"""Tests for the Phase 3 validation infrastructure.

Covers:
- DatatypeValidator (V1)
- TransformationValidator (V2)
- UnitConsistency / pint-based unit check (V3)
- SHACLValidator (V4)
- SPARQLCompetencyAgent (V5)
- Extended ValidationAgent methods
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    HumanReviewStatus,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
    ValidationStatus,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_provenance() -> Provenance:
    return Provenance(
        created_by="TestAgent",
        created_at="2025-01-01T00:00:00Z",
        method="test",
    )


def _make_source(
    entity_id: str = "csv:test.field",
    label: str = "test field",
    datatype: str | None = "number",
    source_type: str = "csv",
) -> SourceEntity:
    return SourceEntity(
        entity_id=entity_id,
        label=label,
        datatype=datatype,
        source_type=source_type,
    )


def _make_target(
    term_id: str = "ont:TestTerm",
    label: str = "Test Term",
    term_type: str = "property",
    ontology_id: str = "ont",
    extra_context: dict | None = None,
) -> OntologyTerm:
    return OntologyTerm(
        term_id=term_id,
        label=label,
        term_type=term_type,
        ontology_id=ontology_id,
        extra_context=extra_context or {},
    )


def _make_hypothesis(
    mapping_id: str = "map-001",
    source: SourceEntity | None = None,
    target: OntologyTerm | None = None,
    predicate: MappingPredicate = MappingPredicate.EXACT_MATCH,
    confidence: float = 0.9,
    required_conditions: list[str] | None = None,
    evidence: list[Evidence] | None = None,
) -> MappingHypothesis:
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source or _make_source(),
        target_entity=target or _make_target(),
        predicate=predicate,
        confidence=confidence,
        required_conditions=required_conditions or [],
        evidence=evidence or [Evidence(evidence_type="test", description="test evidence", score=0.9)],
        provenance=_make_provenance(),
    )


# ===========================================================================
# V1: DatatypeValidator tests
# ===========================================================================


class TestDatatypeValidator:
    """Tests for scoring/datatype_validator.py"""

    def test_datatype_validator_number_to_property_compatible(self):
        """number datatype -> property term_type -> no flag (compatible)."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
            check_datatype_compatibility,
        )

        source = _make_source(datatype="number")
        target = _make_target(term_type="property")

        compatible, reason = check_datatype_compatibility(source, target)
        assert compatible is True
        assert reason == ""

        flag = build_datatype_flag(source, target)
        assert flag is None

    def test_datatype_validator_object_to_property_incompatible(self):
        """object datatype -> property term_type -> flag raised (object maps to class)."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
            check_datatype_compatibility,
        )

        source = _make_source(datatype="object")
        target = _make_target(term_type="property")

        compatible, reason = check_datatype_compatibility(source, target)
        assert compatible is False
        assert "object" in reason
        assert "property" in reason

        flag = build_datatype_flag(source, target)
        assert flag is not None
        assert flag.flag_type == "datatype_incompatibility"
        assert flag.severity == "medium"

    def test_datatype_validator_unknown_permissive(self):
        """unknown datatype -> no flag (permissive)."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
        )

        source = _make_source(datatype="unknown")
        target = _make_target(term_type="property")
        flag = build_datatype_flag(source, target)
        assert flag is None

    def test_datatype_validator_boolean_to_class(self):
        """boolean datatype -> class term_type -> medium flag raised."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
            check_datatype_compatibility,
        )

        source = _make_source(datatype="boolean")
        target = _make_target(term_type="class")

        compatible, reason = check_datatype_compatibility(source, target)
        assert compatible is False
        assert "boolean" in reason

        flag = build_datatype_flag(source, target)
        assert flag is not None
        assert flag.severity == "medium"
        assert flag.flag_type == "datatype_incompatibility"

    def test_datatype_flag_none_when_no_term_type(self):
        """target has empty term_type -> no flag (permissive when no info)."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
        )

        source = _make_source(datatype="number")
        # OntologyTerm requires term_type field but empty string means "no info"
        target = OntologyTerm(
            term_id="ont:T",
            label="T",
            term_type="",   # empty = no info -> permissive
            ontology_id="ont",
        )

        flag = build_datatype_flag(source, target)
        assert flag is None

    def test_datatype_validator_none_datatype_treated_as_unknown(self):
        """None datatype -> treated as 'unknown' -> permissive."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            build_datatype_flag,
        )

        source = _make_source(datatype=None)
        target = _make_target(term_type="property")
        flag = build_datatype_flag(source, target)
        assert flag is None

    def test_datatype_validator_range_check_incompatible(self):
        """number datatype + xsd:boolean range -> incompatible."""
        from ontology_mapping_co_scientist.scoring.datatype_validator import (
            check_datatype_compatibility,
        )

        source = _make_source(datatype="number")
        target = _make_target(
            term_type="property",
            extra_context={"range": "xsd:boolean"},
        )

        compatible, reason = check_datatype_compatibility(source, target)
        assert compatible is False
        assert "xsd:boolean" in reason


# ===========================================================================
# V2: TransformationValidator tests
# ===========================================================================


class TestTransformationValidator:
    """Tests for scoring/transformation_validator.py"""

    def test_transform_validator_no_conditions_gives_warning(self):
        """requiresTransform with empty required_conditions -> WARNING."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            validate_transform_mapping,
        )

        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=[],
        )
        status, messages = validate_transform_mapping(hyp)
        assert status == ValidationStatus.WARNING
        assert len(messages) == 1
        assert "no transform specified" in messages[0].lower()

    def test_transform_validator_actionable_condition_passes(self):
        """Actionable condition like 'convert ng/mL to µmol/L' -> PASSED."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            validate_transform_mapping,
        )

        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=["convert ng/mL to µmol/L using MW=412.5"],
        )
        status, messages = validate_transform_mapping(hyp)
        assert status == ValidationStatus.PASSED
        assert messages == []

    def test_transform_validator_vague_condition_warns(self):
        """'requires transformation' -> WARNING."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            validate_transform_mapping,
        )

        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=["requires transformation"],
        )
        status, messages = validate_transform_mapping(hyp)
        assert status == ValidationStatus.WARNING
        assert len(messages) >= 1
        assert "vague or not actionable" in messages[0].lower()

    def test_transform_validator_non_transform_mapping_skipped(self):
        """exactMatch predicate -> (PASSED, []) without checking conditions."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            validate_transform_mapping,
        )

        hyp = _make_hypothesis(
            predicate=MappingPredicate.EXACT_MATCH,
            required_conditions=["requires transformation"],
        )
        status, messages = validate_transform_mapping(hyp)
        assert status == ValidationStatus.PASSED
        assert messages == []

    def test_parse_transform_condition_unit_conversion(self):
        """Unit conversion condition is parsed as unit_conversion + actionable."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            parse_transform_condition,
        )

        spec = parse_transform_condition("convert ng/mL to µmol/L using MW=412.5")
        assert spec.transform_type == "unit_conversion"
        assert spec.is_actionable is True

    def test_parse_transform_condition_vocabulary_lookup(self):
        """Vocabulary lookup condition parsed correctly."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            parse_transform_condition,
        )

        spec = parse_transform_condition("map sex codes M/F to male/female")
        assert spec.transform_type == "vocabulary_lookup"
        assert spec.is_actionable is True

    def test_parse_transform_condition_vague(self):
        """'requires transformation' -> unknown, not actionable."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            parse_transform_condition,
        )

        spec = parse_transform_condition("requires transformation")
        assert spec.transform_type == "unknown"
        assert spec.is_actionable is False

    def test_transform_validator_vocabulary_mapping_passes(self):
        """A vocabulary mapping condition is actionable -> PASSED."""
        from ontology_mapping_co_scientist.scoring.transformation_validator import (
            validate_transform_mapping,
        )

        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=["map sex codes M/F to male/female"],
        )
        status, messages = validate_transform_mapping(hyp)
        assert status == ValidationStatus.PASSED
        assert messages == []


