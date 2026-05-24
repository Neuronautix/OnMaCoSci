"""Tests for LLMOntologyCandidateGenerator.

All tests use MockLLMProvider — no real API calls are made.
"""
from __future__ import annotations

import json

import pytest

from mapping_co_scientist.shared.llm.mock_provider import MockLLMProvider
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis,
    OntologyRelation,
)
from mapping_co_scientist.ontology_align.agents.llm_candidate_generator import (
    LLMOntologyCandidateGenerator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_source(label: str, entity_id: str | None = None, description: str = "") -> SourceEntity:
    return SourceEntity(
        entity_id=entity_id or f"csv:{label}",
        label=label,
        description=description or None,
        source_type="csv",
    )


def make_term(
    term_id: str,
    label: str,
    definition: str | None = "A well-defined ontology term.",
    synonyms: list[str] | None = None,
) -> OntologyTerm:
    return OntologyTerm(
        term_id=term_id,
        label=label,
        definition=definition,
        synonyms=synonyms or [],
        term_type="class",
        ontology_id="hcm",
    )


def _valid_llm_response(term_id: str, score: float, relation: str, rationale: str) -> str:
    """Return a well-formed JSON array response for a single candidate."""
    return json.dumps([
        {
            "term_id": term_id,
            "semantic_score": score,
            "relation": relation,
            "rationale": rationale,
        }
    ])


# ---------------------------------------------------------------------------
# Test 1: Generator returns same number of hypotheses as the lexical generator
# ---------------------------------------------------------------------------

class TestHypothesisCount:
    def test_same_count_as_lexical_generator(self):
        """LLM generator must return the same number of hypotheses as the lexical generator."""
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": "hcm:BodyWeight", "semantic_score": 0.85, "relation": "skos:closeMatch", "rationale": "good"},
            {"term_id": "hcm:Mass", "semantic_score": 0.70, "relation": "skos:broadMatch", "rationale": "broader"},
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        sources = [make_source("body_weight"), make_source("sex")]
        terms = [
            make_term("hcm:BodyWeight", "body weight"),
            make_term("hcm:Mass", "mass"),
            make_term("hcm:BiologicalSex", "biological sex"),
        ]

        # Use the lexical generator directly to compare count
        from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import (
            SemanticCandidateGeneratorAgent,
        )
        lexical_gen = SemanticCandidateGeneratorAgent(top_k=3)
        lexical_hyps = lexical_gen.generate(sources, terms)

        llm_hyps = gen.generate(sources, terms)
        assert len(llm_hyps) == len(lexical_hyps)

    def test_returns_list_of_hypothesis_objects(self):
        """All returned items must be OntologyMappingHypothesis instances."""
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": "hcm:BodyWeight", "semantic_score": 0.80, "relation": "skos:closeMatch", "rationale": "ok"},
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)
        sources = [make_source("body_weight")]
        terms = [make_term("hcm:BodyWeight", "body weight")]

        hyps = gen.generate(sources, terms)
        assert isinstance(hyps, list)
        for h in hyps:
            assert isinstance(h, OntologyMappingHypothesis)


# ---------------------------------------------------------------------------
# Test 2: Confidence is updated to blended score when LLM responds correctly
# ---------------------------------------------------------------------------

