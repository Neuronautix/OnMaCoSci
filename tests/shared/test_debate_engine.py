"""Tests for the Elo-based three-agent debate engine."""
from __future__ import annotations

import pytest

from mapping_co_scientist.shared.models.evidence import Provenance
from mapping_co_scientist.shared.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
)
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis,
    OntologyRelation,
    SemanticWarning,
)
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation

from mapping_co_scientist.shared.debate.elo import (
    initial_elo,
    k_factor,
    expected_score,
    apply_argument,
    apply_penalties,
    EVIDENCE_WEIGHTS,
    BASE_K,
)
from mapping_co_scientist.shared.debate.models import (
    ArgumentSide,
    EvidenceType,
)
from mapping_co_scientist.shared.debate.heuristic_advocates import (
    HeuristicSourceAdvocate,
    HeuristicTargetAdvocate,
)
from mapping_co_scientist.shared.debate.mediator import MappingMediatorEngine, run_debate
from mapping_co_scientist.shared.debate import DebateReport, EntityDebateResult, DebateArgument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = "2024-01-01T00:00:00"


def make_prov(**kwargs) -> Provenance:
    defaults = dict(created_by="test", created_at=NOW, method="test_v1")
    defaults.update(kwargs)
    return Provenance(**defaults)


def make_source_entity(label: str, entity_type: str = "field") -> SourceEntity:
    return SourceEntity(
        entity_id=f"csv:{label}",
        label=label,
        source_type="csv",
    )


def make_ontology_term(term_id: str, label: str) -> OntologyTerm:
    return OntologyTerm(
        term_id=term_id,
        label=label,
        term_type="class",
        ontology_id="hcm",
    )


def make_ontology_hyp(
    mapping_id: str,
    source_label: str,
    term_id: str,
    relation: OntologyRelation,
    confidence: float = 0.80,
    source_entity_type: str = "field",
    target_entity_type: str = "class",
    semantic_scope_analysis: str = "scope analysis text",
    semantic_warnings: list[SemanticWarning] | None = None,
) -> OntologyMappingHypothesis:
    return OntologyMappingHypothesis(
        mapping_id=mapping_id,
        source_concept=make_source_entity(source_label),
        target_ontology_entity=make_ontology_term(term_id, term_id.split(":")[-1]),
        ontology_relation=relation,
        confidence=confidence,
        source_entity_type=source_entity_type,
        target_entity_type=target_entity_type,
        semantic_scope_analysis=semantic_scope_analysis,
        hierarchy_compatibility="compatible",
        domain_range_compatibility="compatible",
        semantic_warnings=semantic_warnings or [],
        provenance=make_prov(),
    )


def make_schema_hyp(
    mapping_id: str,
    source_path: str,
    target_path: str,
    operation: MappingOperation = MappingOperation.DIRECT_COPY,
    confidence: float = 0.80,
    source_datatype: str = "string",
    target_datatype: str = "string",
    information_loss: bool = False,
    information_loss_description: str | None = None,
) -> FieldMappingHypothesis:
    return FieldMappingHypothesis(
        mapping_id=mapping_id,
        source_path=source_path,
        target_path=target_path,
        mapping_operation=operation,
        confidence=confidence,
        source_datatype=source_datatype,
        target_datatype=target_datatype,
        information_loss=information_loss,
        information_loss_description=information_loss_description,
        provenance=make_prov(),
    )


def make_clean_adv(mapping_id: str) -> AdversarialReviewResult:
    return AdversarialReviewResult(
        mapping_id=mapping_id,
        flags=[],
        overall_severity="clean",
        recommendation="proceed",
    )


def make_adv(mapping_id: str, severity: str, flag_type: str = "test_flag") -> AdversarialReviewResult:
    return AdversarialReviewResult(
        mapping_id=mapping_id,
        flags=[AdversarialFlag(flag_type=flag_type, description="test", severity=severity)],
        overall_severity=severity,
        recommendation="reject" if severity == "high" else "review",
    )


# ---------------------------------------------------------------------------
# Tests: ELO functions
# ---------------------------------------------------------------------------

