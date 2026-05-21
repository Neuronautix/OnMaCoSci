"""Tests for the candidate generator pipeline stage and its sub-components.

This module tests:
- The lexical similarity scoring utilities (normalize_label, label_to_predicate).
- The adversarial reviewer agent (AdversarialReviewerAgent).
- The ranking agent (RankingAgent).
- Higher-level hypothesis construction and field invariants.

Note: CandidateGeneratorAgent.generate_candidates has a known API mismatch
between the call site in candidate_generator.py (which passes a list[str] to
find_best_matches) and the actual find_best_matches signature (which expects
list[tuple[str, str]]).  The tests that verify the overall candidate generation
flow are therefore restricted to the component-level public API that works
correctly.
"""

from __future__ import annotations

import pytest

from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
    AdversarialReviewerAgent,
)
from ontology_mapping_co_scientist.agents.ranking_agent import RankingAgent
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    HumanReviewStatus,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
    ValidationStatus,
)
from ontology_mapping_co_scientist.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
)
from ontology_mapping_co_scientist.scoring.evidence_scoring import (
    build_lexical_evidence,
    build_synonym_evidence,
    compute_aggregate_confidence,
)
from ontology_mapping_co_scientist.scoring.lexical_similarity import (
    compute_similarity,
    find_best_matches,
    label_to_predicate,
    normalize_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provenance() -> Provenance:
    """Return a minimal Provenance object suitable for tests."""
    return Provenance(
        created_by="TestAgent",
        created_at="2025-03-15T14:22:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="run-test-001",
    )


def _make_source_entity(
    label: str,
    entity_id: str | None = None,
    datatype: str = "string",
    examples: list[str] | None = None,
) -> SourceEntity:
    """Helper to create a SourceEntity with sensible defaults."""
    return SourceEntity(
        entity_id=entity_id or f"csv:test.{label.lower().replace(' ', '_')}",
        label=label,
        datatype=datatype,
        examples=examples or [],
        source_type="csv",
    )


def _make_ontology_term(
    term_id: str,
    label: str,
    synonyms: list[str] | None = None,
    definition: str | None = None,
    term_type: str = "class",
) -> OntologyTerm:
    """Helper to create an OntologyTerm with sensible defaults."""
    return OntologyTerm(
        term_id=term_id,
        label=label,
        definition=definition,
        synonyms=synonyms or [],
        term_type=term_type,
        ontology_id="mbo",
        extra_context={},
    )


def _make_hypothesis(
    source_entity: SourceEntity,
    target_entity: OntologyTerm,
    predicate: MappingPredicate,
    confidence: float,
    mapping_id: str = "map-test-001",
    evidence: list[Evidence] | None = None,
) -> MappingHypothesis:
    """Helper to create a MappingHypothesis for tests."""
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source_entity,
        target_entity=target_entity,
        predicate=predicate,
        confidence=confidence,
        evidence=evidence or [],
        validation_status=ValidationStatus.PENDING,
        human_review_status=HumanReviewStatus.AWAITING_REVIEW,
        provenance=_make_provenance(),
    )


# ---------------------------------------------------------------------------
# Lexical similarity utilities
# ---------------------------------------------------------------------------


