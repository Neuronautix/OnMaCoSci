"""Tests for schema alignment: field mapping, transformation rules, adversarial review."""
from __future__ import annotations

import pytest

from mapping_co_scientist.shared.models.evidence import Provenance
from mapping_co_scientist.shared.models.review import ValidationStatus
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import (
    FieldMappingHypothesis,
    CardinalityRelation,
)
from mapping_co_scientist.schema_align.models.transformation_rule import (
    MappingOperation,
    TransformationRule,
)
from mapping_co_scientist.schema_align.agents.field_candidate_generator import FieldCandidateGeneratorAgent
from mapping_co_scientist.schema_align.agents.schema_adversarial_reviewer import SchemaAdversarialReviewerAgent
from mapping_co_scientist.schema_align.agents.schema_validation_agent import SchemaValidationAgent


NOW = "2024-01-01T00:00:00"


def make_prov(**kwargs):
    defaults = dict(created_by="test", created_at=NOW, method="test_v1")
    defaults.update(kwargs)
    return Provenance(**defaults)


def make_src(path: str, label: str, datatype: str = "string", unit: str | None = None) -> SchemaEntity:
    return SchemaEntity(
        entity_id=f"csv:{path}",
        path=path,
        label=label,
        datatype=datatype,
        unit=unit,
        source_type="csv",
    )


def make_tgt(path: str, label: str, datatype: str = "string") -> SchemaEntity:
    return SchemaEntity(
        entity_id=f"json:{path}",
        path=path,
        label=label,
        datatype=datatype,
        source_type="json_schema",
    )


# --- Tests: Field Candidate Generator ---

class TestFieldCandidateGenerator:
    def _source_fields(self):
        return [
            make_src("MouseID", "Mouse ID", "string"),
            make_src("Strain", "Strain", "string"),
            make_src("Sex", "Sex", "string"),
            make_src("Weight_g", "Weight g", "number", unit="g"),
            make_src("Cage", "Cage", "string"),
            make_src("Group", "Group", "string"),
            make_src("DeviceSerial", "Device Serial", "string"),
            make_src("ActivityCount", "Activity Count", "integer"),
            make_src("RecordingDate", "Recording Date", "string"),
        ]

    def _target_fields(self):
        return [
            make_tgt("animal.externalId", "external Id", "string"),
            make_tgt("animal.biologicalAttributes.strain", "strain", "string"),
            make_tgt("animal.biologicalAttributes.sex", "sex", "string"),
            make_tgt("measurements.bodyWeight.value", "body Weight value", "number"),
            make_tgt("measurements.bodyWeight.unit", "body Weight unit", "string"),
            make_tgt("housing.cageIdentifier", "cage Identifier", "string"),
            make_tgt("study.experimentalGroup", "experimental Group", "string"),
            make_tgt("acquisition.device.identifier", "device identifier", "string"),
            make_tgt("measurements.activity.value", "activity value", "number"),
            make_tgt("measurements.activity.date", "activity date", "string"),
        ]

    def test_generates_hypotheses(self):
        gen = FieldCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(self._source_fields(), self._target_fields())
        assert len(hyps) > 0

    def test_weight_maps_to_bodyweight_value(self):
        gen = FieldCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(self._source_fields(), self._target_fields())
        weight_hyps = [h for h in hyps if h.source_path == "Weight_g"]
        assert weight_hyps, "Weight_g should generate at least one hypothesis"
        top = sorted(weight_hyps, key=lambda x: x.confidence, reverse=True)[0]
        assert "bodyWeight" in top.target_path or "weight" in top.target_path.lower(), (
            f"Weight_g should map to bodyWeight path, got: {top.target_path}"
        )

    def test_unit_constant_assignment_generated(self):
        gen = FieldCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(self._source_fields(), self._target_fields())
        unit_hyps = [h for h in hyps if h.mapping_operation == MappingOperation.CONSTANT_ASSIGNMENT]
        assert unit_hyps, "Expected at least one constant_assignment for unit field"
        unit_paths = [h.target_path for h in unit_hyps]
        assert any("unit" in p for p in unit_paths), f"Expected a .unit target, got: {unit_paths}"
        unit_hyp = [h for h in unit_hyps if "unit" in h.target_path][0]
        assert unit_hyp.transformation_rule is not None
        assert unit_hyp.transformation_rule.constant_value == "g"

    def test_nested_path_operation(self):
        gen = FieldCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(self._source_fields(), self._target_fields())
        nested_hyps = [h for h in hyps if h.mapping_operation == MappingOperation.NESTED_PATH]
        # Most mappings to nested JSON paths should be NESTED_PATH
        assert nested_hyps, "Expected at least one NESTED_PATH mapping"

    def test_date_field_mapped(self):
        gen = FieldCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(self._source_fields(), self._target_fields())
        date_hyps = [h for h in hyps if h.source_path == "RecordingDate"]
        assert date_hyps, "RecordingDate should generate at least one hypothesis"

    def test_provenance_recorded(self):
        gen = FieldCandidateGeneratorAgent(top_k=3, pipeline_run_id="sa-test-001")
        hyps = gen.generate(self._source_fields(), self._target_fields())
        assert hyps
        assert hyps[0].provenance.pipeline_run_id == "sa-test-001"


# --- Tests: Transformation Rules ---