# ===========================================================================
# V3: UnitConsistency tests
# ===========================================================================


class TestUnitConsistency:
    """Tests for scoring/unit_consistency.py"""

    def test_unit_consistency_falls_back_gracefully(self):
        """When pint is unavailable, falls back to regex fallback without crashing."""
        from ontology_mapping_co_scientist.scoring import unit_consistency

        original_has_pint = unit_consistency.HAS_PINT
        try:
            unit_consistency.HAS_PINT = False
            # Same concentration group -> compatible
            compatible, reason = unit_consistency.check_unit_compatibility_pint(
                ["ng/mL"], ["g/dL"]
            )
            # Both are in the mass/conc group -> compatible in regex fallback
            assert isinstance(compatible, bool)
            assert isinstance(reason, str)
        finally:
            unit_consistency.HAS_PINT = original_has_pint

    def test_unit_consistency_empty_lists_compatible(self):
        """Empty source or target units -> compatible (inconclusive)."""
        from ontology_mapping_co_scientist.scoring.unit_consistency import (
            check_unit_compatibility_pint,
        )

        assert check_unit_compatibility_pint([], ["ng/mL"]) == (True, "")
        assert check_unit_compatibility_pint(["ng/mL"], []) == (True, "")
        assert check_unit_compatibility_pint([], []) == (True, "")

    def test_unit_consistency_get_unit_compatibility_no_crash(self):
        """get_unit_compatibility runs without crashing on real entities."""
        from ontology_mapping_co_scientist.scoring.unit_consistency import (
            get_unit_compatibility,
        )

        source = _make_source(label="plasma concentration ng/mL", datatype="number")
        target = _make_target(label="concentration measurement", term_type="property")
        compatible, reason = get_unit_compatibility(source, target)
        assert isinstance(compatible, bool)
        assert isinstance(reason, str)

    def test_unit_consistency_opaque_group_incompatibility(self):
        """cell counts vs enzyme activity are incompatible opaque groups."""
        from ontology_mapping_co_scientist.scoring.unit_consistency import (
            check_unit_compatibility_pint,
        )

        compatible, reason = check_unit_compatibility_pint(
            ["10^9/L"], ["U/L"]
        )
        assert compatible is False
        assert reason != ""