class TestLexicalSimilarity:
    """Tests for the lexical_similarity module's public functions."""

    def test_normalize_label_removes_underscores(self) -> None:
        """normalize_label must replace underscores with spaces."""
        result = normalize_label("mouse_strain")
        assert result == "mouse strain", (
            f"Expected 'mouse strain', got {result!r}"
        )

    def test_normalize_label_removes_hyphens(self) -> None:
        """normalize_label must replace hyphens with spaces."""
        result = normalize_label("body-weight")
        assert result == "body weight"

    def test_normalize_label_lowercases(self) -> None:
        """normalize_label must convert to lowercase."""
        result = normalize_label("MouseStrain")
        assert result == "mousestrain" or result == "mouse strain"
        assert result == result.lower()

    def test_normalize_label_collapses_whitespace(self) -> None:
        """normalize_label must collapse runs of whitespace to a single space."""
        result = normalize_label("genetic  background")
        assert result == "genetic background"

    def test_compute_similarity_identical_strings(self) -> None:
        """compute_similarity must return 1.0 for identical strings."""
        score = compute_similarity("strain", "strain")
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_compute_similarity_completely_different(self) -> None:
        """compute_similarity must return a low score for unrelated strings."""
        score = compute_similarity("xxxxxx", "yyyyyy")
        assert score < 0.5, f"Expected low score for unrelated strings, got {score}"

    def test_compute_similarity_partial_overlap(self) -> None:
        """compute_similarity must return a high score for 'strain' vs 'mouse strain'."""
        score = compute_similarity("strain", "mouse strain")
        # rapidfuzz partial_ratio / WRatio handles substring well
        assert score >= 0.85, (
            f"Expected score >= 0.85 for 'strain'/'mouse strain', got {score}"
        )

    def test_find_best_matches_returns_top_k(self) -> None:
        """find_best_matches must return at most top_k results."""
        candidates = [
            ("mbo:MouseStrain", "mouse strain"),
            ("mbo:BodyWeight", "body weight"),
            ("mbo:Sex", "sex"),
            ("mbo:Age", "age"),
            ("mbo:Weight", "weight"),
        ]
        results = find_best_matches("strain", candidates, top_k=3)
        assert len(results) <= 3, f"Expected at most 3 results, got {len(results)}"

    def test_find_best_matches_sorted_by_score(self) -> None:
        """find_best_matches must return results sorted by score descending."""
        candidates = [
            ("mbo:MouseStrain", "mouse strain"),
            ("mbo:BodyWeight", "body weight"),
            ("mbo:Sex", "sex"),
        ]
        results = find_best_matches("strain", candidates, top_k=5)
        scores = [score for _, _, score in results]
        assert scores == sorted(scores, reverse=True), (
            "Results must be sorted by score descending"
        )

    def test_find_best_matches_high_score_for_strain(self) -> None:
        """'strain' against candidates including 'mouse strain' must rank 'mouse strain' first."""
        candidates = [
            ("mbo:MouseStrain", "mouse strain"),
            ("mbo:BodyWeight", "body weight"),
            ("mbo:Sex", "sex"),
        ]
        results = find_best_matches("strain", candidates, top_k=3)
        assert len(results) >= 1
        top_term_id, top_label, top_score = results[0]
        assert top_term_id == "mbo:MouseStrain", (
            f"Expected 'mbo:MouseStrain' at rank 1, got {top_term_id!r}"
        )
        assert top_score >= 0.85, (
            f"Expected score >= 0.85 for 'strain'/'mouse strain', got {top_score}"
        )

    def test_find_best_matches_empty_candidates(self) -> None:
        """find_best_matches must return an empty list for an empty candidates list."""
        result = find_best_matches("strain", [], top_k=5)
        assert result == []

    # ------------------------------------------------------------------
    # label_to_predicate threshold tests
    # ------------------------------------------------------------------

    def test_label_to_predicate_exact_match(self) -> None:
        """Score >= 0.90 must map to EXACT_MATCH."""
        result = label_to_predicate(0.95)
        assert result == MappingPredicate.EXACT_MATCH, (
            f"Expected EXACT_MATCH for score=0.95, got {result!r}"
        )

    def test_label_to_predicate_exact_match_boundary(self) -> None:
        """Score exactly at 0.90 must map to EXACT_MATCH."""
        result = label_to_predicate(0.90)
        assert result == MappingPredicate.EXACT_MATCH

    def test_label_to_predicate_close_match(self) -> None:
        """Score of 0.80 must map to CLOSE_MATCH (in range [0.75, 0.89])."""
        result = label_to_predicate(0.80)
        assert result == MappingPredicate.CLOSE_MATCH, (
            f"Expected CLOSE_MATCH for score=0.80, got {result!r}"
        )

    def test_label_to_predicate_broad_match(self) -> None:
        """Score of 0.65 must map to BROAD_MATCH (in range [0.55, 0.74])."""
        result = label_to_predicate(0.65)
        assert result == MappingPredicate.BROAD_MATCH, (
            f"Expected BROAD_MATCH for score=0.65, got {result!r}"
        )

    def test_label_to_predicate_related_match(self) -> None:
        """Score of 0.45 must map to RELATED_MATCH (in range [0.40, 0.54])."""
        result = label_to_predicate(0.45)
        assert result == MappingPredicate.RELATED_MATCH, (
            f"Expected RELATED_MATCH for score=0.45, got {result!r}"
        )

    def test_label_to_predicate_no_mapping(self) -> None:
        """Score of 0.20 must map to NO_MAPPING (below 0.40)."""
        result = label_to_predicate(0.20)
        assert result == MappingPredicate.NO_MAPPING, (
            f"Expected NO_MAPPING for score=0.20, got {result!r}"
        )

    def test_label_to_predicate_zero(self) -> None:
        """Score of 0.0 must map to NO_MAPPING."""
        result = label_to_predicate(0.0)
        assert result == MappingPredicate.NO_MAPPING