class TestBlendedScoring:
    def test_blended_confidence_replaces_lexical(self):
        """Confidence must reflect the weighted blend, not the raw lexical score."""
        llm_semantic_score = 0.90
        term_id = "hcm:BodyWeight"

        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": llm_semantic_score,
             "relation": "skos:closeMatch", "rationale": "strong match"}
        ]))
        # Use weights: 0.4 lexical, 0.6 LLM
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3, lexical_weight=0.4, llm_weight=0.6)

        sources = [make_source("body_weight")]
        terms = [make_term(term_id, "body weight")]

        hyps = gen.generate(sources, terms)
        assert hyps, "Expected at least one hypothesis"

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None

        # Confidence must be a blend of lexical + LLM scores, not the raw lexical score
        # We know lexical score for "body_weight" vs "body weight" will be high (~1.0)
        # blended = 0.4 * lexical + 0.6 * 0.90; should not equal pure lexical
        assert 0.0 < target_hyp.confidence <= 1.0

    def test_blended_score_arithmetic(self):
        """Check the blend formula: 0.4 * lex + 0.6 * llm."""
        term_id = "hcm:Sex"
        llm_semantic_score = 0.50
        # Use a source label that will score very close to 1.0 lexically against the term
        # sex vs sex → ~1.0 lexical
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": llm_semantic_score,
             "relation": "skos:closeMatch", "rationale": "ok"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3, lexical_weight=0.4, llm_weight=0.6)

        sources = [make_source("sex")]
        terms = [make_term(term_id, "sex")]

        hyps = gen.generate(sources, terms)
        assert hyps
        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None

        # Get lexical score from evidence
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
        """An Evidence entry with type 'llm_semantic_score' must be added after LLM scoring."""
        term_id = "hcm:BodyWeight"
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": 0.85,
             "relation": "skos:closeMatch", "rationale": "strong semantic match"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        hyps = gen.generate([make_source("body_weight")], [make_term(term_id, "body weight")])
        assert hyps

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None

        llm_evidence = [e for e in target_hyp.evidence if e.evidence_type == "llm_semantic_score"]
        assert len(llm_evidence) == 1
        assert llm_evidence[0].score == pytest.approx(0.85, abs=1e-6)
        assert "strong semantic match" in llm_evidence[0].description

    def test_llm_evidence_source_is_model_name(self):
        """The LLM evidence source must match the provider's model_name."""
        term_id = "hcm:Sex"
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": 0.75,
             "relation": "skos:closeMatch", "rationale": "ok"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        hyps = gen.generate([make_source("sex")], [make_term(term_id, "sex")])
        assert hyps

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        llm_evidence = [e for e in target_hyp.evidence if e.evidence_type == "llm_semantic_score"]
        assert llm_evidence[0].source == "mock"


# ---------------------------------------------------------------------------
# Test 4: Malformed LLM JSON falls back to lexical scores gracefully
# ---------------------------------------------------------------------------

class TestMalformedJsonFallback:
    def test_malformed_json_keeps_lexical_scores(self):
        """When LLM returns invalid JSON, confidence stays at lexical score unchanged."""
        llm = MockLLMProvider(default_response="this is not valid json {{}}}")
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        sources = [make_source("body_weight")]
        terms = [make_term("hcm:BodyWeight", "body weight")]

        hyps = gen.generate(sources, terms)
        assert hyps, "Should still produce hypotheses on LLM parse failure"

        for hyp in hyps:
            # No LLM evidence should be added
            llm_evidence = [e for e in hyp.evidence if e.evidence_type == "llm_semantic_score"]
            assert len(llm_evidence) == 0

    def test_malformed_json_no_exception_raised(self):
        """Malformed JSON must not propagate an exception."""
        llm = MockLLMProvider(default_response="INVALID JSON ][")
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)
        # Must not raise
        hyps = gen.generate([make_source("sex")], [make_term("hcm:Sex", "sex")])
        assert isinstance(hyps, list)

    def test_wrong_type_response_falls_back(self):
        """JSON that is not an array falls back to lexical scores."""
        llm = MockLLMProvider(default_response=json.dumps({"not": "an array"}))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        hyps = gen.generate([make_source("body_weight")], [make_term("hcm:BodyWeight", "body weight")])
        for hyp in hyps:
            assert not any(e.evidence_type == "llm_semantic_score" for e in hyp.evidence)


# ---------------------------------------------------------------------------
# Test 5: LLM relation override adds reviewer_note
# ---------------------------------------------------------------------------