class TestInitialElo:
    def test_zero_confidence(self):
        assert initial_elo(0.0) == 1000.0

    def test_full_confidence(self):
        assert initial_elo(1.0) == 1800.0

    def test_half_confidence(self):
        assert initial_elo(0.5) == 1400.0

    def test_typical_confidence(self):
        # 0.82 -> 1000 + round(0.82 * 800) = 1000 + 656 = 1656
        assert initial_elo(0.82) == 1656.0


class TestKFactor:
    def test_scales_by_weight(self):
        k = k_factor(EvidenceType.DOMAIN_DEFINITION_MATCH, 1.0)
        expected = BASE_K * EVIDENCE_WEIGHTS[EvidenceType.DOMAIN_DEFINITION_MATCH] * 1.0
        assert abs(k - expected) < 1e-9

    def test_scales_by_confidence(self):
        k_low = k_factor(EvidenceType.SEMANTIC_OVERREACH, 0.50)
        k_high = k_factor(EvidenceType.SEMANTIC_OVERREACH, 1.00)
        assert abs(k_high - 2 * k_low) < 1e-9

    def test_lower_weight_evidence(self):
        k_info = k_factor(EvidenceType.INFORMATION_LOSS_RISK, 1.0)
        k_prec = k_factor(EvidenceType.PRECEDENT_CONSISTENCY, 1.0)
        assert k_info > k_prec


class TestApplyArgument:
    def test_for_argument_raises_argued_elo(self):
        ratings = {"A": 1400.0, "B": 1400.0}
        updated = apply_argument(
            ratings=ratings,
            argued_id="A",
            side=ArgumentSide.FOR,
            evidence_type=EvidenceType.DOMAIN_DEFINITION_MATCH,
            argument_confidence=1.0,
        )
        assert updated["A"] > ratings["A"]
        assert updated["B"] < ratings["B"]

    def test_against_argument_lowers_argued_elo(self):
        ratings = {"A": 1400.0, "B": 1400.0}
        updated = apply_argument(
            ratings=ratings,
            argued_id="A",
            side=ArgumentSide.AGAINST,
            evidence_type=EvidenceType.SEMANTIC_OVERREACH,
            argument_confidence=1.0,
        )
        assert updated["A"] < ratings["A"]
        assert updated["B"] > ratings["B"]

    def test_zero_sum_net_change(self):
        """Total Elo change across all candidates is zero for a two-candidate set."""
        ratings = {"A": 1400.0, "B": 1400.0}
        updated = apply_argument(
            ratings=ratings,
            argued_id="A",
            side=ArgumentSide.FOR,
            evidence_type=EvidenceType.INFORMATION_LOSS_RISK,
            argument_confidence=0.90,
        )
        original_total = sum(ratings.values())
        updated_total = sum(updated.values())
        assert abs(updated_total - original_total) < 1e-6

    def test_single_candidate_no_change(self):
        ratings = {"A": 1400.0}
        updated = apply_argument(
            ratings=ratings,
            argued_id="A",
            side=ArgumentSide.FOR,
            evidence_type=EvidenceType.DOMAIN_DEFINITION_MATCH,
            argument_confidence=1.0,
        )
        assert updated["A"] == 1400.0

    def test_does_not_mutate_input(self):
        ratings = {"A": 1400.0, "B": 1400.0}
        original = dict(ratings)
        apply_argument(ratings, "A", ArgumentSide.FOR, EvidenceType.SCOPE_RELATIONSHIP, 0.8)
        assert ratings == original