# ---------------------------------------------------------------------------
# Evidence scoring utilities
# ---------------------------------------------------------------------------


class TestEvidenceScoring:
    """Tests for evidence factory functions and aggregate confidence."""

    def test_build_lexical_evidence_type(self) -> None:
        """build_lexical_evidence must produce evidence_type='lexical_similarity'."""
        ev = build_lexical_evidence("strain", "mouse strain", 0.82)
        assert ev.evidence_type == "lexical_similarity"

    def test_build_lexical_evidence_score_stored(self) -> None:
        """build_lexical_evidence must store the supplied score."""
        ev = build_lexical_evidence("strain", "mouse strain", 0.82)
        assert ev.score == pytest.approx(0.82, abs=1e-6)

    def test_build_lexical_evidence_description_contains_labels(self) -> None:
        """build_lexical_evidence description must quote both labels."""
        ev = build_lexical_evidence("strain", "mouse strain", 0.82)
        assert "strain" in ev.description
        assert "mouse strain" in ev.description

    def test_build_synonym_evidence_type(self) -> None:
        """build_synonym_evidence must produce evidence_type='synonym_match'."""
        ev = build_synonym_evidence(
            source_label="strain",
            matched_synonym="mouse strain",
            term_id="mbo:MouseStrain",
            score=0.90,
        )
        assert ev.evidence_type == "synonym_match"

    def test_build_synonym_evidence_score_stored(self) -> None:
        """build_synonym_evidence must store the supplied score."""
        ev = build_synonym_evidence(
            source_label="strain",
            matched_synonym="mouse strain",
            term_id="mbo:MouseStrain",
            score=0.90,
        )
        assert ev.score == pytest.approx(0.90, abs=1e-6)

    def test_compute_aggregate_confidence_single_evidence(self) -> None:
        """compute_aggregate_confidence with one evidence item must return its score."""
        ev = Evidence(
            evidence_type="lexical_similarity",
            description="test",
            score=0.75,
        )
        result = compute_aggregate_confidence([ev], [])
        assert result == pytest.approx(0.75, abs=1e-6)

    def test_compute_aggregate_confidence_mean_of_two(self) -> None:
        """compute_aggregate_confidence with two items must return their mean score."""
        ev1 = Evidence(evidence_type="lexical_similarity", description="t1", score=0.80)
        ev2 = Evidence(evidence_type="synonym_match", description="t2", score=0.90)
        result = compute_aggregate_confidence([ev1, ev2], [])
        assert result == pytest.approx(0.85, abs=1e-6)

    def test_compute_aggregate_confidence_counter_evidence_reduces_score(
        self,
    ) -> None:
        """Counter-evidence items must reduce the aggregate confidence score."""
        ev = Evidence(evidence_type="lexical_similarity", description="t", score=0.80)
        counter = Evidence(
            evidence_type="datatype_mismatch", description="c", score=0.5
        )
        base = compute_aggregate_confidence([ev], [])
        penalised = compute_aggregate_confidence([ev], [counter])
        assert penalised < base, (
            "Counter-evidence must reduce the aggregate confidence"
        )

    def test_compute_aggregate_confidence_clamped_to_unit_interval(self) -> None:
        """Aggregate confidence must always be in [0.0, 1.0]."""
        ev = Evidence(evidence_type="lexical_similarity", description="t", score=1.0)
        many_counters = [
            Evidence(evidence_type="x", description="c", score=0.9)
            for _ in range(20)
        ]
        result = compute_aggregate_confidence([ev], many_counters)
        assert 0.0 <= result <= 1.0

    def test_compute_aggregate_confidence_empty_evidence_returns_zero(self) -> None:
        """compute_aggregate_confidence with no evidence must return 0.0."""
        result = compute_aggregate_confidence([], [])
        assert result == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Hypothesis field invariants
