"""Tests for ontology alignment: candidate generation, semantic warnings, adversarial review."""
from __future__ import annotations

import pytest
from pathlib import Path

from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.shared.models.evidence import Provenance
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis,
    OntologyRelation,
    SemanticWarning,
)
from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import (
    SemanticCandidateGeneratorAgent,
)
from mapping_co_scientist.ontology_align.agents.ontology_adversarial_reviewer import (
    OntologyAdversarialReviewerAgent,
)
from mapping_co_scientist.ontology_align.agents.term_gap_agent import TermGapAgent
from mapping_co_scientist.ontology_align.agents.ontology_validation_agent import (
    OntologyValidationAgent,
)
from mapping_co_scientist.shared.models.review import ValidationStatus


# --- Fixtures ---

NOW = "2024-01-01T00:00:00"


def make_prov(**kwargs):
    defaults = dict(created_by="test", created_at=NOW, method="test_v1")
    defaults.update(kwargs)
    return Provenance(**defaults)


def make_source(label: str, entity_type: str = "field") -> SourceEntity:
    return SourceEntity(
        entity_id=f"csv:{label}",
        label=label,
        source_type="csv",
    )


def make_term(term_id: str, label: str, definition: str | None = None) -> OntologyTerm:
    return OntologyTerm(
        term_id=term_id,
        label=label,
        definition=definition,
        term_type="class",
        ontology_id="hcm",
    )


# --- Tests: Candidate Generation ---

class TestSemanticCandidateGenerator:
    def test_generates_candidates(self):
        source = [make_source("strain"), make_source("sex")]
        targets = [
            make_term("hcm:MouseStrain", "MouseStrain", "A standardised mouse line."),
            make_term("hcm:BiologicalSex", "BiologicalSex", "Biological sex of the animal."),
        ]
        gen = SemanticCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(source, targets)
        assert len(hyps) >= 2

    def test_strain_genetic_background_scope_warning(self):
        """Critical: strain -> GeneticBackground must produce a scope warning and use narrowMatch."""
        source = [SourceEntity(
            entity_id="csv:strain",
            label="strain",
            source_type="csv",
        )]
        targets = [
            make_term("hcm:GeneticBackground", "GeneticBackground",
                      "The genetic constitution including strain, breeding history, and modifications."),
        ]
        gen = SemanticCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(source, targets)
        assert hyps, "Expected at least one hypothesis for strain -> GeneticBackground"
        # Must use narrowMatch or closeMatch (not exactMatch) due to scope difference
        for h in hyps:
            if "GeneticBackground" in h.target_ontology_entity.term_id:
                assert h.ontology_relation != OntologyRelation.EXACT_MATCH, (
                    "strain should not auto-map to GeneticBackground with exactMatch"
                )
                # Should have a scope warning
                warning_types = [w.warning_type for w in h.semantic_warnings]
                assert any("scope" in wt or "lexical" in wt for wt in warning_types), (
                    f"Expected scope warning, got: {warning_types}"
                )

    def test_no_exactmatch_from_lexical_only(self):
        """Lexical similarity alone must never produce exactMatch."""
        source = [make_source("sex")]
        targets = [make_term("hcm:BiologicalSex", "sex")]  # near-identical label
        gen = SemanticCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(source, targets)
        for h in hyps:
            assert h.ontology_relation != OntologyRelation.EXACT_MATCH, (
                "Lexical-only generator must not assign exactMatch"
            )

    def test_low_score_not_included(self):
        source = [make_source("unrelated_field_xyz")]
        targets = [make_term("hcm:Animal", "Animal", "A vertebrate animal.")]
        gen = SemanticCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(source, targets)
        # May or may not produce hypotheses, but none should have very high confidence
        for h in hyps:
            assert h.confidence < 0.90

    def test_provenance_recorded(self):
        source = [make_source("body_weight")]
        targets = [make_term("hcm:BodyWeightMeasurement", "BodyWeightMeasurement")]
        gen = SemanticCandidateGeneratorAgent(top_k=3, pipeline_run_id="test-run-001")
        hyps = gen.generate(source, targets)
        assert hyps
        assert hyps[0].provenance.pipeline_run_id == "test-run-001"
        assert hyps[0].provenance.created_by == "SemanticCandidateGenerator"


# --- Tests: Adversarial Review ---