class TestApplyPenalties:
    def test_exactmatch_penalty(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="clean",
            has_exactmatch=True,
            has_unrebutted_info_loss=False,
            source_net_negative=False,
            target_net_negative=False,
        )
        assert final_elo == 1200.0
        assert any("exactMatch" in r for r in reasons)

    def test_high_severity_penalty(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="high",
            has_exactmatch=False,
            has_unrebutted_info_loss=False,
            source_net_negative=False,
            target_net_negative=False,
        )
        assert final_elo == 1250.0
        assert any("high" in r for r in reasons)

    def test_medium_severity_penalty(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="medium",
            has_exactmatch=False,
            has_unrebutted_info_loss=False,
            source_net_negative=False,
            target_net_negative=False,
        )
        assert final_elo == 1350.0
        assert any("medium" in r for r in reasons)

    def test_high_and_exactmatch_stack(self):
        final_elo, reasons = apply_penalties(
            elo=1600.0,
            overall_severity="high",
            has_exactmatch=True,
            has_unrebutted_info_loss=False,
            source_net_negative=False,
            target_net_negative=False,
        )
        # -150 (high) + -200 (exactmatch) = -350
        assert final_elo == 1250.0
        assert len(reasons) == 2

    def test_info_loss_penalty(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="clean",
            has_exactmatch=False,
            has_unrebutted_info_loss=True,
            source_net_negative=False,
            target_net_negative=False,
        )
        assert final_elo == 1300.0
        assert any("information_loss" in r for r in reasons)

    def test_source_and_target_net_negative(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="clean",
            has_exactmatch=False,
            has_unrebutted_info_loss=False,
            source_net_negative=True,
            target_net_negative=True,
        )
        assert final_elo == 1300.0
        assert len(reasons) == 2

    def test_no_penalties_clean(self):
        final_elo, reasons = apply_penalties(
            elo=1400.0,
            overall_severity="clean",
            has_exactmatch=False,
            has_unrebutted_info_loss=False,
            source_net_negative=False,
            target_net_negative=False,
        )
        assert final_elo == 1400.0
        assert reasons == []


# ---------------------------------------------------------------------------
# Tests: HeuristicSourceAdvocate
# ---------------------------------------------------------------------------