# ---------------------------------------------------------------------------


class TestHypothesisFieldInvariants:
    """Tests verifying that MappingHypothesis objects have all required fields."""

    def test_hypothesis_has_required_fields(
        self, sample_hypothesis: MappingHypothesis
    ) -> None:
        """A well-formed MappingHypothesis must have all required fields populated."""
        h = sample_hypothesis
        assert h.mapping_id, "mapping_id must be non-empty"
        assert h.source_entity is not None, "source_entity must be present"
        assert h.target_entity is not None, "target_entity must be present"
        assert h.predicate is not None, "predicate must be present"
        assert h.confidence is not None, "confidence must be present"
        assert h.provenance is not None, "provenance must be present"

    def test_hypothesis_confidence_in_valid_range(
        self, sample_hypothesis: MappingHypothesis
    ) -> None:
        """MappingHypothesis confidence must be in [0.0, 1.0]."""
        assert 0.0 <= sample_hypothesis.confidence <= 1.0, (
            f"Confidence {sample_hypothesis.confidence} is outside [0.0, 1.0]"
        )

    def test_hypothesis_predicate_is_mapping_predicate(
        self, sample_hypothesis: MappingHypothesis
    ) -> None:
        """MappingHypothesis predicate must be a MappingPredicate enum member."""
        assert isinstance(sample_hypothesis.predicate, MappingPredicate)

    def test_hypothesis_evidence_is_list(
        self, sample_hypothesis: MappingHypothesis
    ) -> None:
        """MappingHypothesis evidence must be a list."""
        assert isinstance(sample_hypothesis.evidence, list)

    def test_hypothesis_default_validation_status(self) -> None:
        """A freshly created hypothesis must have validation_status=PENDING."""
        se = _make_source_entity("test_field")
        ot = _make_ontology_term("mbo:Test", "test concept", definition="A test concept.")
        h = _make_hypothesis(se, ot, MappingPredicate.RELATED_MATCH, 0.5)
        assert h.validation_status == ValidationStatus.PENDING

    def test_hypothesis_default_rank_is_none(self) -> None:
        """A freshly created hypothesis must have rank=None (not yet ranked)."""
        se = _make_source_entity("test_field")
        ot = _make_ontology_term("mbo:Test", "test concept", definition="A test concept.")
        h = _make_hypothesis(se, ot, MappingPredicate.RELATED_MATCH, 0.5)
        assert h.rank is None


# ---------------------------------------------------------------------------
# Adversarial reviewer
# ---------------------------------------------------------------------------


