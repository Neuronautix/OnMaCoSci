"""Tests for shared core models used by both ontology-align and schema-align."""
from __future__ import annotations

import pytest

from mapping_co_scientist.shared.models.evidence import Evidence, Provenance
from mapping_co_scientist.shared.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
    HumanReviewStatus,
    ValidationStatus,
)
from mapping_co_scientist.shared.models.confidence import ConfidenceScore
from mapping_co_scientist.shared.models.human_decision import HumanReviewAction, SuggestedAction
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.shared.llm.mock_provider import MockLLMProvider
from mapping_co_scientist.shared.llm.provider_interface import LLMMessage
from mapping_co_scientist.shared.scoring.ranking import rank_by_confidence


class TestEvidence:
    def test_basic_construction(self):
        ev = Evidence(
            evidence_type="lexical_similarity",
            description="Label match score 0.87",
            score=0.87,
            source="TestAgent",
        )
        assert ev.evidence_type == "lexical_similarity"
        assert ev.score == 0.87

    def test_score_bounds(self):
        with pytest.raises(Exception):
            Evidence(evidence_type="test", description="bad", score=1.5)

    def test_qualitative_evidence(self):
        ev = Evidence(evidence_type="manual", description="Reviewed by expert")
        assert ev.score is None


class TestProvenance:
    def test_basic_construction(self):
        prov = Provenance(
            created_by="TestAgent",
            created_at="2024-01-01T00:00:00",
            method="lexical_v1",
        )
        assert prov.created_by == "TestAgent"
        assert prov.pipeline_run_id is None


class TestValidationStatus:
    def test_values(self):
        assert ValidationStatus.PENDING == "pending"
        assert ValidationStatus.PASSED == "passed"
        assert ValidationStatus.FAILED == "failed"
        assert ValidationStatus.WARNING == "warning"


class TestHumanReviewStatus:
    def test_values(self):
        assert HumanReviewStatus.AWAITING_REVIEW == "awaiting_review"
        assert HumanReviewStatus.APPROVED == "approved"
        assert HumanReviewStatus.REJECTED == "rejected"


class TestAdversarialReviewResult:
    def test_has_blocking_issues_true(self):
        result = AdversarialReviewResult(
            mapping_id="map-001",
            flags=[AdversarialFlag(flag_type="overreach", description="too strong", severity="high")],
            overall_severity="high",
            recommendation="reject",
        )
        assert result.has_blocking_issues() is True

    def test_has_blocking_issues_false(self):
        result = AdversarialReviewResult(
            mapping_id="map-002",
            flags=[AdversarialFlag(flag_type="minor", description="note", severity="low")],
            overall_severity="low",
            recommendation="proceed",
        )
        assert result.has_blocking_issues() is False

    def test_clean_result(self):
        result = AdversarialReviewResult(
            mapping_id="map-003",
            flags=[],
            overall_severity="clean",
            recommendation="proceed",
        )
        assert result.has_blocking_issues() is False


class TestConfidenceScore:
    def test_very_high(self):
        cs = ConfidenceScore.from_score(0.90)
        assert cs.label == "very_high"

    def test_high(self):
        cs = ConfidenceScore.from_score(0.75)
        assert cs.label == "high"

    def test_medium(self):
        cs = ConfidenceScore.from_score(0.55)
        assert cs.label == "medium"

    def test_low(self):
        cs = ConfidenceScore.from_score(0.35)
        assert cs.label == "low"

    def test_very_low(self):
        cs = ConfidenceScore.from_score(0.10)
        assert cs.label == "very_low"


class TestSourceEntity:
    def test_basic(self):
        e = SourceEntity(
            entity_id="csv:strain",
            label="strain",
            source_type="csv",
        )
        assert e.entity_id == "csv:strain"
        assert e.examples == []


class TestMockLLMProvider:
    def test_default_response(self):
        provider = MockLLMProvider(default_response="DEFAULT")
        resp = provider.complete([LLMMessage(role="user", content="Hello")])
        assert resp.content == "DEFAULT"
        assert resp.model == "mock"

    def test_rule_match(self):
        provider = MockLLMProvider()
        provider.add_rule("strain", "Strain matched a genetic background term")
        resp = provider.complete([LLMMessage(role="user", content="What about strain?")])
        assert "Strain" in resp.content

    def test_no_rule_match(self):
        provider = MockLLMProvider(default_response="fallback")
        provider.add_rule("weight", "weight rule")
        resp = provider.complete([LLMMessage(role="user", content="about strain")])
        assert resp.content == "fallback"


class TestRanking:
    def test_rank_by_confidence(self):
        from dataclasses import dataclass

        @dataclass
        class FakeHyp:
            confidence: float
            rank: int | None = None

        hyps = [FakeHyp(0.60), FakeHyp(0.90), FakeHyp(0.75)]
        ranked = rank_by_confidence(hyps)
        assert ranked[0].confidence == 0.90
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        assert ranked[2].rank == 3

    def test_top_k(self):
        from dataclasses import dataclass

        @dataclass
        class FakeHyp:
            confidence: float
            rank: int | None = None

        hyps = [FakeHyp(0.60), FakeHyp(0.90), FakeHyp(0.75), FakeHyp(0.50)]
        ranked = rank_by_confidence(hyps, top_k=2)
        assert len(ranked) == 2
        assert ranked[0].confidence == 0.90