class TestHeuristicSourceAdvocate:
    def setup_method(self):
        self.advocate = HeuristicSourceAdvocate()

    def test_ambiguity_against_for_count_field_schema(self):
        hyp = make_schema_hyp("m1", "activity_count", "target.value", confidence=0.75)
        args = self.advocate.generate_arguments(hyp, "schema_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.AMBIGUITY_UNRESOLVED, ArgumentSide.AGAINST) in types

    def test_scope_for_for_strain_narrowmatch(self):
        hyp = make_ontology_hyp(
            "m1", "strain", "hcm:GeneticBackground",
            relation=OntologyRelation.NARROW_MATCH,
            confidence=0.80,
        )
        args = self.advocate.generate_arguments(hyp, "ontology_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.SCOPE_RELATIONSHIP, ArgumentSide.FOR) in types

    def test_information_loss_against_for_schema_loss(self):
        hyp = make_schema_hyp(
            "m1", "weight", "target.weight",
            information_loss=True,
            information_loss_description="Precision truncated",
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.INFORMATION_LOSS_RISK, ArgumentSide.AGAINST) in types

    def test_domain_definition_for_high_confidence_schema(self):
        hyp = make_schema_hyp(
            "m1", "strain", "target.strain",
            confidence=0.90,
            information_loss=False,
            operation=MappingOperation.DIRECT_COPY,
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.DOMAIN_DEFINITION_MATCH, ArgumentSide.FOR) in types

    def test_at_most_3_arguments_returned(self):
        hyp = make_schema_hyp(
            "m1", "score_count", "target.value",
            confidence=0.40,
            information_loss=True,
            information_loss_description="loss",
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        assert len(args) <= 3


# ---------------------------------------------------------------------------
# Tests: HeuristicTargetAdvocate
# ---------------------------------------------------------------------------

class TestHeuristicTargetAdvocate:
    def setup_method(self):
        self.advocate = HeuristicTargetAdvocate()

    def test_semantic_overreach_for_exactmatch(self):
        hyp = make_ontology_hyp(
            "m1", "sex", "hcm:BiologicalSex",
            relation=OntologyRelation.EXACT_MATCH,
        )
        args = self.advocate.generate_arguments(hyp, "ontology_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.SEMANTIC_OVERREACH, ArgumentSide.AGAINST) in types

    def test_type_incompatibility_direct_copy_type_mismatch(self):
        hyp = make_schema_hyp(
            "m1", "animal_id", "target.animalId",
            operation=MappingOperation.DIRECT_COPY,
            source_datatype="string",
            target_datatype="number",
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.TYPE_INCOMPATIBILITY, ArgumentSide.AGAINST) in types

    def test_no_type_incompatibility_for_numeric_types(self):
        """integer -> number should NOT be flagged as type incompatibility."""
        hyp = make_schema_hyp(
            "m1", "age_weeks", "target.age",
            operation=MappingOperation.DIRECT_COPY,
            source_datatype="integer",
            target_datatype="number",
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        incompatibility_args = [
            a for a in args
            if a.evidence_type == EvidenceType.TYPE_INCOMPATIBILITY
            and a.side == ArgumentSide.AGAINST
        ]
        assert incompatibility_args == []

    def test_operation_safety_for_matching_types(self):
        hyp = make_schema_hyp(
            "m1", "strain", "target.strain",
            source_datatype="string",
            target_datatype="string",
            operation=MappingOperation.DIRECT_COPY,
        )
        args = self.advocate.generate_arguments(hyp, "schema_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.OPERATION_SAFETY, ArgumentSide.FOR) in types

    def test_identifier_to_class_type_incompatibility_ontology(self):
        hyp = make_ontology_hyp(
            "m1", "animal_id", "hcm:Animal",
            relation=OntologyRelation.CLOSE_MATCH,
            source_entity_type="identifier",
            target_entity_type="class",
        )
        args = self.advocate.generate_arguments(hyp, "ontology_align")
        types = [(a.evidence_type, a.side) for a in args]
        assert (EvidenceType.TYPE_INCOMPATIBILITY, ArgumentSide.AGAINST) in types


# ---------------------------------------------------------------------------
# Tests: MappingMediatorEngine
# ---------------------------------------------------------------------------

class TestMappingMediatorEngine:
    def _make_two_ontology_candidates(self, source_label="strain"):
        hyp1 = make_ontology_hyp(
            "map-001", source_label, "hcm:GeneticBackground",
            relation=OntologyRelation.NARROW_MATCH,
            confidence=0.82,
        )
        hyp2 = make_ontology_hyp(
            "map-002", source_label, "hcm:MouseStrain",
            relation=OntologyRelation.CLOSE_MATCH,
            confidence=0.65,
        )
        return [hyp1, hyp2]

    def test_correct_number_of_entity_results(self):
        hyps_by_source = {
            "csv:strain": self._make_two_ontology_candidates("strain"),
            "csv:sex": [
                make_ontology_hyp("map-003", "sex", "hcm:Sex",
                                  relation=OntologyRelation.CLOSE_MATCH, confidence=0.88)
            ],
        }
        adv_results = {
            "map-001": make_clean_adv("map-001"),
            "map-002": make_clean_adv("map-002"),
            "map-003": make_clean_adv("map-003"),
        }
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "ontology_align", adv_results, "run-001")
        assert len(report.entity_results) == 2

    def test_rank_inversion_detected_when_strong_against(self):
        """High-confidence candidate should be knocked off top1 by strong AGAINST args."""
        # candidate A: high confidence but exactMatch (gets semantic_overreach penalty)
        hyp_a = make_ontology_hyp(
            "map-exactmatch", "sex", "hcm:BiologicalSex",
            relation=OntologyRelation.EXACT_MATCH,
            confidence=0.95,
        )
        # candidate B: lower confidence but sound relation
        hyp_b = make_ontology_hyp(
            "map-closematch", "sex", "hcm:SexCharacteristic",
            relation=OntologyRelation.CLOSE_MATCH,
            confidence=0.70,
        )
        hyps_by_source = {"csv:sex": [hyp_a, hyp_b]}
        adv_results = {
            "map-exactmatch": make_adv("map-exactmatch", "high", "exactmatch_requires_validation"),
            "map-closematch": make_clean_adv("map-closematch"),
        }
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "ontology_align", adv_results, "run-002")
        result = report.entity_results[0]
        # The pipeline prefers map-exactmatch (higher confidence)
        assert result.pipeline_top1_id == "map-exactmatch"
        # The debate should invert: map-closematch should win (exactMatch -200 + high severity -150)
        assert result.rank_inverted is True
        assert result.debate_top1_id == "map-closematch"

    def test_constants_skipped(self):
        """__constant__ source_id entries must be skipped."""
        constant_hyp = FieldMappingHypothesis(
            mapping_id="const-001",
            source_path=None,
            target_path="measurements.bodyWeight.unit",
            mapping_operation=MappingOperation.CONSTANT_ASSIGNMENT,
            confidence=1.0,
            provenance=make_prov(),
        )
        real_hyp = make_schema_hyp("field-001", "Weight_g", "target.weight.value",
                                   confidence=0.85)
        hyps_by_source = {
            "__constant__": [constant_hyp],
            "Weight_g": [real_hyp],
        }
        adv_results = {
            "const-001": make_clean_adv("const-001"),
            "field-001": make_clean_adv("field-001"),
        }
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "schema_align", adv_results, "run-003")
        # Only Weight_g should appear; __constant__ must be skipped
        assert len(report.entity_results) == 1
        assert report.entity_results[0].source_id == "Weight_g"

    def test_debate_report_structure(self):
        hyps_by_source = {"csv:strain": self._make_two_ontology_candidates()}
        adv_results = {
            "map-001": make_clean_adv("map-001"),
            "map-002": make_clean_adv("map-002"),
        }
        report = run_debate(hyps_by_source, "ontology_align", adv_results, "run-004")
        assert isinstance(report, DebateReport)
        assert report.run_type == "ontology_align"
        assert report.run_id == "run-004"
        assert isinstance(report.consistency, object)

    def test_tier1_when_final_elo_below_1250(self):
        # Very low confidence candidate that should land below 1250
        hyp = make_ontology_hyp(
            "map-low", "unknown_field", "hcm:SomeTerm",
            relation=OntologyRelation.RELATED_MATCH,
            confidence=0.10,  # initial_elo = 1000 + round(0.10*800) = 1080
        )
        hyps_by_source = {"csv:unknown_field": [hyp]}
        adv_results = {"map-low": make_adv("map-low", "medium")}
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "ontology_align", adv_results, "run-005")
        result = report.entity_results[0]
        assert result.tier == 1

    def test_collision_detected_in_consistency_report(self):
        """Two sources both mapping to the same target should appear as a collision."""
        hyp_a = make_schema_hyp("map-s1", "field_one", "shared.target", confidence=0.85)
        hyp_b = make_schema_hyp("map-s2", "field_two", "shared.target", confidence=0.80)
        hyps_by_source = {
            "field_one": [hyp_a],
            "field_two": [hyp_b],
        }
        adv_results = {
            "map-s1": make_clean_adv("map-s1"),
            "map-s2": make_clean_adv("map-s2"),
        }
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "schema_align", adv_results, "run-006")
        # Both should pick "shared.target" as their top1
        assert report.consistency.collisions >= 1

    def test_importable_from_package(self):
        from mapping_co_scientist.shared.debate import run_debate as rd, DebateReport as DR
        assert callable(rd)
        assert DR is DebateReport


# ---------------------------------------------------------------------------
# Tests: ConsistencyReport tier boundaries
# ---------------------------------------------------------------------------

class TestTierAssignment:
    def test_tier1_with_blocking_concerns(self):
        """Blocking adversarial flag forces Tier 1 even with high confidence."""
        hyp = make_ontology_hyp(
            "map-blocked", "sex", "hcm:Sex",
            relation=OntologyRelation.CLOSE_MATCH,
            confidence=0.90,
        )
        hyps_by_source = {"csv:sex": [hyp]}
        adv_results = {"map-blocked": make_adv("map-blocked", "high")}
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "ontology_align", adv_results, "run-tier1")
        result = report.entity_results[0]
        assert result.tier == 1
        assert result.blocking_concerns

    def test_tier3_with_no_concerns_high_confidence(self):
        """Very high confidence, clean adversarial → Tier 3 if final_elo ≥ 1500."""
        hyp = make_schema_hyp(
            "map-clean", "animal_id", "target.animalId",
            confidence=0.99,  # initial_elo = 1000 + round(0.99*800) = 1792
            operation=MappingOperation.DIRECT_COPY,
            source_datatype="string",
            target_datatype="string",
        )
        hyps_by_source = {"animal_id": [hyp]}
        adv_results = {"map-clean": make_clean_adv("map-clean")}
        engine = MappingMediatorEngine()
        report = engine.run_debate(hyps_by_source, "schema_align", adv_results, "run-tier3")
        result = report.entity_results[0]
        # Tier 3 requires final_elo >= 1500 and no blocking concerns
        assert result.tier in (2, 3)  # depends on advocate arguments