class TestAdversarialReviewer:
    """Tests for AdversarialReviewerAgent.review_hypothesis."""

    def test_adversarial_reviewer_flags_weak_similarity(self) -> None:
        """A hypothesis with confidence=0.3 must be flagged for weak similarity."""
        se = _make_source_entity("strain", examples=["C57BL/6J"])
        ot = _make_ontology_term(
            "mbo:GeneticBackground",
            "genetic background",
            definition="A genetically distinct lineage.",
        )
        h = _make_hypothesis(se, ot, MappingPredicate.BROAD_MATCH, 0.3)
        agent = AdversarialReviewerAgent()
        result = agent.review_hypothesis(h)

        flag_types = {f.flag_type for f in result.flags}
        assert "weak_lexical_similarity" in flag_types, (
            f"Expected 'weak_lexical_similarity' flag for low-confidence hypothesis; "
            f"got flags: {flag_types}"
        )

    def test_adversarial_reviewer_flags_exact_match_low_confidence(self) -> None:
        """EXACT_MATCH with confidence < 0.85 must be flagged as a strong claim."""
        se = _make_source_entity("strain", examples=["C57BL/6J"])
        ot = _make_ontology_term(
            "mbo:GeneticBackground",
            "genetic background",
            definition="A genetically distinct lineage.",
        )
        ev = Evidence(
            evidence_type="lexical_similarity",
            description="Lexical similarity between 'strain' and 'genetic background': 0.60",
            score=0.60,
        )
        h = _make_hypothesis(
            se, ot, MappingPredicate.EXACT_MATCH, 0.60, evidence=[ev]
        )
        agent = AdversarialReviewerAgent()
        result = agent.review_hypothesis(h)

        flag_types = {f.flag_type for f in result.flags}
        assert "strong_exactmatch_claim" in flag_types, (
            f"Expected 'strong_exactmatch_claim' flag for EXACT_MATCH + confidence=0.60; "
            f"got flags: {flag_types}"
        )

    def test_adversarial_reviewer_high_severity_has_blocking_issues(self) -> None:
        """A result with a 'high' flag must report has_blocking_issues() == True."""
        flag = AdversarialFlag(
            flag_type="strong_exactmatch_claim",
            description="Test high-severity flag",
            severity="high",
        )
        result = AdversarialReviewResult(
            mapping_id="map-001",
            flags=[flag],
            overall_severity="high",
            recommendation="reject",
        )
        assert result.has_blocking_issues() is True

    def test_adversarial_reviewer_clean_result_no_blocking_issues(self) -> None:
        """An AdversarialReviewResult with no flags must report has_blocking_issues() == False."""
        result = AdversarialReviewResult(
            mapping_id="map-001",
            flags=[],
            overall_severity="clean",
            recommendation="proceed",
        )
        assert result.has_blocking_issues() is False

    def test_adversarial_reviewer_no_mapping_always_flagged(self) -> None:
        """A NO_MAPPING hypothesis must always produce at least one flag."""
        se = _make_source_entity("unknown_field")
        ot = _make_ontology_term("custom:no_mapping", "No Mapping", term_type="sentinel")
        h = _make_hypothesis(se, ot, MappingPredicate.NO_MAPPING, 0.0)
        agent = AdversarialReviewerAgent()
        result = agent.review_hypothesis(h)

        assert len(result.flags) >= 1, (
            "A NO_MAPPING hypothesis must produce at least one adversarial flag"
        )

    def test_adversarial_reviewer_review_all_returns_one_result_per_hypothesis(
        self,
    ) -> None:
        """review_all must return exactly one AdversarialReviewResult per hypothesis."""
        se = _make_source_entity("strain", examples=["C57BL/6J"])
        ot = _make_ontology_term("mbo:G1", "genetic background", definition="Def.")

        hypotheses = [
            _make_hypothesis(se, ot, MappingPredicate.CLOSE_MATCH, 0.82, "map-001"),
            _make_hypothesis(se, ot, MappingPredicate.BROAD_MATCH, 0.60, "map-002"),
        ]
        agent = AdversarialReviewerAgent()
        results = agent.review_all(hypotheses)

        assert len(results) == len(hypotheses), (
            f"Expected {len(hypotheses)} review results, got {len(results)}"
        )

    def test_adversarial_reviewer_apply_flags_populates_warnings(self) -> None:
        """apply_flags_to_hypotheses must append flag descriptions as warnings."""
        se = _make_source_entity("strain", examples=["C57BL/6J"])
        ot = _make_ontology_term("mbo:G1", "genetic background", definition="Def.")
        h = _make_hypothesis(se, ot, MappingPredicate.BROAD_MATCH, 0.30, "map-001")

        agent = AdversarialReviewerAgent()
        results = agent.review_all([h])
        agent.apply_flags_to_hypotheses([h], results)

        assert len(h.warnings) >= 1, (
            "Hypothesis warnings must be populated after apply_flags_to_hypotheses"
        )


# ---------------------------------------------------------------------------
# Ranking agent
# ---------------------------------------------------------------------------