# ===========================================================================
# V4: SHACLValidator tests
# ===========================================================================


class TestSHACLValidator:
    """Tests for validation/shacl_validator.py"""

    def test_shacl_validator_no_shapes_returns_conforms(self):
        """SHACLValidator() with no path -> conforms=True for any hypothesis."""
        from ontology_mapping_co_scientist.validation.shacl_validator import (
            SHACLValidator,
        )

        validator = SHACLValidator()
        hyp = _make_hypothesis()
        result = validator.validate_hypothesis(hyp)
        assert result.conforms is True
        assert result.violation_messages == []
        assert result.shapes_used is None

    def test_shacl_validator_import_error_on_unavailable(self):
        """When pyshacl is unavailable, importing with a path raises ImportError."""
        from ontology_mapping_co_scientist.validation import shacl_validator

        original_has_shacl = shacl_validator.HAS_SHACL
        try:
            shacl_validator.HAS_SHACL = False
            with pytest.raises(ImportError, match="pyshacl"):
                shacl_validator.SHACLValidator("some/path.ttl")
        finally:
            shacl_validator.HAS_SHACL = original_has_shacl

    def test_shacl_validator_result_structure(self):
        """SHACLValidationResult has expected fields."""
        from ontology_mapping_co_scientist.validation.shacl_validator import (
            SHACLValidationResult,
        )

        result = SHACLValidationResult(
            mapping_id="map-001",
            conforms=True,
            violation_messages=[],
            shapes_used=None,
        )
        assert result.mapping_id == "map-001"
        assert result.conforms is True
        assert result.violation_messages == []

    def test_shacl_validator_validate_hypotheses_returns_list(self):
        """validate_hypotheses returns a list with one result per hypothesis."""
        from ontology_mapping_co_scientist.validation.shacl_validator import (
            SHACLValidator,
        )

        validator = SHACLValidator()
        hyps = [_make_hypothesis(mapping_id=f"map-{i:03d}") for i in range(3)]
        results = validator.validate_hypotheses(hyps)
        assert len(results) == 3
        assert all(r.conforms is True for r in results)