class TestTransformationRules:
    def test_direct_copy_rule(self):
        rule = TransformationRule(
            rule_id="rule-001",
            source_path="Sex",
            target_path="animal.biologicalAttributes.sex",
            operation=MappingOperation.DIRECT_COPY,
        )
        assert rule.operation == MappingOperation.DIRECT_COPY
        assert rule.information_loss is False

    def test_constant_assignment_rule(self):
        rule = TransformationRule(
            rule_id="rule-002",
            source_path=None,
            target_path="measurements.bodyWeight.unit",
            operation=MappingOperation.CONSTANT_ASSIGNMENT,
            constant_value="g",
        )
        assert rule.constant_value == "g"
        assert rule.source_path is None

    def test_unit_conversion_rule(self):
        rule = TransformationRule(
            rule_id="rule-003",
            source_path="Weight_g",
            target_path="measurements.bodyWeight.value",
            operation=MappingOperation.UNIT_CONVERSION,
            unit_from="g",
            unit_to="kg",
            unit_conversion_factor=0.001,
        )
        assert rule.unit_conversion_factor == 0.001

    def test_enumeration_remapping(self):
        rule = TransformationRule(
            rule_id="rule-004",
            source_path="Sex",
            target_path="animal.biologicalAttributes.sex",
            operation=MappingOperation.ENUMERATION_REMAPPING,
            enumeration_map={"Male": "M", "Female": "F"},
        )
        assert rule.enumeration_map["Male"] == "M"

    def test_unmapped_operation(self):
        rule = TransformationRule(
            rule_id="rule-005",
            source_path="UnknownField",
            target_path="",
            operation=MappingOperation.UNMAPPED,
        )
        assert rule.operation == MappingOperation.UNMAPPED


# --- Tests: Adversarial Review ---

class TestSchemaAdversarialReviewer:
    def _make_hyp(
        self,
        operation: MappingOperation = MappingOperation.DIRECT_COPY,
        source_dt: str = "string",
        target_dt: str = "string",
        confidence: float = 0.80,
        info_loss: bool = False,
        info_loss_desc: str | None = None,
    ) -> FieldMappingHypothesis:
        return FieldMappingHypothesis(
            mapping_id="test-sa-map-001",
            source_path="TestField",
            target_path="target.testField",
            mapping_operation=operation,
            confidence=confidence,
            source_datatype=source_dt,
            target_datatype=target_dt,
            information_loss=info_loss,
            information_loss_description=info_loss_desc,
            provenance=make_prov(),
        )

    def test_datatype_mismatch_flagged(self):
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = self._make_hyp(source_dt="string", target_dt="number")
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "datatype_mismatch" in flag_types

    def test_information_loss_flagged_high(self):
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = self._make_hyp(
            info_loss=True,
            info_loss_desc="Source enum values not in target",
        )
        result = reviewer.review(hyp)
        assert result.overall_severity == "high"
        flag_types = [f.flag_type for f in result.flags]
        assert "information_loss" in flag_types

    def test_unmapped_flagged_medium(self):
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = self._make_hyp(operation=MappingOperation.UNMAPPED, confidence=0.0)
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "unmapped_field" in flag_types

    def test_activity_count_ambiguity_flagged(self):
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = FieldMappingHypothesis(
            mapping_id="test-activity",
            source_path="ActivityCount",
            target_path="measurements.activity.value",
            mapping_operation=MappingOperation.NESTED_PATH,
            confidence=0.55,
            source_datatype="integer",
            target_datatype="number",
            provenance=make_prov(),
        )
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "ambiguous_measurement" in flag_types, (
            "ActivityCount should be flagged as ambiguous measurement requiring contextual definition"
        )

    def test_clean_mapping_proceeds(self):
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = self._make_hyp(operation=MappingOperation.DIRECT_COPY, confidence=0.90)
        result = reviewer.review(hyp)
        assert result.recommendation in ("proceed", "review")

    def test_no_sssom_predicates_in_schema_align(self):
        """schema-align must not produce SKOS predicates or SSSOM output."""
        reviewer = SchemaAdversarialReviewerAgent()
        hyp = self._make_hyp()
        result = reviewer.review(hyp)
        # Check no SKOS predicates appear in flag types or descriptions
        for flag in result.flags:
            assert "skos:" not in flag.flag_type
            assert "skos:" not in flag.description
            assert "owl:" not in flag.flag_type


# --- Tests: Schema Validation Agent ---

class TestSchemaValidationAgent:
    def _make_hyp(self, operation: MappingOperation, info_loss: bool = False) -> FieldMappingHypothesis:
        return FieldMappingHypothesis(
            mapping_id="val-sa-001",
            source_path="TestField",
            target_path="target.field",
            mapping_operation=operation,
            confidence=0.75,
            source_datatype="string",
            target_datatype="string",
            information_loss=info_loss,
            information_loss_description="Loss description" if info_loss else None,
            provenance=make_prov(),
        )

    def test_direct_copy_passes(self):
        agent = SchemaValidationAgent()
        hyp = self._make_hyp(MappingOperation.DIRECT_COPY)
        [result] = agent.validate_all([hyp])
        assert result.validation_status == ValidationStatus.PASSED

    def test_info_loss_warns(self):
        agent = SchemaValidationAgent()
        hyp = self._make_hyp(MappingOperation.DIRECT_COPY, info_loss=True)
        [result] = agent.validate_all([hyp])
        assert result.validation_status == ValidationStatus.WARNING
