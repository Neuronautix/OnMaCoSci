"""Tests for the LLM-backed adversarial reviewer.

All tests that would trigger real LLM API calls use a mock client so that
the test suite can run without an ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Allow running with PYTHONPATH=src or from within the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.agents.llm_adversarial_reviewer import (
    LLMAdversarialReviewerAgent,
)
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
)
from ontology_mapping_co_scientist.models.review import AdversarialReviewResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hypothesis(
    mapping_id: str = "test-map-001",
    predicate: MappingPredicate = MappingPredicate.CLOSE_MATCH,
    confidence: float = 0.75,
    with_examples: bool = True,
    with_definition: bool = True,
) -> MappingHypothesis:
    """Build a minimal but valid MappingHypothesis for testing."""
    source = SourceEntity(
        entity_id="csv:test.field",
        label="body weight",
        description="Weight of the animal in kilograms",
        datatype="number",
        examples=["10.5", "12.3"] if with_examples else [],
        source_file="test.csv",
        source_type="csv",
    )
    target = OntologyTerm(
        term_id="PATO:0000125",
        label="mass",
        definition=(
            "A physical quality that inheres in a body by virtue of the proportion "
            "of that body's substance to a unit volume."
        ) if with_definition else None,
        synonyms=["weight", "body mass"],
        term_type="class",
        ontology_id="PATO",
    )
    provenance = Provenance(
        created_by="TestAgent",
        created_at="2026-01-01T00:00:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="test-run-001",
    )
    evidence = [
        Evidence(
            evidence_type="lexical_similarity",
            description="Label similarity between 'body weight' and 'mass': 0.75",
            score=0.75,
            source="TestScoringAgent",
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


def _make_llm_response_json(
    flags: list[dict] | None = None,
    overall_assessment: str = "Mapping appears sound.",
    recommendation: str = "proceed",
) -> str:
    """Return a raw JSON string as the LLM would emit."""
    return json.dumps(
        {
            "flags": flags or [],
            "overall_assessment": overall_assessment,
            "recommendation": recommendation,
        }
    )


def _make_mock_client(response_text: str) -> MagicMock:
    """Create a mock anthropic client whose messages.create returns response_text."""
    mock_content_block = MagicMock()
    mock_content_block.text = response_text

    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# Construction and fallback tests
# ---------------------------------------------------------------------------


def test_fallback_when_no_client():
    """LLMAdversarialReviewerAgent() with no client falls back to heuristic reviewer."""
    agent = LLMAdversarialReviewerAgent()
    assert agent.llm_client is None
    assert agent._fallback is not None

    hypothesis = _make_hypothesis()
    result = agent.review_hypothesis(hypothesis)

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == hypothesis.mapping_id
    assert result.overall_severity in ("clean", "low", "medium", "high")
    assert result.recommendation in ("proceed", "review", "reject")


def test_no_client_no_fallback_raises():
    """LLMAdversarialReviewerAgent(fallback_to_heuristic=False) raises ValueError when no client."""
    with pytest.raises(ValueError, match="fallback_to_heuristic=False"):
        LLMAdversarialReviewerAgent(llm_client=None, fallback_to_heuristic=False)


def test_from_env_without_api_key(monkeypatch):
    """from_env() without ANTHROPIC_API_KEY returns a heuristic-only agent."""
    # Remove the key from the environment if it happens to be set
    monkeypatch.setenv("OMCS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = LLMAdversarialReviewerAgent.from_env()
    # Should not raise; should silently fall back
    assert agent.llm_client is None
    assert agent._fallback is not None


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------


def test_parse_valid_json_response():
    """_parse_llm_response correctly parses a valid JSON string."""
    agent = LLMAdversarialReviewerAgent()  # heuristic mode is fine for parsing

    flags = [
        {
            "flag_type": "unit_mismatch",
            "description": "Source uses kg but target does not specify units.",
            "severity": "medium",
        },
        {
            "flag_type": "weak_exactmatch",
            "description": "exactMatch is too strong for this pairing.",
            "severity": "high",
        },
    ]
    response_text = _make_llm_response_json(
        flags=flags,
        overall_assessment="Two issues found.",
        recommendation="reject",
    )

    result = agent._parse_llm_response(response_text, mapping_id="test-map-parse-001")

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == "test-map-parse-001"
    assert len(result.flags) == 2
    assert result.flags[0].flag_type == "unit_mismatch"
    assert result.flags[0].severity == "medium"
    assert result.flags[1].flag_type == "weak_exactmatch"
    assert result.flags[1].severity == "high"
    assert result.overall_severity == "high"
    assert result.recommendation == "reject"


def test_parse_json_with_markdown_fences():
    """_parse_llm_response handles ```json ... ``` wrapping."""
    agent = LLMAdversarialReviewerAgent()

    inner = _make_llm_response_json(
        flags=[
            {
                "flag_type": "broad_match_preferred",
                "description": "Should be broadMatch rather than exactMatch.",
                "severity": "low",
            }
        ],
        overall_assessment="Minor concern.",
        recommendation="review",
    )
    wrapped = f"```json\n{inner}\n```"

    result = agent._parse_llm_response(wrapped, mapping_id="test-map-fence-001")

    assert isinstance(result, AdversarialReviewResult)
    assert len(result.flags) == 1
    assert result.flags[0].flag_type == "broad_match_preferred"
    assert result.overall_severity == "low"


def test_parse_invalid_json_returns_error_flag():
    """Malformed JSON response produces a result with a single 'llm_parse_error' flag."""
    agent = LLMAdversarialReviewerAgent()

    bad_text = "This is not JSON at all }{{"
    result = agent._parse_llm_response(bad_text, mapping_id="test-map-bad-json")

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == "test-map-bad-json"
    assert len(result.flags) == 1
    assert result.flags[0].flag_type == "llm_parse_error"
    assert result.flags[0].severity == "low"
    assert result.recommendation == "proceed"


def test_parse_empty_flags_list():
    """A JSON response with no flags yields a clean result."""
    agent = LLMAdversarialReviewerAgent()
    response_text = _make_llm_response_json(
        flags=[], overall_assessment="Mapping appears sound.", recommendation="proceed"
    )
    result = agent._parse_llm_response(response_text, mapping_id="test-map-clean")
    assert result.overall_severity == "clean"
    assert result.recommendation == "proceed"
    assert result.flags == []


# ---------------------------------------------------------------------------
# review_all tests
# ---------------------------------------------------------------------------


def test_review_all_returns_list():
    """review_all returns a list of AdversarialReviewResult with the same length as input."""
    agent = LLMAdversarialReviewerAgent()  # heuristic fallback

    hypotheses = [
        _make_hypothesis(mapping_id=f"test-map-{i:03d}") for i in range(5)
    ]
    results = agent.review_all(hypotheses)

    assert isinstance(results, list)
    assert len(results) == 5
    for result in results:
        assert isinstance(result, AdversarialReviewResult)


def test_review_all_with_mock_llm():
    """review_all with a mock LLM client calls messages.create for each hypothesis."""
    llm_response = _make_llm_response_json(
        flags=[
            {
                "flag_type": "test_flag",
                "description": "Test description.",
                "severity": "low",
            }
        ],
        overall_assessment="One minor issue.",
        recommendation="proceed",
    )
    mock_client = _make_mock_client(llm_response)
    agent = LLMAdversarialReviewerAgent(llm_client=mock_client)

    hypotheses = [_make_hypothesis(mapping_id=f"test-map-llm-{i}") for i in range(3)]
    results = agent.review_all(hypotheses)

    assert len(results) == 3
    assert mock_client.messages.create.call_count == 3
    assert agent.llm_attempted_reviews == 3
    assert agent.llm_successful_reviews == 3
    assert agent.fallback_reviews == 0
    for result in results:
        assert len(result.flags) == 1
        assert result.flags[0].flag_type == "test_flag"


# ---------------------------------------------------------------------------
# _build_prompt tests
# ---------------------------------------------------------------------------


def test_build_prompt_contains_key_fields():
    """_build_prompt output contains source label, target label, and predicate."""
    agent = LLMAdversarialReviewerAgent()
    hypothesis = _make_hypothesis(
        predicate=MappingPredicate.EXACT_MATCH,
        confidence=0.91,
    )
    prompt = agent._build_prompt(hypothesis)

    assert "body weight" in prompt
    assert "mass" in prompt
    assert MappingPredicate.EXACT_MATCH.value in prompt
    assert "0.91" in prompt
    # Prompt must request JSON output
    assert "JSON" in prompt
    assert "flag_type" in prompt
    assert "severity" in prompt


def test_build_prompt_shows_no_definition():
    """_build_prompt gracefully handles a target term with no definition."""
    agent = LLMAdversarialReviewerAgent()
    hypothesis = _make_hypothesis(with_definition=False)
    prompt = agent._build_prompt(hypothesis)
    assert "no definition available" in prompt


def test_build_prompt_shows_no_examples():
    """_build_prompt gracefully handles a source entity with no examples."""
    agent = LLMAdversarialReviewerAgent()
    hypothesis = _make_hypothesis(with_examples=False)
    prompt = agent._build_prompt(hypothesis)
    assert "none" in prompt


# ---------------------------------------------------------------------------
# LLM mode: mocked API call
# ---------------------------------------------------------------------------


def test_llm_review_calls_api_and_parses():
    """_llm_review calls the LLM API and returns a parsed AdversarialReviewResult."""
    llm_response = _make_llm_response_json(
        flags=[
            {
                "flag_type": "predicate_too_strong",
                "description": "exactMatch is not warranted at this confidence level.",
                "severity": "high",
            }
        ],
        overall_assessment="Predicate is problematic.",
        recommendation="reject",
    )
    mock_client = _make_mock_client(llm_response)
    agent = LLMAdversarialReviewerAgent(llm_client=mock_client)

    hypothesis = _make_hypothesis(
        predicate=MappingPredicate.EXACT_MATCH,
        confidence=0.55,
    )
    result = agent._llm_review(hypothesis)

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == hypothesis.mapping_id
    assert agent.llm_attempted_reviews == 1
    assert agent.llm_successful_reviews == 1
    assert agent.fallback_reviews == 0
    assert len(result.flags) == 1
    assert result.flags[0].flag_type == "predicate_too_strong"
    assert result.overall_severity == "high"
    assert result.recommendation == "reject"


def test_llm_api_error_falls_back_to_heuristic():
    """When the LLM API raises an exception, _llm_review falls back to heuristic reviewer."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("Network error")

    agent = LLMAdversarialReviewerAgent(llm_client=mock_client)
    hypothesis = _make_hypothesis()

    # Should not raise — should fall back to heuristic
    result = agent._llm_review(hypothesis)

    assert isinstance(result, AdversarialReviewResult)
    assert result.mapping_id == hypothesis.mapping_id
    assert agent.llm_attempted_reviews == 1
    assert agent.llm_successful_reviews == 0
    assert agent.fallback_reviews == 1


def test_apply_flags_to_hypotheses():
    """apply_flags_to_hypotheses merges flags into hypothesis warnings and counter-evidence."""
    agent = LLMAdversarialReviewerAgent()
    hypothesis = _make_hypothesis()
    results = agent.review_all([hypothesis])

    original_warnings = len(hypothesis.warnings)
    updated = agent.apply_flags_to_hypotheses([hypothesis], results)

    assert len(updated) == 1
    # Warnings should have been updated (unless review was completely clean)
    result = results[0]
    expected_added_warnings = len(result.flags)
    assert len(updated[0].warnings) >= original_warnings
    if expected_added_warnings > 0:
        assert len(updated[0].warnings) > original_warnings