# ===========================================================================
# V5: SPARQLCompetencyAgent tests
# ===========================================================================


class TestSPARQLCompetencyAgent:
    """Tests for validation/sparql_competency.py"""

    def test_sparql_agent_built_in_cqs_run(self):
        """Built-in CQs run on sample hypotheses and return a list of CQResults."""
        from ontology_mapping_co_scientist.validation.sparql_competency import (
            SPARQLCompetencyAgent,
        )

        agent = SPARQLCompetencyAgent()
        hyps = [_make_hypothesis(mapping_id="map-001")]
        results = agent.run_cqs(hyps)
        assert isinstance(results, list)
        assert len(results) == len(agent.BUILT_IN_CQS)

    def test_sparql_cq_result_structure(self):
        """CQResult has cq_id, passed, description, severity fields."""
        from ontology_mapping_co_scientist.validation.sparql_competency import CQResult

        result = CQResult(
            cq_id="CQ001",
            passed=True,
            description="A test question",
            severity="warning",
        )
        assert result.cq_id == "CQ001"
        assert result.passed is True
        assert result.description == "A test question"
        assert result.severity == "warning"

    def test_sparql_agent_summary_keys(self):
        """summary() returns dict with expected keys."""
        from ontology_mapping_co_scientist.validation.sparql_competency import (
            CQResult,
            SPARQLCompetencyAgent,
        )

        agent = SPARQLCompetencyAgent()
        results = [
            CQResult(cq_id="CQ001", passed=True, description="d1", severity="warning"),
            CQResult(cq_id="CQ002", passed=False, description="d2", severity="error"),
        ]
        summary = agent.summary(results)
        assert set(summary.keys()) == {"total", "passed", "failed", "errors", "warnings"}
        assert summary["total"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["errors"] == 1
        assert summary["warnings"] == 0

    def test_sparql_agent_extra_cqs(self):
        """Extra CQs are included in the agent's CQ list."""
        from ontology_mapping_co_scientist.validation.sparql_competency import (
            CompetencyQuestion,
            SPARQLCompetencyAgent,
        )

        extra = CompetencyQuestion(
            cq_id="CQ-EXTRA",
            description="Extra question",
            sparql="PREFIX omcs: <https://w3id.org/omcs/mapping#> ASK { ?s a omcs:MappingHypothesis }",
            severity="warning",
        )
        agent = SPARQLCompetencyAgent(extra_cqs=[extra])
        assert len(agent.cqs) == len(SPARQLCompetencyAgent.BUILT_IN_CQS) + 1
        assert agent.cqs[-1].cq_id == "CQ-EXTRA"

    def test_sparql_agent_no_rdflib_returns_failed(self):
        """When rdflib is unavailable, all CQs are returned as failed."""
        from ontology_mapping_co_scientist.validation import sparql_competency

        original = sparql_competency.HAS_RDFLIB
        try:
            sparql_competency.HAS_RDFLIB = False
            agent = sparql_competency.SPARQLCompetencyAgent()
            results = agent.run_cqs([_make_hypothesis()])
            assert all(not r.passed for r in results)
        finally:
            sparql_competency.HAS_RDFLIB = original


# ===========================================================================
# Extended ValidationAgent tests
# ===========================================================================


class TestExtendedValidationAgent:
    """Tests for the new methods added to ValidationAgent."""

    def test_validation_agent_extended_runs_all(self):
        """validate_all_extended calls all three validators."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()

        # A REQUIRES_TRANSFORM hypothesis with no conditions to trigger all validators
        source = _make_source(datatype="object")  # object -> property should warn
        target = _make_target(term_type="property")
        hyp = _make_hypothesis(
            source=source,
            target=target,
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=[],
        )

        results = agent.validate_all_extended([hyp])
        assert len(results) == 1
        result = results[0]
        # Should have at least one warning from datatype or transform
        assert result.validation_status in (ValidationStatus.WARNING, ValidationStatus.FAILED)
        # Must have some warnings
        assert len(result.warnings) > 0

    def test_validation_agent_datatype_warning_added(self):
        """validate_with_datatype_check adds [datatype] prefix to warnings."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        source = _make_source(datatype="boolean")
        target = _make_target(term_type="class")
        hyp = _make_hypothesis(source=source, target=target)
        # Set status to PASSED first
        hyp.validation_status = ValidationStatus.PASSED

        result = agent.validate_with_datatype_check(hyp)
        assert any("[datatype]" in w for w in result.warnings)
        assert result.validation_status == ValidationStatus.WARNING

    def test_validation_agent_transform_warning_added(self):
        """validate_transform_conditions adds [transform] prefix to warnings."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=["requires transformation"],
        )
        hyp.validation_status = ValidationStatus.PASSED

        result = agent.validate_transform_conditions(hyp)
        assert any("[transform]" in w for w in result.warnings)
        assert result.validation_status == ValidationStatus.WARNING

    def test_validation_agent_transform_skipped_for_non_transform(self):
        """validate_transform_conditions is a no-op for non-REQUIRES_TRANSFORM."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        hyp = _make_hypothesis(
            predicate=MappingPredicate.EXACT_MATCH,
            required_conditions=["requires transformation"],
        )
        hyp.validation_status = ValidationStatus.PASSED
        original_warnings = list(hyp.warnings)

        result = agent.validate_transform_conditions(hyp)
        assert result.validation_status == ValidationStatus.PASSED
        assert result.warnings == original_warnings

    def test_validation_full_report_keys(self):
        """generate_full_report has all expected keys."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        hyps = [_make_hypothesis(mapping_id=f"map-{i:03d}") for i in range(3)]
        agent.validate_all_extended(hyps)
        report = agent.generate_full_report(hyps)

        expected_keys = {
            "total",
            "passed",
            "warnings",
            "failed",
            "no_mapping_count",
            "exact_match_count",
            "high_confidence_count",
            "with_datatype_warnings",
            "with_transform_warnings",
        }
        assert expected_keys.issubset(set(report.keys()))

    def test_validation_full_report_counts_datatype_warnings(self):
        """generate_full_report correctly counts hypotheses with datatype warnings."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()

        # One that will get a datatype warning (object -> property)
        source_bad = _make_source(datatype="object")
        target_prop = _make_target(term_type="property")
        hyp_bad = _make_hypothesis(
            mapping_id="map-bad",
            source=source_bad,
            target=target_prop,
        )
        # One that is clean
        hyp_good = _make_hypothesis(mapping_id="map-good")

        hyps = [hyp_bad, hyp_good]
        agent.validate_all_extended(hyps)
        report = agent.generate_full_report(hyps)

        assert report["with_datatype_warnings"] >= 1

    def test_validation_full_report_counts_transform_warnings(self):
        """generate_full_report correctly counts hypotheses with transform warnings."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        hyp = _make_hypothesis(
            predicate=MappingPredicate.REQUIRES_TRANSFORM,
            required_conditions=["requires transformation"],
        )
        agent.validate_all_extended([hyp])
        report = agent.generate_full_report([hyp])
        assert report["with_transform_warnings"] >= 1

    def test_validate_all_extended_no_double_warnings(self):
        """Warnings are not added twice if validate_all_extended is called twice."""
        from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

        agent = ValidationAgent()
        source = _make_source(datatype="boolean")
        target = _make_target(term_type="class")
        hyp = _make_hypothesis(source=source, target=target)

        # First pass
        agent.validate_all_extended([hyp])
        first_count = len(hyp.warnings)

        # Second pass — warnings should not be duplicated
        agent.validate_all_extended([hyp])
        second_count = len(hyp.warnings)

        assert second_count == first_count
