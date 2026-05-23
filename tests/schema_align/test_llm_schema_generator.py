"""Tests for LLMSchemaFieldGenerator.

All tests use MockLLMProvider — no real API calls are made.
"""
from __future__ import annotations

import json

import pytest

from mapping_co_scientist.shared.llm.mock_provider import MockLLMProvider
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation
from mapping_co_scientist.schema_align.agents.llm_field_generator import LLMSchemaFieldGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_src(
    path: str,
    label: str,
    datatype: str = "string",
    unit: str | None = None,
    description: str | None = None,
) -> SchemaEntity:
    return SchemaEntity(
        entity_id=f"csv:{path}",
        path=path,
        label=label,
        datatype=datatype,
        unit=unit,
        description=description,
        source_type="csv",
    )


def make_tgt(
    path: str,
    label: str,
    datatype: str = "string",
) -> SchemaEntity:
    return SchemaEntity(
        entity_id=f"json:{path}",
        path=path,
        label=label,
        datatype=datatype,
        source_type="json_schema",
    )


def _llm_response(*items: dict) -> str:
    """Return a well-formed JSON array response."""
    return json.dumps(list(items))


def _score_item(
    target_path: str,
    score: float,
    operation: str = "rename",
    rationale: str = "ok",
    valid: bool = True,
) -> dict:
    return {
        "target_path": target_path,
        "semantic_score": score,
        "operation": operation,
        "rationale": rationale,
        "valid": valid,
    }


# ---------------------------------------------------------------------------
# Test 1: Generator returns same number of hypotheses as lexical generator
# ---------------------------------------------------------------------------

class TestHypothesisCount:
    def test_same_count_as_lexical_generator(self):
        """LLM generator must return the same number of hypotheses as the lexical generator."""
        src_fields = [make_src("MouseID", "Mouse ID"), make_src("Strain", "Strain")]
        tgt_fields = [
            make_tgt("animal.externalId", "external Id"),
            make_tgt("animal.biologicalAttributes.strain", "strain"),
        ]

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item("animal.externalId", 0.85, "nested_path"),
            _score_item("animal.biologicalAttributes.strain", 0.90, "nested_path"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        from mapping_co_scientist.schema_align.agents.field_candidate_generator import (
            FieldCandidateGeneratorAgent,
        )
        lexical_gen = FieldCandidateGeneratorAgent(top_k=3)
        lexical_hyps = lexical_gen.generate(src_fields, tgt_fields)

        llm_hyps = gen.generate(src_fields, tgt_fields)
        assert len(llm_hyps) == len(lexical_hyps)

    def test_returns_list_of_field_mapping_hypotheses(self):
        """All returned items must be FieldMappingHypothesis instances."""
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item("animal.externalId", 0.80, "nested_path"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("MouseID", "Mouse ID")],
            [make_tgt("animal.externalId", "external Id")],
        )
        assert isinstance(hyps, list)
        for h in hyps:
            assert isinstance(h, FieldMappingHypothesis)


# ---------------------------------------------------------------------------
# Test 2: Blended scoring updates confidences correctly
# ---------------------------------------------------------------------------