class TestOntologyAdversarialReviewer:
    def _make_hyp(
        self,
        relation: OntologyRelation,
        confidence: float = 0.80,
        source_type: str = "field",
        target_type: str = "class",
        definition: str | None = "A well-defined term.",
        warnings: list[SemanticWarning] | None = None,
    ) -> OntologyMappingHypothesis:
        return OntologyMappingHypothesis(
            mapping_id="test-map-001",
            source_concept=make_source("test_field"),
            target_ontology_entity=make_term("hcm:Test", "Test", definition),
            ontology_relation=relation,
            confidence=confidence,
            source_entity_type=source_type,
            target_entity_type=target_type,
            semantic_scope_analysis="test",
            hierarchy_compatibility="unknown",
            domain_range_compatibility="unknown",
            semantic_warnings=warnings or [],
            provenance=make_prov(),
        )

    def test_exactmatch_flagged_as_high(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(OntologyRelation.EXACT_MATCH)
        result = reviewer.review(hyp)
        assert result.overall_severity == "high"
        assert result.recommendation == "reject"
        flag_types = [f.flag_type for f in result.flags]
        assert "exactmatch_requires_validation" in flag_types

    def test_closematch_proceeds(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(OntologyRelation.CLOSE_MATCH, confidence=0.82)
        result = reviewer.review(hyp)
        # closeMatch with good confidence and definition should proceed or review
        assert result.overall_severity in ("clean", "low")

    def test_owl_equivalentclass_flagged(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(OntologyRelation.EQUIVALENT_CLASS, confidence=0.95)
        result = reviewer.review(hyp)
        assert result.overall_severity == "high"
        flag_types = [f.flag_type for f in result.flags]
        assert "owl_equivalence_overreach" in flag_types

    def test_missing_definition_flagged(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(OntologyRelation.CLOSE_MATCH, definition=None)
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "missing_ontology_definition" in flag_types

    def test_low_confidence_flagged(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(OntologyRelation.BROAD_MATCH, confidence=0.30)
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "low_confidence" in flag_types

    def test_measurement_to_class_flagged(self):
        reviewer = OntologyAdversarialReviewerAgent()
        hyp = self._make_hyp(
            OntologyRelation.CLOSE_MATCH,
            source_type="measurement",
            target_type="class",
            confidence=0.70,
        )
        result = reviewer.review(hyp)
        flag_types = [f.flag_type for f in result.flags]
        assert "measurement_to_class_mismatch" in flag_types


# --- Tests: Term Gap Agent ---

class TestTermGapAgent:
    def test_identifies_unmapped(self):
        source_entities = [
            make_source("locomotor_activity_index"),
            make_source("sex"),
        ]
        # Only sex has a hypothesis
        sex_hyp = OntologyMappingHypothesis(
            mapping_id="map-sex",
            source_concept=make_source("sex"),
            target_ontology_entity=make_term("hcm:BiologicalSex", "BiologicalSex"),
            ontology_relation=OntologyRelation.CLOSE_MATCH,
            confidence=0.85,
            source_entity_type="attribute",
            target_entity_type="class",
            semantic_scope_analysis="good match",
            hierarchy_compatibility="compatible",
            domain_range_compatibility="compatible",
            provenance=make_prov(),
        )
        agent = TermGapAgent()
        gaps = agent.identify_gaps(source_entities, [sex_hyp])
        assert len(gaps) == 1
        assert gaps[0].source_concept_label == "locomotor_activity_index"

    def test_no_gaps_when_all_mapped(self):
        source_entities = [make_source("sex")]
        hyp = OntologyMappingHypothesis(
            mapping_id="map-sex",
            source_concept=make_source("sex"),
            target_ontology_entity=make_term("hcm:BiologicalSex", "BiologicalSex"),
            ontology_relation=OntologyRelation.CLOSE_MATCH,
            confidence=0.85,
            source_entity_type="attribute",
            target_entity_type="class",
            semantic_scope_analysis="good",
            hierarchy_compatibility="compatible",
            domain_range_compatibility="compatible",
            provenance=make_prov(),
        )
        agent = TermGapAgent()
        gaps = agent.identify_gaps(source_entities, [hyp])
        assert len(gaps) == 0


# --- Tests: Validation ---

class TestOntologyValidationAgent:
    def _make_hyp(self, relation: OntologyRelation, confidence: float = 0.80) -> OntologyMappingHypothesis:
        return OntologyMappingHypothesis(
            mapping_id="val-map-001",
            source_concept=make_source("test"),
            target_ontology_entity=make_term("hcm:Test", "Test"),
            ontology_relation=relation,
            confidence=confidence,
            source_entity_type="field",
            target_entity_type="class",
            semantic_scope_analysis="test",
            hierarchy_compatibility="unknown",
            domain_range_compatibility="unknown",
            provenance=make_prov(),
        )

    def test_closematch_high_confidence_passes(self):
        agent = OntologyValidationAgent()
        hyp = self._make_hyp(OntologyRelation.CLOSE_MATCH, confidence=0.80)
        result = agent.validate_all([hyp])
        assert result[0].validation_status == ValidationStatus.PASSED

    def test_exactmatch_without_justification_warns(self):
        agent = OntologyValidationAgent()
        hyp = self._make_hyp(OntologyRelation.EXACT_MATCH, confidence=0.92)
        result = agent.validate_all([hyp])
        assert result[0].validation_status == ValidationStatus.WARNING
        assert any("exactMatch" in w for w in result[0].warnings)

    def test_equivalentclass_always_warns(self):
        agent = OntologyValidationAgent()
        hyp = self._make_hyp(OntologyRelation.EQUIVALENT_CLASS, confidence=0.95)
        result = agent.validate_all([hyp])
        assert result[0].validation_status == ValidationStatus.WARNING