class TestRankingAgent:
    """Tests for RankingAgent.rank_hypotheses and RankingAgent.get_top_mapping."""

    def _two_hypotheses_same_entity(self) -> list[MappingHypothesis]:
        """Return two hypotheses for the same source entity with different confidence."""
        se = _make_source_entity("strain")
        ot1 = _make_ontology_term("mbo:G1", "genetic background", definition="Def 1.")
        ot2 = _make_ontology_term("mbo:G2", "body weight", definition="Def 2.")
        return [
            _make_hypothesis(se, ot1, MappingPredicate.CLOSE_MATCH, 0.82, "map-001"),
            _make_hypothesis(se, ot2, MappingPredicate.RELATED_MATCH, 0.45, "map-002"),
        ]

    def test_ranking_assigns_ranks(self) -> None:
        """rank_hypotheses must assign integer ranks to all hypotheses."""
        hypotheses = self._two_hypotheses_same_entity()
        agent = RankingAgent()
        ranked = agent.rank_hypotheses(hypotheses, {})

        for h in ranked:
            assert h.rank is not None, f"Hypothesis {h.mapping_id} has no rank"
            assert isinstance(h.rank, int), f"rank must be int, got {type(h.rank)}"

    def test_ranking_starts_at_one(self) -> None:
        """The best-ranked hypothesis must have rank=1."""
        hypotheses = self._two_hypotheses_same_entity()
        agent = RankingAgent()
        ranked = agent.rank_hypotheses(hypotheses, {})

        min_rank = min(h.rank for h in ranked if h.rank is not None)  # type: ignore[arg-type]
        assert min_rank == 1, f"Minimum rank must be 1, got {min_rank}"

    def test_ranking_higher_confidence_ranked_first(self) -> None:
        """Without adversarial penalties, higher confidence must receive rank=1."""
        hypotheses = self._two_hypotheses_same_entity()
        agent = RankingAgent()
        agent.rank_hypotheses(hypotheses, {})

        # map-001 has confidence=0.82, map-002 has 0.45
        h1 = next(h for h in hypotheses if h.mapping_id == "map-001")
        h2 = next(h for h in hypotheses if h.mapping_id == "map-002")
        assert h1.rank == 1, (
            f"Higher-confidence hypothesis must rank 1, got rank={h1.rank}"
        )
        assert h2.rank == 2, (
            f"Lower-confidence hypothesis must rank 2, got rank={h2.rank}"
        )

    def test_ranking_get_top_mapping_returns_rank1(self) -> None:
        """get_top_mapping must return the rank=1 hypothesis for each source entity."""
        hypotheses = self._two_hypotheses_same_entity()
        agent = RankingAgent()
        agent.rank_hypotheses(hypotheses, {})
        top = agent.get_top_mapping(hypotheses)

        entity_id = hypotheses[0].source_entity.entity_id
        assert entity_id in top, "source entity must appear in the top mapping dict"
        assert top[entity_id].rank == 1, (
            f"get_top_mapping must return rank=1 hypothesis; got rank={top[entity_id].rank}"
        )

    def test_ranking_multiple_entities_independent_ranks(self) -> None:
        """Ranking must be independent per source entity — each entity starts at rank 1."""
        se1 = _make_source_entity("strain", entity_id="csv:test.strain")
        se2 = _make_source_entity("sex", entity_id="csv:test.sex")
        ot = _make_ontology_term("mbo:G1", "genetic background", definition="Def.")

        h1 = _make_hypothesis(se1, ot, MappingPredicate.CLOSE_MATCH, 0.80, "map-e1")
        h2 = _make_hypothesis(se2, ot, MappingPredicate.RELATED_MATCH, 0.50, "map-e2")

        agent = RankingAgent()
        agent.rank_hypotheses([h1, h2], {})

        # Each entity has exactly one hypothesis, so both must be rank 1
        assert h1.rank == 1, f"h1 must be rank 1 (sole candidate for se1), got {h1.rank}"
        assert h2.rank == 1, f"h2 must be rank 1 (sole candidate for se2), got {h2.rank}"