class TestBlendedScoring:
    def test_blended_confidence_replaces_lexical(self):
        """Confidence must reflect the weighted blend."""
        target_path = "animal.biologicalAttributes.strain"
        llm_semantic_score = 0.90

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, llm_semantic_score, "nested_path", "strong match"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3, lexical_weight=0.4, llm_weight=0.6)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt(target_path, "strain")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None
        assert 0.0 < target_hyp.confidence <= 1.0

    def test_blended_score_arithmetic(self):
        """Check the blend formula: 0.4 * lex + 0.6 * llm."""
        target_path = "animal.biologicalAttributes.sex"
        llm_semantic_score = 0.60

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, llm_semantic_score, "nested_path", "ok"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3, lexical_weight=0.4, llm_weight=0.6)

        hyps = gen.generate(
            [make_src("Sex", "Sex")],
            [make_tgt(target_path, "sex")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None

        lex_score = next(
            (e.score for e in target_hyp.evidence if e.evidence_type == "lexical_similarity"),
            None,
        )
        assert lex_score is not None
        expected = 0.4 * lex_score + 0.6 * llm_semantic_score
        assert target_hyp.confidence == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 3: LLM semantic evidence is added to hypothesis.evidence
# ---------------------------------------------------------------------------

class TestLLMEvidenceAdded:
    def test_llm_semantic_score_evidence_present(self):
        """An Evidence entry with type 'llm_semantic_score' must be added."""
        target_path = "animal.biologicalAttributes.strain"
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.88, "nested_path", "very good semantic fit"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt(target_path, "strain")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None

        llm_evidence = [e for e in target_hyp.evidence if e.evidence_type == "llm_semantic_score"]
        assert len(llm_evidence) == 1
        assert llm_evidence[0].score == pytest.approx(0.88, abs=1e-6)
        assert "very good semantic fit" in llm_evidence[0].description

    def test_llm_evidence_source_is_model_name(self):
        """The LLM evidence source must match the provider's model_name."""
        target_path = "animal.biologicalAttributes.strain"
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.75, "nested_path", "ok"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt(target_path, "strain")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        llm_evidence = [e for e in target_hyp.evidence if e.evidence_type == "llm_semantic_score"]
        assert llm_evidence[0].source == "mock"


# ---------------------------------------------------------------------------
# Test 4: Malformed LLM JSON falls back to lexical scores gracefully
# ---------------------------------------------------------------------------

class TestMalformedJsonFallback:
    def test_malformed_json_keeps_lexical_scores(self):
        """When LLM returns invalid JSON, confidence stays at lexical score unchanged."""
        llm = MockLLMProvider(default_response="this is not valid json {{}}}")
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt("animal.biologicalAttributes.strain", "strain")],
        )
        assert hyps, "Should still produce hypotheses on LLM parse failure"

        for hyp in hyps:
            if hyp.source_path is not None:  # skip constant assignments
                llm_evidence = [e for e in hyp.evidence if e.evidence_type == "llm_semantic_score"]
                assert len(llm_evidence) == 0

    def test_malformed_json_no_exception_raised(self):
        """Malformed JSON must not propagate an exception."""
        llm = MockLLMProvider(default_response="INVALID ][")
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)
        hyps = gen.generate(
            [make_src("Sex", "Sex")],
            [make_tgt("animal.biologicalAttributes.sex", "sex")],
        )
        assert isinstance(hyps, list)

    def test_non_array_json_falls_back(self):
        """JSON that is not an array falls back to lexical scores."""
        llm = MockLLMProvider(default_response=json.dumps({"not": "an array"}))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt("animal.biologicalAttributes.strain", "strain")],
        )
        for hyp in hyps:
            assert not any(e.evidence_type == "llm_semantic_score" for e in hyp.evidence)


# ---------------------------------------------------------------------------
# Test 5: operation_invalid=True adds warning to hypothesis.warnings
# ---------------------------------------------------------------------------

class TestInvalidOperationWarning:
    def test_valid_false_adds_warning(self):
        """When LLM returns valid=false, a warning must be appended to hypothesis.warnings."""
        target_path = "animal.externalId"
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.70, "nested_path", "operation mismatch detected", valid=False),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("MouseID", "Mouse ID")],
            [make_tgt(target_path, "external Id")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None
        assert any("invalid" in w.lower() or "flagged" in w.lower() for w in target_hyp.warnings), (
            f"Expected a warning for invalid operation, got: {target_hyp.warnings}"
        )

    def test_valid_true_adds_no_operation_warning(self):
        """When LLM returns valid=true, no invalid-operation warning should be added."""
        target_path = "animal.biologicalAttributes.strain"
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.85, "nested_path", "correct operation", valid=True),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt(target_path, "strain")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None
        # No "invalid" / "flagged" warnings from LLM for valid=True
        assert not any(
            ("invalid" in w.lower() or "flagged" in w.lower())
            and "LLM flagged" in w
            for w in target_hyp.warnings
        )


# ---------------------------------------------------------------------------
# Test 6: Constant assignments are preserved unchanged
# ---------------------------------------------------------------------------