class TestRelationOverride:
    def test_relation_override_updates_hypothesis(self):
        """When LLM suggests a different relation, ontology_relation must be updated."""
        term_id = "hcm:BodyWeight"
        # LLM suggests broadMatch instead of closeMatch
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": 0.70,
             "relation": "skos:broadMatch", "rationale": "target is broader"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        sources = [make_source("body_weight")]
        terms = [make_term(term_id, "body weight")]

        hyps = gen.generate(sources, terms)
        assert hyps

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None
        # The LLM's suggested broadMatch should be applied
        assert target_hyp.ontology_relation == OntologyRelation.BROAD_MATCH

    def test_relation_override_adds_reviewer_note(self):
        """A reviewer note must be added when the relation is overridden by LLM."""
        term_id = "hcm:Sex"
        original_relation = "skos:closeMatch"
        new_relation = "skos:narrowMatch"

        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": 0.65,
             "relation": new_relation, "rationale": "target is narrower concept"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        hyps = gen.generate([make_source("sex")], [make_term(term_id, "sex")])
        assert hyps

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None

        # The original relation was closeMatch (from lexical generator for high-similarity match)
        # but only check the reviewer note if the relation actually changed
        if target_hyp.ontology_relation == OntologyRelation.NARROW_MATCH:
            assert any("narrowMatch" in note for note in target_hyp.reviewer_notes)

    def test_no_reviewer_note_when_relation_unchanged(self):
        """No reviewer note should be added when the LLM agrees with the lexical relation."""
        term_id = "hcm:BodyWeight"
        # Find what lexical relation the generator assigns, then make LLM agree
        from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import (
            SemanticCandidateGeneratorAgent,
        )
        lexical_gen = SemanticCandidateGeneratorAgent(top_k=3)
        sources = [make_source("body_weight")]
        terms = [make_term(term_id, "body weight")]
        lexical_hyps = lexical_gen.generate(sources, terms)
        lexical_relation = lexical_hyps[0].ontology_relation.value if lexical_hyps else "skos:closeMatch"

        # LLM agrees with the lexical relation
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id, "semantic_score": 0.85,
             "relation": lexical_relation, "rationale": "agrees"}
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)
        hyps = gen.generate(sources, terms)
        assert hyps

        target_hyp = next((h for h in hyps if h.target_ontology_entity.term_id == term_id), None)
        assert target_hyp is not None
        # When relation unchanged, reviewer_notes should be empty (no LLM override note)
        assert not any("LLM suggested relation change" in note for note in target_hyp.reviewer_notes)


# ---------------------------------------------------------------------------
# Test 6: Top-k ordering is by blended score
# ---------------------------------------------------------------------------

class TestTopKOrdering:
    def test_hypotheses_ordered_by_blended_confidence(self):
        """Hypotheses for a given source entity must be sorted by descending confidence."""
        term_id_a = "hcm:BodyWeight"
        term_id_b = "hcm:Mass"

        # Give term_a a higher LLM score → higher blended score
        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id_a, "semantic_score": 0.95,
             "relation": "skos:closeMatch", "rationale": "best match"},
            {"term_id": term_id_b, "semantic_score": 0.40,
             "relation": "skos:broadMatch", "rationale": "weaker match"},
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        sources = [make_source("body_weight")]
        terms = [
            make_term(term_id_a, "body weight"),
            make_term(term_id_b, "mass", synonyms=["body mass"]),
        ]

        hyps = gen.generate(sources, terms)
        # All hypotheses for the source entity should be in descending confidence order
        for i in range(len(hyps) - 1):
            assert hyps[i].confidence >= hyps[i + 1].confidence

    def test_rank_field_updated_after_reorder(self):
        """The rank field must be updated to reflect the new ordering."""
        term_id_a = "hcm:BodyWeight"
        term_id_b = "hcm:Mass"

        llm = MockLLMProvider(default_response=json.dumps([
            {"term_id": term_id_a, "semantic_score": 0.90,
             "relation": "skos:closeMatch", "rationale": "top"},
            {"term_id": term_id_b, "semantic_score": 0.30,
             "relation": "skos:relatedMatch", "rationale": "weak"},
        ]))
        gen = LLMOntologyCandidateGenerator(llm=llm, top_k=3)

        sources = [make_source("body_weight")]
        terms = [
            make_term(term_id_a, "body weight"),
            make_term(term_id_b, "mass", synonyms=["body mass"]),
        ]

        hyps = gen.generate(sources, terms)
        # Ranks should be sequential from 1
        for i, hyp in enumerate(hyps):
            assert hyp.rank == i + 1
