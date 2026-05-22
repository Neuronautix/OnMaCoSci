"""Tests for the LLM-backed agents: candidate generator, ontology engineer reviewer,
domain scientist reviewer, cost tracker, and prompt templates.

All tests that would trigger real LLM API calls use mock clients so that the
test suite can run without an ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow running with PYTHONPATH=src or from within the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.agents.llm_candidate_generator import (
    LLMCandidateGeneratorAgent,
)
from ontology_mapping_co_scientist.agents.llm_cost_tracker import LLMCostTracker
from ontology_mapping_co_scientist.agents.llm_domain_scientist_reviewer import (
    LLMDomainScientistReviewerAgent,
)
from ontology_mapping_co_scientist.agents.llm_ontology_engineer_reviewer import (
    LLMOntologyEngineerReviewerAgent,
)
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
)
from ontology_mapping_co_scientist.models.review import AdversarialReviewResult
from ontology_mapping_co_scientist.prompts.templates import get_prompt_hash


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockMessage:
    """Minimal mock of an Anthropic API Message response."""

    class MockContent:
        text = '{"scores": [{"term_id": "t1", "score": 0.85, "rationale": "good match"}]}'

    content = [MockContent()]

    class MockUsage:
        input_tokens = 100
        output_tokens = 50

    usage = MockUsage()


class MockClient:
    """Minimal mock of an Anthropic API client."""

    class messages:  # noqa: N801
        @staticmethod
        def create(**kwargs):
            return MockMessage()


def _make_source_entity(entity_id: str = "csv:body_weight") -> SourceEntity:
    return SourceEntity(
        entity_id=entity_id,
        label="body weight",
        description="Weight of the animal in kilograms",
        datatype="number",
        examples=["10.5", "12.3"],
        source_file="test.csv",
        source_type="csv",
    )


def _make_ontology_term(
    term_id: str = "PATO:0000125",
    label: str = "mass",
) -> OntologyTerm:
    return OntologyTerm(
        term_id=term_id,
        label=label,
        definition="A physical quality relating to mass.",
        synonyms=["weight", "body mass"],
        term_type="class",
        ontology_id="PATO",
    )


def _make_hypothesis(
    mapping_id: str = "test-map-001",
    predicate: MappingPredicate = MappingPredicate.CLOSE_MATCH,
    confidence: float = 0.75,
) -> MappingHypothesis:
    source = _make_source_entity()
    target = _make_ontology_term()
    provenance = Provenance(
        created_by="TestAgent",
        created_at="2026-01-01T00:00:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="test-run-001",
    )
    evidence = [
        Evidence(
            evidence_type="lexical_similarity",
            description="Label similarity score 0.75",
            score=0.75,
            source="TestAgent",
        )
    ]
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source,
        target_entity=target,
        predicate=predicate,
        confidence=confidence,
        evidence=evidence,
        provenance=provenance,
    )


def _make_mock_client_with_response(response_text: str):
    """Return a mock client whose messages.create returns response_text."""

    class DynamicMockContent:
        text = response_text

    class DynamicMockUsage:
        input_tokens = 100
        output_tokens = 50

    class DynamicMockMessage:
        content = [DynamicMockContent()]
        usage = DynamicMockUsage()

    class DynamicMockClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                return DynamicMockMessage()

    return DynamicMockClient()


class _OverloadedMessages:
    @staticmethod
    def create(**kwargs):
        exc = RuntimeError("provider overloaded")
        exc.status_code = 529
        raise exc


class _OverloadedClient:
    messages = _OverloadedMessages()


# ---------------------------------------------------------------------------
# L2: LLMCandidateGeneratorAgent tests
# ---------------------------------------------------------------------------


def test_llm_candidate_generator_fallback():
    """No client provided → falls back to lexical generation and returns hypotheses."""
    agent = LLMCandidateGeneratorAgent()
    assert agent.llm_client is None

    source_entities = [_make_source_entity()]
    ontology_terms = [_make_ontology_term(term_id="PATO:0000125", label="mass")]

    hypotheses = agent.generate_candidates(source_entities, ontology_terms)
    assert isinstance(hypotheses, list)
    assert len(hypotheses) >= 1
    for h in hypotheses:
        assert isinstance(h, MappingHypothesis)


def test_llm_candidate_generator_from_env_no_key(monkeypatch):
    """from_env() without ANTHROPIC_API_KEY returns a lexical-only agent."""
    monkeypatch.setenv("OMCS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = LLMCandidateGeneratorAgent.from_env()
    assert agent.llm_client is None


def test_llm_candidate_generator_with_mock_client():
    """Mock client returns valid JSON scores; check Evidence is added to top candidate."""
    # The mock returns a score for term_id "PATO:0000125"
    score_response = json.dumps(
        {
            "scores": [
                {
                    "term_id": "PATO:0000125",
                    "score": 0.90,
                    "rationale": "body weight is semantically equivalent to mass",
                }
            ]
        }
    )
    mock_client = _make_mock_client_with_response(score_response)
    agent = LLMCandidateGeneratorAgent(
        llm_client=mock_client,
        top_k_for_llm=3,
    )

    source_entities = [_make_source_entity()]
    ontology_terms = [_make_ontology_term(term_id="PATO:0000125", label="mass")]

    hypotheses = agent.generate_candidates(source_entities, ontology_terms)

    # Find hypotheses with LLM evidence
    llm_evidenced = [
        h
        for h in hypotheses
        if any(e.evidence_type == "llm_semantic_similarity" for e in h.evidence)
    ]
    assert len(llm_evidenced) >= 1
    llm_ev = next(
        e for e in llm_evidenced[0].evidence if e.evidence_type == "llm_semantic_similarity"
    )
    assert llm_ev.score == pytest.approx(0.90, abs=1e-6)
    assert "body weight is semantically equivalent to mass" in llm_ev.description


def test_llm_candidate_generator_stops_after_provider_overload():
    """Provider overload disables remaining LLM candidate calls."""
    agent = LLMCandidateGeneratorAgent(llm_client=_OverloadedClient())

    hypotheses = agent.generate_candidates(
        [_make_source_entity()],
        [_make_ontology_term(term_id="PATO:0000125", label="mass")],
    )

    assert hypotheses
    assert agent.llm_disabled_reason is not None
    assert "provider overloaded" in agent.llm_disabled_reason


def test_llm_candidate_generator_parse_scores_valid():
    """_parse_scoring_response correctly parses a valid JSON response."""
    agent = LLMCandidateGeneratorAgent()

    source = _make_source_entity()
    target = _make_ontology_term(term_id="PATO:0000125")
    hyp = _make_hypothesis()

    response_text = json.dumps(
        {
            "scores": [
                {
                    "term_id": "PATO:0000125",
                    "score": 0.82,
                    "rationale": "semantically similar concepts",
                }
            ]
        }
    )
    result = agent._parse_scoring_response(response_text, [hyp])

    assert "PATO:0000125" in result
    score, rationale = result["PATO:0000125"]
    assert score == pytest.approx(0.82, abs=1e-6)
    assert "semantically similar" in rationale


def test_llm_candidate_generator_parse_scores_invalid():
    """Malformed JSON returns an empty dict without raising."""
    agent = LLMCandidateGeneratorAgent()
    hyp = _make_hypothesis()

    result = agent._parse_scoring_response("this is not json }}{{", [hyp])
    assert result == {}


def test_llm_candidate_generator_parse_scores_score_clamped():
    """Scores outside [0, 1] are clamped to the valid range."""
    agent = LLMCandidateGeneratorAgent()
    hyp = _make_hypothesis()

    # Score > 1.0 should be clamped to 1.0
    response_text = json.dumps(
        {
            "scores": [
                {"term_id": "PATO:0000125", "score": 1.5, "rationale": "over score"}
            ]
        }
    )
    result = agent._parse_scoring_response(response_text, [hyp])
    assert result["PATO:0000125"][0] == pytest.approx(1.0, abs=1e-6)

    # Score < 0.0 should be clamped to 0.0
    response_text2 = json.dumps(
        {
            "scores": [
                {"term_id": "PATO:0000125", "score": -0.5, "rationale": "under score"}
            ]
        }
    )
    result2 = agent._parse_scoring_response(response_text2, [hyp])
    assert result2["PATO:0000125"][0] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# L3: LLMOntologyEngineerReviewerAgent tests
# ---------------------------------------------------------------------------


def test_ontology_engineer_reviewer_no_client():
    """No client → returns clean AdversarialReviewResult with 'proceed'."""
    reviewer = LLMOntologyEngineerReviewerAgent()
    hyp = _make_hypothesis()

    result = reviewer.review_hypothesis(hyp)

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == hyp.mapping_id
    assert result.flags == []
    assert result.overall_severity == "clean"
    assert result.recommendation == "proceed"


def test_ontology_engineer_reviewer_from_env_no_key(monkeypatch):
    """from_env() without ANTHROPIC_API_KEY returns a no-op agent."""
    monkeypatch.setenv("OMCS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reviewer = LLMOntologyEngineerReviewerAgent.from_env()
    assert reviewer.llm_client is None


def test_ontology_engineer_reviewer_with_mock():
    """Mock client → flags are parsed correctly from LLM response."""
    flag_response = json.dumps(
        {
            "flags": [
                {
                    "flag_type": "predicate_mismatch",
                    "description": "exactMatch is too strong; should be closeMatch.",
                    "severity": "medium",
                }
            ],
            "recommendation": "review",
        }
    )
    mock_client = _make_mock_client_with_response(flag_response)
    reviewer = LLMOntologyEngineerReviewerAgent(llm_client=mock_client)
    hyp = _make_hypothesis()

    result = reviewer.review_hypothesis(hyp)

    assert isinstance(result, AdversarialReviewResult)
    assert len(result.flags) == 1
    assert result.flags[0].flag_type == "predicate_mismatch"
    assert result.flags[0].severity == "medium"
    assert result.overall_severity == "medium"
    assert result.recommendation == "review"
    assert reviewer.llm_attempted_reviews == 1
    assert reviewer.llm_successful_reviews == 1
    assert reviewer.fallback_reviews == 0


def test_ontology_engineer_reviewer_review_all():
    """review_all returns one result per hypothesis."""
    reviewer = LLMOntologyEngineerReviewerAgent()
    hypotheses = [_make_hypothesis(mapping_id=f"map-{i}") for i in range(4)]
    results = reviewer.review_all(hypotheses)
    assert len(results) == 4
    for r in results:
        assert isinstance(r, AdversarialReviewResult)


def test_ontology_engineer_reviewer_build_prompt_contains_key_fields():
    """_build_prompt includes source/target labels, predicate, and JSON instructions."""
    reviewer = LLMOntologyEngineerReviewerAgent()
    hyp = _make_hypothesis(predicate=MappingPredicate.EXACT_MATCH)
    prompt = reviewer._build_prompt(hyp)

    assert "body weight" in prompt
    assert "mass" in prompt
    assert MappingPredicate.EXACT_MATCH.value in prompt
    assert "JSON" in prompt
    assert "flag_type" in prompt
    assert "severity" in prompt


# ---------------------------------------------------------------------------
# L4: LLMDomainScientistReviewerAgent tests
# ---------------------------------------------------------------------------


def test_domain_scientist_reviewer_no_client():
    """No client → returns clean AdversarialReviewResult with 'proceed'."""
    reviewer = LLMDomainScientistReviewerAgent()
    hyp = _make_hypothesis()

    result = reviewer.review_hypothesis(hyp)

    assert isinstance(result, AdversarialReviewResult)
    assert result.flags == []
    assert result.overall_severity == "clean"
    assert result.recommendation == "proceed"


def test_domain_scientist_reviewer_from_env_no_key(monkeypatch):
    """from_env() without ANTHROPIC_API_KEY returns a no-op agent."""
    monkeypatch.setenv("OMCS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reviewer = LLMDomainScientistReviewerAgent.from_env()
    assert reviewer.llm_client is None


def test_domain_scientist_reviewer_with_mock():
    """Mock client → flags are parsed correctly from LLM response."""
    flag_response = json.dumps(
        {
            "flags": [
                {
                    "flag_type": "domain_ambiguity",
                    "description": "Weight field may refer to dose weight, not body weight.",
                    "severity": "high",
                }
            ],
            "recommendation": "reject",
        }
    )
    mock_client = _make_mock_client_with_response(flag_response)
    reviewer = LLMDomainScientistReviewerAgent(
        llm_client=mock_client,
        domain_context="preclinical pharmacokinetics in rodents",
    )
    hyp = _make_hypothesis()

    result = reviewer.review_hypothesis(hyp)

    assert isinstance(result, AdversarialReviewResult)
    assert len(result.flags) == 1
    assert result.flags[0].flag_type == "domain_ambiguity"
    assert result.flags[0].severity == "high"
    assert result.overall_severity == "high"
    assert result.recommendation == "reject"
    assert reviewer.llm_attempted_reviews == 1
    assert reviewer.llm_successful_reviews == 1
    assert reviewer.fallback_reviews == 0


def test_domain_scientist_reviewer_domain_context_in_prompt():
    """domain_context string appears in the prompt built by _build_prompt."""
    reviewer = LLMDomainScientistReviewerAgent(
        domain_context="preclinical pharmacokinetics in rodents"
    )
    hyp = _make_hypothesis()
    prompt = reviewer._build_prompt(hyp)

    assert "preclinical pharmacokinetics in rodents" in prompt


def test_domain_scientist_reviewer_default_domain_context():
    """Default domain_context 'biomedical research' appears in the prompt."""
    reviewer = LLMDomainScientistReviewerAgent()
    hyp = _make_hypothesis()
    prompt = reviewer._build_prompt(hyp)

    assert "biomedical research" in prompt


def test_domain_scientist_reviewer_review_all():
    """review_all returns one result per hypothesis."""
    reviewer = LLMDomainScientistReviewerAgent()
    hypotheses = [_make_hypothesis(mapping_id=f"ds-map-{i}") for i in range(3)]
    results = reviewer.review_all(hypotheses)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# L5: LLMCostTracker tests
# ---------------------------------------------------------------------------


def test_cost_tracker_record_and_summary():
    """Record 2 calls, check totals are correct."""
    tracker = LLMCostTracker()

    tracker.record(
        agent_name="LLMCandidateGeneratorAgent",
        model="claude-haiku-4-5-20251001",
        input_tokens=200,
        output_tokens=80,
    )
    tracker.record(
        agent_name="LLMOntologyEngineerReviewerAgent",
        model="claude-haiku-4-5-20251001",
        input_tokens=150,
        output_tokens=60,
    )

    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert summary["total_input_tokens"] == 350
    assert summary["total_output_tokens"] == 140

    tokens = tracker.total_tokens()
    assert tokens["input"] == 350
    assert tokens["output"] == 140
    assert tokens["total"] == 490

    assert "by_agent" in summary
    assert "LLMCandidateGeneratorAgent" in summary["by_agent"]
    assert summary["by_agent"]["LLMCandidateGeneratorAgent"]["calls"] == 1


def test_cost_tracker_estimated_cost():
    """Check cost calculation for known token counts using haiku pricing."""
    tracker = LLMCostTracker()

    # 1M input tokens at $0.80/M = $0.80
    # 1M output tokens at $4.00/M = $4.00
    tracker.record(
        agent_name="TestAgent",
        model="claude-haiku-4-5-20251001",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    cost = tracker.estimated_cost_usd()
    assert cost == pytest.approx(4.80, abs=1e-6)


def test_cost_tracker_estimated_cost_small():
    """Verify cost calculation for small token counts."""
    tracker = LLMCostTracker()

    # 100 input tokens at $0.80/M = $0.00008
    # 50 output tokens at $4.00/M = $0.0002
    tracker.record(
        agent_name="TestAgent",
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
    )

    expected = (100 / 1_000_000) * 0.80 + (50 / 1_000_000) * 4.00
    cost = tracker.estimated_cost_usd()
    assert cost == pytest.approx(expected, abs=1e-10)


def test_cost_tracker_unknown_model():
    """Unknown model returns 0.0 cost without crashing."""
    tracker = LLMCostTracker()

    tracker.record(
        agent_name="TestAgent",
        model="claude-unknown-model-xyz",
        input_tokens=1000,
        output_tokens=500,
    )

    cost = tracker.estimated_cost_usd()
    assert cost == pytest.approx(0.0, abs=1e-10)
    # Summary should still work
    summary = tracker.summary()
    assert summary["total_calls"] == 1


def test_cost_tracker_empty():
    """Empty tracker returns zero totals."""
    tracker = LLMCostTracker()
    assert tracker.total_tokens() == {"input": 0, "output": 0, "total": 0}
    assert tracker.estimated_cost_usd() == pytest.approx(0.0)
    summary = tracker.summary()
    assert summary["total_calls"] == 0
    assert summary["by_agent"] == {}


def test_cost_tracker_multiple_models():
    """Cost is computed correctly across multiple different models."""
    tracker = LLMCostTracker()

    tracker.record("AgentA", "claude-haiku-4-5-20251001", 1_000_000, 0)
    tracker.record("AgentB", "claude-sonnet-4-6", 1_000_000, 0)

    expected = 0.80 + 3.00  # haiku input + sonnet input (both 1M tokens, 0 output)
    assert tracker.estimated_cost_usd() == pytest.approx(expected, abs=1e-6)


def test_cost_tracker_print_summary(capsys):
    """print_summary produces non-empty output."""
    tracker = LLMCostTracker()
    tracker.record("TestAgent", "claude-haiku-4-5-20251001", 100, 50)
    tracker.print_summary()

    captured = capsys.readouterr()
    assert "LLM Cost Tracker Summary" in captured.out
    assert "TestAgent" in captured.out


# ---------------------------------------------------------------------------
# Prompt templates tests
# ---------------------------------------------------------------------------


def test_prompt_hash_is_deterministic():
    """Same prompt always produces the same hash."""
    prompt = "This is a test prompt for hashing."
    hash1 = get_prompt_hash(prompt)
    hash2 = get_prompt_hash(prompt)
    assert hash1 == hash2


def test_prompt_hash_different_prompts():
    """Different prompts produce different hashes."""
    h1 = get_prompt_hash("prompt one")
    h2 = get_prompt_hash("prompt two")
    assert h1 != h2


def test_prompt_hash_length():
    """get_prompt_hash always returns exactly 12 characters."""
    for prompt in ["", "a", "hello world", "x" * 10000]:
        h = get_prompt_hash(prompt)
        assert len(h) == 12
        assert h.isalnum() or all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Cost tracker integration with LLM agents
# ---------------------------------------------------------------------------


def test_cost_tracker_wired_into_candidate_generator():
    """LLM calls through LLMCandidateGeneratorAgent are recorded in the tracker."""
    tracker = LLMCostTracker()

    score_response = json.dumps(
        {"scores": [{"term_id": "PATO:0000125", "score": 0.80, "rationale": "good"}]}
    )
    mock_client = _make_mock_client_with_response(score_response)
    agent = LLMCandidateGeneratorAgent(
        llm_client=mock_client,
        top_k_for_llm=1,
        cost_tracker=tracker,
    )

    source_entities = [_make_source_entity()]
    ontology_terms = [_make_ontology_term(term_id="PATO:0000125", label="mass")]
    agent.generate_candidates(source_entities, ontology_terms)

    assert tracker.summary()["total_calls"] >= 1


def test_cost_tracker_wired_into_ontology_engineer_reviewer():
    """LLM calls through LLMOntologyEngineerReviewerAgent are recorded in the tracker."""
    tracker = LLMCostTracker()

    flag_response = json.dumps({"flags": [], "recommendation": "proceed"})
    mock_client = _make_mock_client_with_response(flag_response)
    reviewer = LLMOntologyEngineerReviewerAgent(
        llm_client=mock_client,
        cost_tracker=tracker,
    )

    hyp = _make_hypothesis()
    reviewer.review_hypothesis(hyp)

    assert tracker.summary()["total_calls"] == 1


def test_cost_tracker_wired_into_domain_scientist_reviewer():
    """LLM calls through LLMDomainScientistReviewerAgent are recorded in the tracker."""
    tracker = LLMCostTracker()

    flag_response = json.dumps({"flags": [], "recommendation": "proceed"})
    mock_client = _make_mock_client_with_response(flag_response)
    reviewer = LLMDomainScientistReviewerAgent(
        llm_client=mock_client,
        cost_tracker=tracker,
    )

    hyp = _make_hypothesis()
    reviewer.review_hypothesis(hyp)

    assert tracker.summary()["total_calls"] == 1