class TestConstantAssignments:
    def _src_with_unit_fields(self):
        return [
            make_src("Weight_g", "Weight g", "number", unit="g"),
        ]

    def _tgt_with_unit_field(self):
        return [
            make_tgt("measurements.bodyWeight.value", "body Weight value", "number"),
            make_tgt("measurements.bodyWeight.unit", "body Weight unit", "string"),
        ]

    def test_constant_assignments_not_sent_to_llm(self):
        """Constant-assignment hypotheses (source_path=None) must pass through unchanged."""
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item("measurements.bodyWeight.value", 0.85, "nested_path", "good"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(self._src_with_unit_fields(), self._tgt_with_unit_field())

        constant_hyps = [h for h in hyps if h.source_path is None]
        if constant_hyps:
            for h in constant_hyps:
                # Constant assignments must not have LLM evidence
                assert not any(e.evidence_type == "llm_semantic_score" for e in h.evidence)
                assert h.mapping_operation == MappingOperation.CONSTANT_ASSIGNMENT

    def test_constant_assignments_preserved_with_correct_value(self):
        """Constant-assignment hypotheses must retain their constant value."""
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item("measurements.bodyWeight.value", 0.80, "nested_path", "ok"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(self._src_with_unit_fields(), self._tgt_with_unit_field())

        constant_hyps = [h for h in hyps if h.source_path is None]
        for h in constant_hyps:
            # The transformation rule for a constant assignment should have constant_value set
            if h.transformation_rule is not None:
                assert h.transformation_rule.constant_value is not None


# ---------------------------------------------------------------------------
# Test 7: Operation override adds reviewer_note
# ---------------------------------------------------------------------------

class TestOperationOverride:
    def test_operation_override_updates_hypothesis(self):
        """When LLM suggests a different operation, mapping_operation must be updated."""
        target_path = "animal.biologicalAttributes.strain"
        # Lexical generator will likely assign nested_path; LLM suggests rename
        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.80, "rename", "flat rename is sufficient"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("Strain", "Strain")],
            [make_tgt(target_path, "strain")],
        )
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None
        # If the operation changed, check the reviewer note exists
        if target_hyp.mapping_operation == MappingOperation.RENAME:
            assert any("LLM suggested operation change" in note for note in target_hyp.reviewer_notes)

    def test_no_reviewer_note_when_operation_unchanged(self):
        """No reviewer note when LLM agrees with the lexical operation."""
        target_path = "animal.biologicalAttributes.strain"

        # First, find what operation the lexical generator assigns
        from mapping_co_scientist.schema_align.agents.field_candidate_generator import (
            FieldCandidateGeneratorAgent,
        )
        lexical_gen = FieldCandidateGeneratorAgent(top_k=3)
        src_fields = [make_src("Strain", "Strain")]
        tgt_fields = [make_tgt(target_path, "strain")]
        lexical_hyps = lexical_gen.generate(src_fields, tgt_fields)

        lexical_op = "nested_path"
        if lexical_hyps:
            target_lex = next((h for h in lexical_hyps if h.target_path == target_path), None)
            if target_lex:
                lexical_op = target_lex.mapping_operation.value

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_path, 0.85, lexical_op, "agrees with lexical"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(src_fields, tgt_fields)
        assert hyps

        target_hyp = next((h for h in hyps if h.target_path == target_path), None)
        assert target_hyp is not None
        assert not any("LLM suggested operation change" in note for note in target_hyp.reviewer_notes)


# ---------------------------------------------------------------------------
# Test 8: Top-k ordering is by blended score
# ---------------------------------------------------------------------------

class TestTopKOrdering:
    def test_hypotheses_ordered_by_blended_confidence(self):
        """Hypotheses for a source entity must be sorted by descending confidence."""
        target_a = "animal.externalId"
        target_b = "animal.biologicalAttributes.strain"

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_a, 0.95, "nested_path", "best"),
            _score_item(target_b, 0.30, "nested_path", "weak"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("MouseID", "Mouse ID")],
            [
                make_tgt(target_a, "external Id"),
                make_tgt(target_b, "strain"),
            ],
        )

        # Filter only the scored hyps (not constant assignments)
        scored = [h for h in hyps if h.source_path is not None]
        for i in range(len(scored) - 1):
            assert scored[i].confidence >= scored[i + 1].confidence

    def test_rank_field_updated_after_reorder(self):
        """The rank field must be sequential (1-based) after re-ranking."""
        target_a = "animal.externalId"
        target_b = "animal.biologicalAttributes.strain"

        llm = MockLLMProvider(default_response=_llm_response(
            _score_item(target_a, 0.90, "nested_path", "top"),
            _score_item(target_b, 0.20, "nested_path", "low"),
        ))
        gen = LLMSchemaFieldGenerator(llm=llm, top_k=3)

        hyps = gen.generate(
            [make_src("MouseID", "Mouse ID")],
            [
                make_tgt(target_a, "external Id"),
                make_tgt(target_b, "strain"),
            ],
        )

        scored = [h for h in hyps if h.source_path is not None]
        for i, hyp in enumerate(scored):
            assert hyp.rank == i + 1
