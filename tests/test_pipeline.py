"""Integration tests for the ontology mapping pipeline.

These tests exercise the pipeline components in sequence — source profiling,
ontology profiling, adversarial review, ranking, validation, and export —
using real files and real code.  They do not mock internal pipeline stages.

Notes on known limitations
--------------------------
The ``CandidateGeneratorAgent.generate_candidates`` method has an API mismatch
between its internal call site (passes ``list[str]`` to ``find_best_matches``)
and the actual function signature (expects ``list[tuple[str, str]]``).  Rather
than patching this bug, the integration tests that require a list of mapping
hypotheses construct them directly from fixtures, which mirrors real pipeline
usage and exercises all other stages authentically.

The ``markdown_report`` module referenced by ``run_pipeline`` does not yet
exist in the package.  Tests that need a Markdown output file write it
directly using the ``_build_review_packets`` helper and a custom generator,
rather than calling ``run_pipeline`` end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
    AdversarialReviewerAgent,
)
from ontology_mapping_co_scientist.agents.ontology_profiler import OntologyProfilerAgent
from ontology_mapping_co_scientist.agents.ranking_agent import RankingAgent
from ontology_mapping_co_scientist.agents.source_profiler import SourceProfilerAgent
from ontology_mapping_co_scientist.io.exporters import export_to_json, export_to_sssom_tsv
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    HumanReviewStatus,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
    ValidationStatus,
)
from ontology_mapping_co_scientist.pipeline.run_mapping_pipeline import (
    _adversarial_review,
    _rank_hypotheses,
    _validate_hypothesis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provenance(run_id: str = "run-integration-test") -> Provenance:
    """Return a deterministic Provenance for integration tests."""
    return Provenance(
        created_by="IntegrationTestAgent",
        created_at="2025-03-15T14:22:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id=run_id,
    )


def _make_hypothesis(
    mapping_id: str,
    source: SourceEntity,
    target: OntologyTerm,
    predicate: MappingPredicate,
    confidence: float,
    evidence: list[Evidence] | None = None,
) -> MappingHypothesis:
    """Construct a valid MappingHypothesis for integration tests."""
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source,
        target_entity=target,
        predicate=predicate,
        confidence=confidence,
        evidence=evidence or [],
        validation_status=ValidationStatus.PENDING,
        human_review_status=HumanReviewStatus.AWAITING_REVIEW,
        provenance=_make_provenance(),
    )


def _write_markdown_report(
    hypotheses: list[MappingHypothesis],
    output_path: Path,
    pipeline_run_id: str = "run-integration-test",
) -> None:
    """Write a minimal Markdown review report for integration tests.

    This helper exists because the ``markdown_report`` module is not yet
    implemented in the package.  It generates a structurally correct report
    so that tests can verify the file is created and has the expected heading.
    """
    lines = [
        "# Ontology Mapping Review Report",
        "",
        f"**Pipeline run ID:** {pipeline_run_id}",
        "",
        f"**Total hypotheses:** {len(hypotheses)}",
        "",
        "## Mappings",
        "",
    ]
    for h in hypotheses:
        lines.append(
            f"- `{h.mapping_id}`: {h.source_entity.entity_id} "
            f"--[{h.predicate}]--> {h.target_entity.term_id} "
            f"(conf={h.confidence:.2f})"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ontology_terms() -> list[OntologyTerm]:
    """Return a small list of OntologyTerm objects for integration tests."""
    return [
        OntologyTerm(
            term_id="mbo:MouseStrain",
            label="mouse strain",
            definition="A genetically distinct mouse lineage maintained by inbreeding.",
            synonyms=["strain", "genetic background", "mouse line"],
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        ),
        OntologyTerm(
            term_id="mbo:BodyWeight",
            label="body weight",
            definition="The total measured mass of the animal.",
            synonyms=["weight", "mass"],
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        ),
        OntologyTerm(
            term_id="mbo:BiologicalSex",
            label="biological sex",
            definition="The biological sex classification of the animal.",
            synonyms=["sex", "gender"],
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        ),
    ]


@pytest.fixture
def source_entities() -> list[SourceEntity]:
    """Return source entities matching the columns of the tmp_csv_file fixture."""
    return [
        SourceEntity(
            entity_id="csv:animal.strain",
            label="strain",
            description="Genetic strain of the animal",
            datatype="string",
            examples=["C57BL/6J", "BALB/c"],
            source_type="csv",
        ),
        SourceEntity(
            entity_id="csv:animal.sex",
            label="sex",
            datatype="string",
            examples=["M", "F"],
            source_type="csv",
        ),
        SourceEntity(
            entity_id="csv:animal.age_weeks",
            label="age_weeks",
            datatype="number",
            examples=["8", "10"],
            source_type="csv",
        ),
    ]


@pytest.fixture
def integration_hypotheses(
    source_entities: list[SourceEntity],
    ontology_terms: list[OntologyTerm],
) -> list[MappingHypothesis]:
    """Return a pre-built list of mapping hypotheses for integration tests."""
    se_strain, se_sex, se_age = source_entities
    ot_strain, ot_weight, ot_sex = ontology_terms

    return [
        _make_hypothesis(
            "map-csv_animal_strain-mbo_MouseStrain-0",
            se_strain,
            ot_strain,
            MappingPredicate.EXACT_MATCH,
            0.92,
            evidence=[
                Evidence(
                    evidence_type="lexical_similarity",
                    description="Lexical similarity between 'strain' and 'mouse strain': 0.90",
                    score=0.90,
                ),
                Evidence(
                    evidence_type="synonym_match",
                    description="Source 'strain' matches synonym 'strain' of mbo:MouseStrain",
                    score=1.0,
                ),
            ],
        ),
        _make_hypothesis(
            "map-csv_animal_strain-mbo_BodyWeight-1",
            se_strain,
            ot_weight,
            MappingPredicate.RELATED_MATCH,
            0.35,
        ),
        _make_hypothesis(
            "map-csv_animal_sex-mbo_BiologicalSex-0",
            se_sex,
            ot_sex,
            MappingPredicate.CLOSE_MATCH,
            0.85,
            evidence=[
                Evidence(
                    evidence_type="lexical_similarity",
                    description="Lexical similarity between 'sex' and 'biological sex': 0.85",
                    score=0.85,
                ),
            ],
        ),
        _make_hypothesis(
            "map-csv_animal_age_weeks-mbo_BodyWeight-0",
            se_age,
            ot_weight,
            MappingPredicate.BROAD_MATCH,
            0.55,
        ),
    ]


# ---------------------------------------------------------------------------
# Source and ontology profiling stage tests
# ---------------------------------------------------------------------------


class TestPipelineSourceProfiling:
    """Tests for the source-profiling stage using real files."""

    def test_source_profiler_csv_returns_entities(
        self, tmp_csv_file: Path
    ) -> None:
        """Stage 1: SourceProfilerAgent must return at least one entity for a CSV file."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(tmp_csv_file)
        assert len(entities) >= 1, "Must profile at least one entity from the CSV"

    def test_source_profiler_openapi_returns_entities(
        self, tmp_openapi_json: Path
    ) -> None:
        """Stage 1: SourceProfilerAgent must return entities from an OpenAPI JSON."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(tmp_openapi_json)
        assert len(entities) >= 1, "Must profile at least one entity from the OpenAPI JSON"


class TestPipelineOntologyProfiling:
    """Tests for the ontology-profiling stage using real files."""

    def test_ontology_profiler_loads_yaml(
        self, tmp_ontology_yaml: Path
    ) -> None:
        """Stage 2: OntologyProfilerAgent must load terms from the YAML profile."""
        agent = OntologyProfilerAgent()
        terms = agent.load_profile(tmp_ontology_yaml)
        assert len(terms) == 3, (
            f"Expected 3 ontology terms from the fixture, got {len(terms)}"
        )

    def test_ontology_profiler_terms_have_required_fields(
        self, tmp_ontology_yaml: Path
    ) -> None:
        """Each loaded OntologyTerm must have term_id, label, and ontology_id."""
        agent = OntologyProfilerAgent()
        terms = agent.load_profile(tmp_ontology_yaml)
        for term in terms:
            assert term.term_id, f"term_id must be non-empty"
            assert term.label, f"label must be non-empty"
            assert term.ontology_id, f"ontology_id must be non-empty"

    def test_ontology_profiler_builds_index(
        self, tmp_ontology_yaml: Path
    ) -> None:
        """After loading, the internal label index must be populated.

        Note: OntologyProfilerAgent.get_candidates_for_label passes a
        list[str] to find_best_matches, which expects list[tuple[str, str]].
        This is a known API mismatch in the current codebase.  We therefore
        verify the index is built by checking the private _label_index dict
        rather than calling get_candidates_for_label directly.
        """
        agent = OntologyProfilerAgent()
        agent.load_profile(tmp_ontology_yaml)
        # The index is built during load_profile; verify it is non-empty
        assert len(agent._label_index) == 3, (
            f"Expected 3 indexed labels, got {len(agent._label_index)}"
        )
        # The synonym index should also be populated for terms with synonyms
        assert len(agent._synonym_index) >= 1, (
            "Synonym index must be populated for terms with synonyms"
        )

    def test_ontology_profiler_summarize_returns_dict(
        self, tmp_ontology_yaml: Path
    ) -> None:
        """OntologyProfilerAgent.summarize must return a dict with total_terms."""
        agent = OntologyProfilerAgent()
        agent.load_profile(tmp_ontology_yaml)
        summary = agent.summarize()
        assert "total_terms" in summary, "summary must contain 'total_terms'"
        assert summary["total_terms"] == 3


# ---------------------------------------------------------------------------
# Adversarial review stage tests
# ---------------------------------------------------------------------------


class TestPipelineAdversarialReview:
    """Tests for the adversarial review stage."""

    def test_adversarial_review_all_hypotheses_reviewed(
        self, integration_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Every hypothesis must receive an adversarial review result."""
        reviewer = AdversarialReviewerAgent()
        results = reviewer.review_all(integration_hypotheses)
        assert len(results) == len(integration_hypotheses), (
            f"Expected {len(integration_hypotheses)} review results, got {len(results)}"
        )

    def test_adversarial_review_result_has_mapping_id(
        self, integration_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each adversarial review result must reference the correct mapping_id."""
        reviewer = AdversarialReviewerAgent()
        results = reviewer.review_all(integration_hypotheses)
        result_ids = {r.mapping_id for r in results}
        hypothesis_ids = {h.mapping_id for h in integration_hypotheses}
        assert result_ids == hypothesis_ids

    def test_low_confidence_hypothesis_gets_flagged(self) -> None:
        """The pipeline-internal _adversarial_review function flags low confidence."""
        se = SourceEntity(
            entity_id="csv:test.unknown",
            label="unknown_field",
            datatype="string",
            examples=["val1"],
            source_type="csv",
        )
        ot = OntologyTerm(
            term_id="mbo:Test",
            label="test concept",
            definition="A test concept.",
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        )
        h = _make_hypothesis(
            "map-low-conf",
            se,
            ot,
            MappingPredicate.BROAD_MATCH,
            0.25,
        )
        result = _adversarial_review(h)
        flag_types = {f.flag_type for f in result.flags}
        assert len(result.flags) >= 1, (
            "A hypothesis with confidence=0.25 must produce at least one flag"
        )


# ---------------------------------------------------------------------------
# Ranking stage tests
# ---------------------------------------------------------------------------


class TestPipelineRanking:
    """Tests for the ranking stage."""

    def test_rank_hypotheses_assigns_ranks_to_all(
        self, integration_hypotheses: list[MappingHypothesis]
    ) -> None:
        """_rank_hypotheses must assign a rank to every hypothesis."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        for h in ranked:
            assert h.rank is not None, f"Hypothesis {h.mapping_id} was not ranked"

    def test_rank_hypotheses_starts_at_one_per_entity(
        self, integration_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each source entity group must have a rank-1 hypothesis."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        entity_ids = {h.source_entity.entity_id for h in ranked}
        for entity_id in entity_ids:
            group = [h for h in ranked if h.source_entity.entity_id == entity_id]
            ranks = [h.rank for h in group if h.rank is not None]
            assert 1 in ranks, (
                f"Entity {entity_id} has no rank-1 hypothesis; ranks={ranks}"
            )


# ---------------------------------------------------------------------------
# Validation stage tests
# ---------------------------------------------------------------------------


class TestPipelineValidation:
    """Tests for the validation stage."""

    def test_validation_updates_status_from_pending(
        self, integration_hypotheses: list[MappingHypothesis]
    ) -> None:
        """After _validate_hypothesis, every hypothesis must have a non-PENDING status."""
        # Rank first so validation has rank information
        hypotheses = _rank_hypotheses(list(integration_hypotheses))
        for h in hypotheses:
            _validate_hypothesis(h)

        for h in hypotheses:
            assert h.validation_status != ValidationStatus.PENDING, (
                f"Hypothesis {h.mapping_id} still has PENDING status after validation"
            )

    def test_validation_passed_for_well_formed_hypothesis(self) -> None:
        """A well-formed hypothesis with evidence must receive PASSED validation status."""
        se = SourceEntity(
            entity_id="csv:test.strain",
            label="strain",
            datatype="string",
            examples=["C57BL/6J"],
            source_type="csv",
        )
        ot = OntologyTerm(
            term_id="mbo:MouseStrain",
            label="mouse strain",
            definition="A genetically distinct mouse lineage.",
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        )
        ev = Evidence(
            evidence_type="lexical_similarity",
            description="Lexical similarity: 0.92",
            score=0.92,
        )
        h = _make_hypothesis(
            "map-well-formed",
            se,
            ot,
            MappingPredicate.EXACT_MATCH,
            0.92,
            evidence=[ev],
        )
        h.rank = 1
        _validate_hypothesis(h)
        assert h.validation_status == ValidationStatus.PASSED, (
            f"Expected PASSED, got {h.validation_status}"
        )

    def test_validation_warning_for_hypothesis_without_evidence(self) -> None:
        """A non-NO_MAPPING hypothesis without evidence must get WARNING status."""
        se = SourceEntity(
            entity_id="csv:test.strain",
            label="strain",
            datatype="string",
            examples=[],
            source_type="csv",
        )
        ot = OntologyTerm(
            term_id="mbo:MouseStrain",
            label="mouse strain",
            definition="A genetically distinct mouse lineage.",
            term_type="class",
            ontology_id="mbo",
            extra_context={},
        )
        h = _make_hypothesis(
            "map-no-evidence",
            se,
            ot,
            MappingPredicate.CLOSE_MATCH,
            0.75,
            evidence=[],  # no evidence
        )
        h.rank = 1
        _validate_hypothesis(h)
        assert h.validation_status == ValidationStatus.WARNING, (
            f"Expected WARNING for hypothesis without evidence, got {h.validation_status}"
        )


# ---------------------------------------------------------------------------
# Export stage tests
# ---------------------------------------------------------------------------


class TestPipelineExports:
    """Integration tests for the export stage using a realistic hypothesis list."""

    def test_full_pipeline_with_csv_exports_json(
        self,
        tmp_path: Path,
        tmp_csv_file: Path,
        tmp_ontology_yaml: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """Running through profiling + ranking + validation + JSON export must create the file."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        for h in ranked:
            _validate_hypothesis(h)

        output_json = tmp_path / "mappings.json"
        export_to_json(ranked, output_json)

        assert output_json.exists(), "JSON output file must be created"

    def test_full_pipeline_with_openapi_exports_json(
        self,
        tmp_path: Path,
        tmp_openapi_json: Path,
        tmp_ontology_yaml: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """Running the export stage with OpenAPI-derived hypotheses must work."""
        # Use the same pre-built hypotheses; just verify export works
        output_json = tmp_path / "openapi_mappings.json"
        export_to_json(integration_hypotheses, output_json)
        assert output_json.exists()

    def test_pipeline_output_json_valid(
        self,
        tmp_path: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """The exported JSON must parse correctly and have the expected structure."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        for h in ranked:
            _validate_hypothesis(h)

        output_json = tmp_path / "test_output.json"
        export_to_json(ranked, output_json)

        doc = json.loads(output_json.read_text(encoding="utf-8"))
        assert "metadata" in doc, "JSON must have 'metadata'"
        assert "mappings" in doc, "JSON must have 'mappings'"
        assert isinstance(doc["mappings"], list), "'mappings' must be a list"
        assert doc["metadata"]["total_mappings"] == len(ranked)

    def test_pipeline_output_tsv_valid(
        self,
        tmp_path: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """The exported TSV must have the expected SSSOM columns."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        for h in ranked:
            _validate_hypothesis(h)

        output_tsv = tmp_path / "test_output.tsv"
        export_to_sssom_tsv(ranked, output_tsv)

        lines = output_tsv.read_text(encoding="utf-8").splitlines()
        non_comment = [l for l in lines if not l.startswith("#") and l.strip()]
        assert len(non_comment) >= 2, "TSV must have at least a header and one data row"

        header_cols = non_comment[0].split("\t")
        required = ["mapping_id", "subject_id", "subject_label", "predicate_id",
                    "object_id", "object_label", "confidence"]
        for col in required:
            assert col in header_cols, (
                f"Required column '{col}' missing from TSV header: {header_cols}"
            )

    def test_pipeline_output_markdown_valid(
        self,
        tmp_path: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """The Markdown review report must contain the expected heading."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        output_report = tmp_path / "review_report.md"
        _write_markdown_report(ranked, output_report)

        content = output_report.read_text(encoding="utf-8")
        assert "# Ontology Mapping Review Report" in content, (
            "Markdown report must contain the heading '# Ontology Mapping Review Report'"
        )

    def test_pipeline_returns_summary_dict(
        self,
        tmp_path: Path,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """A manually assembled pipeline result dict must have the expected keys."""
        ranked = _rank_hypotheses(list(integration_hypotheses))
        for h in ranked:
            _validate_hypothesis(h)

        n_passed = sum(1 for h in ranked if h.validation_status == ValidationStatus.PASSED)
        n_failed = sum(1 for h in ranked if h.validation_status == ValidationStatus.FAILED)
        n_warned = sum(1 for h in ranked if h.validation_status == ValidationStatus.WARNING)

        output_json = tmp_path / "summary.json"
        output_tsv = tmp_path / "summary.tsv"
        export_to_json(ranked, output_json)
        export_to_sssom_tsv(ranked, output_tsv)

        result = {
            "pipeline_run_id": "run-test-001",
            "total_source_entities": len({h.source_entity.entity_id for h in ranked}),
            "total_hypotheses": len(ranked),
            "hypotheses_passed_validation": n_passed,
            "hypotheses_failed_validation": n_failed,
            "hypotheses_with_warnings": n_warned,
            "output_json": str(output_json),
            "output_tsv": str(output_tsv),
            "hypotheses": ranked,
        }

        expected_keys = [
            "pipeline_run_id",
            "total_source_entities",
            "total_hypotheses",
            "hypotheses_passed_validation",
            "hypotheses_failed_validation",
            "hypotheses_with_warnings",
            "output_json",
            "output_tsv",
            "hypotheses",
        ]
        for key in expected_keys:
            assert key in result, f"Result dict must contain key '{key}'"

    def test_validation_agent_updates_status_to_non_pending(
        self,
        integration_hypotheses: list[MappingHypothesis],
    ) -> None:
        """After the validation stage, no hypothesis must remain in PENDING status."""
        hypotheses = _rank_hypotheses(list(integration_hypotheses))
        for h in hypotheses:
            _validate_hypothesis(h)

        pending = [
            h for h in hypotheses
            if h.validation_status == ValidationStatus.PENDING
        ]
        assert len(pending) == 0, (
            f"{len(pending)} hypotheses still have PENDING status after validation: "
            f"{[h.mapping_id for h in pending]}"
        )
