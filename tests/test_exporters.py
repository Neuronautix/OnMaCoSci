"""Tests for the JSON and SSSOM-TSV exporter functions.

These tests exercise the real exporter code against in-memory fixtures.
They verify file creation, content structure, required column names, and
round-trip consistency — without mocking the file system.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_provenance() -> Provenance:
    """Return a deterministic Provenance for tests."""
    return Provenance(
        created_by="TestAgent",
        created_at="2025-03-15T14:22:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="run-exporter-test",
    )


def _make_hypothesis(
    mapping_id: str,
    source_label: str,
    target_label: str,
    predicate: MappingPredicate = MappingPredicate.CLOSE_MATCH,
    confidence: float = 0.80,
    entity_id: str | None = None,
    term_id: str | None = None,
) -> MappingHypothesis:
    """Construct a minimal but valid MappingHypothesis for exporter tests."""
    safe_label = source_label.lower().replace(" ", "_")
    source = SourceEntity(
        entity_id=entity_id or f"csv:test.{safe_label}",
        label=source_label,
        datatype="string",
        examples=["example_value"],
        source_type="csv",
    )
    target = OntologyTerm(
        term_id=term_id or f"mbo:{target_label.replace(' ', '')}",
        label=target_label,
        definition=f"Definition of {target_label}.",
        synonyms=[],
        term_type="class",
        ontology_id="mbo",
        extra_context={},
    )
    evidence = [
        Evidence(
            evidence_type="lexical_similarity",
            description=f"Lexical similarity between '{source_label}' and '{target_label}'",
            score=confidence,
        )
    ]
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source,
        target_entity=target,
        predicate=predicate,
        confidence=confidence,
        evidence=evidence,
        validation_status=ValidationStatus.PASSED,
        human_review_status=HumanReviewStatus.AWAITING_REVIEW,
        provenance=_make_provenance(),
        rank=1,
    )


@pytest.fixture
def sample_hypotheses() -> list[MappingHypothesis]:
    """Return a list of three realistic MappingHypothesis objects for exporter tests."""
    return [
        _make_hypothesis(
            "map-001",
            "strain",
            "mouse strain",
            MappingPredicate.EXACT_MATCH,
            0.92,
            entity_id="csv:animal.strain",
            term_id="mbo:MouseStrain",
        ),
        _make_hypothesis(
            "map-002",
            "sex",
            "biological sex",
            MappingPredicate.CLOSE_MATCH,
            0.78,
            entity_id="csv:animal.sex",
            term_id="mbo:BiologicalSex",
        ),
        _make_hypothesis(
            "map-003",
            "age_weeks",
            "age at measurement",
            MappingPredicate.BROAD_MATCH,
            0.62,
            entity_id="csv:animal.age_weeks",
            term_id="mbo:AgeAtMeasurement",
        ),
    ]


# ---------------------------------------------------------------------------
# JSON exporter tests
# ---------------------------------------------------------------------------


class TestExportToJson:
    """Tests for the export_to_json function."""

    def test_export_to_json_creates_file(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """export_to_json must create the output file at the specified path."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        assert output_path.exists(), f"Output file was not created at {output_path}"
        assert output_path.is_file(), "Output path must be a regular file"

    def test_export_to_json_file_is_valid_json(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The exported file must be valid JSON that can be parsed without errors."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        doc = json.loads(content)  # must not raise
        assert isinstance(doc, dict)

    def test_export_to_json_has_metadata_and_mappings_keys(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The top-level JSON document must contain 'metadata' and 'mappings' keys."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        assert "metadata" in doc, "JSON output must have a 'metadata' key"
        assert "mappings" in doc, "JSON output must have a 'mappings' key"

    def test_export_to_json_metadata_fields(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """metadata must contain generated_at, total_mappings, and pipeline_version."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        metadata = doc["metadata"]
        assert "generated_at" in metadata, "metadata must have 'generated_at'"
        assert "total_mappings" in metadata, "metadata must have 'total_mappings'"
        assert "pipeline_version" in metadata, "metadata must have 'pipeline_version'"

    def test_export_to_json_total_mappings_matches_input(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """metadata.total_mappings must equal the number of hypotheses exported."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        assert doc["metadata"]["total_mappings"] == len(sample_hypotheses), (
            f"Expected total_mappings={len(sample_hypotheses)}, "
            f"got {doc['metadata']['total_mappings']}"
        )

    def test_export_to_json_mappings_count_matches_input(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The 'mappings' array must contain one entry per input hypothesis."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(doc["mappings"]) == len(sample_hypotheses), (
            f"Expected {len(sample_hypotheses)} mappings, got {len(doc['mappings'])}"
        )

    def test_export_to_json_mapping_ids_preserved(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each serialised mapping must preserve its mapping_id."""
        output_path = tmp_path / "mappings.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        exported_ids = {m["mapping_id"] for m in doc["mappings"]}
        original_ids = {h.mapping_id for h in sample_hypotheses}
        assert exported_ids == original_ids, (
            f"Exported mapping_ids {exported_ids} != original {original_ids}"
        )

    def test_export_to_json_empty_list_produces_empty_mappings(
        self, tmp_path: Path
    ) -> None:
        """Exporting an empty list must produce a valid JSON with an empty mappings array."""
        output_path = tmp_path / "empty.json"
        export_to_json([], output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        assert doc["mappings"] == [], "Empty export must produce an empty 'mappings' array"
        assert doc["metadata"]["total_mappings"] == 0

    def test_export_roundtrip_mapping_ids_match(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Exporting then reading back must yield the same set of mapping_ids."""
        output_path = tmp_path / "roundtrip.json"
        export_to_json(sample_hypotheses, output_path)

        doc = json.loads(output_path.read_text(encoding="utf-8"))
        read_back_ids = [m["mapping_id"] for m in doc["mappings"]]
        original_ids = [h.mapping_id for h in sample_hypotheses]
        assert sorted(read_back_ids) == sorted(original_ids), (
            "Round-trip must preserve all mapping_ids"
        )


# ---------------------------------------------------------------------------
# SSSOM TSV exporter tests
# ---------------------------------------------------------------------------


class TestExportToSssomTsv:
    """Tests for the export_to_sssom_tsv function."""

    def test_export_to_sssom_tsv_creates_file(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """export_to_sssom_tsv must create the output TSV file."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        assert output_path.exists(), f"Output TSV file was not created at {output_path}"
        assert output_path.is_file()

    def test_export_to_sssom_tsv_first_non_comment_line_is_header(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The first non-comment line must be the column header row."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        header_line = next(line for line in lines if not line.startswith("#"))
        columns = header_line.split("\t")

        assert len(columns) > 1, "Header must contain tab-separated column names"
        # Check that common SSSOM column names are present
        assert "mapping_id" in columns, "Header must contain 'mapping_id'"
        assert "subject_id" in columns, "Header must contain 'subject_id'"

    def test_export_to_sssom_tsv_required_columns_present(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """All required SSSOM columns must be present in the header."""
        required = [
            "mapping_id",
            "subject_id",
            "subject_label",
            "predicate_id",
            "object_id",
            "object_label",
            "confidence",
        ]
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        header_line = next(line for line in lines if not line.startswith("#"))
        columns = header_line.split("\t")

        for col in required:
            assert col in columns, (
                f"Required SSSOM column '{col}' not found in header; "
                f"available columns: {columns}"
            )

    def test_export_to_sssom_tsv_row_count_matches_hypotheses(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Number of data rows must equal the number of exported hypotheses."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        # Skip comment lines and the header
        data_lines = [
            line for line in lines
            if line.strip() and not line.startswith("#")
        ]
        # First data_line is the header; remaining are data rows
        data_rows = data_lines[1:]
        assert len(data_rows) == len(sample_hypotheses), (
            f"Expected {len(sample_hypotheses)} data rows, got {len(data_rows)}"
        )

    def test_export_to_sssom_tsv_contains_comment_header(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The TSV file must begin with comment lines (lines starting with '#')."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert content.startswith("#"), (
            "SSSOM TSV file must start with comment lines beginning with '#'"
        )

    def test_export_to_sssom_tsv_mapping_ids_in_rows(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each data row must contain the corresponding mapping_id."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        for h in sample_hypotheses:
            assert h.mapping_id in content, (
                f"mapping_id {h.mapping_id!r} not found in TSV output"
            )

    def test_export_to_sssom_tsv_subject_labels_in_rows(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each data row must contain the source entity label as subject_label."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        for h in sample_hypotheses:
            assert h.source_entity.label in content, (
                f"source entity label {h.source_entity.label!r} not found in TSV"
            )

    def test_export_to_sssom_tsv_confidence_values_present(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """Each data row must contain the hypothesis confidence as a decimal string."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment_lines = [l for l in lines if not l.startswith("#") and l.strip()]
        header = non_comment_lines[0].split("\t")
        conf_idx = header.index("confidence")

        for i, data_line in enumerate(non_comment_lines[1:]):
            cols = data_line.split("\t")
            conf_str = cols[conf_idx]
            # Must be parseable as a float
            conf_val = float(conf_str)
            assert 0.0 <= conf_val <= 1.0, (
                f"Row {i + 1}: confidence={conf_str!r} is outside [0.0, 1.0]"
            )

    def test_sssom_columns_subject_id_contains_source_entity_ids(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """subject_id column values must match the source_entity.entity_id of each hypothesis."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment_lines = [l for l in lines if not l.startswith("#") and l.strip()]
        header = non_comment_lines[0].split("\t")
        subj_idx = header.index("subject_id")

        exported_subject_ids = [
            line.split("\t")[subj_idx] for line in non_comment_lines[1:]
        ]
        expected_subject_ids = [h.source_entity.entity_id for h in sample_hypotheses]

        assert sorted(exported_subject_ids) == sorted(expected_subject_ids), (
            "subject_id values must match source_entity.entity_id of each hypothesis"
        )

    def test_sssom_columns_object_id_contains_term_ids(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """object_id column values must match the target_entity.term_id of each hypothesis."""
        output_path = tmp_path / "mappings.tsv"
        export_to_sssom_tsv(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment_lines = [l for l in lines if not l.startswith("#") and l.strip()]
        header = non_comment_lines[0].split("\t")
        obj_idx = header.index("object_id")

        exported_object_ids = [
            line.split("\t")[obj_idx] for line in non_comment_lines[1:]
        ]
        expected_object_ids = [h.target_entity.term_id for h in sample_hypotheses]

        assert sorted(exported_object_ids) == sorted(expected_object_ids), (
            "object_id values must match target_entity.term_id of each hypothesis"
        )


# ---------------------------------------------------------------------------
# SSSOM-compliant exporter tests
# ---------------------------------------------------------------------------


class TestExportToSssomCompliant:
    """Tests for the export_to_sssom_compliant / sssom_exporter.export_to_sssom function."""

    def test_sssom_compliant_creates_file(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """export_to_sssom_compliant must create the output file at the specified path."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        output_path = tmp_path / "compliant.tsv"
        export_to_sssom_compliant(sample_hypotheses, output_path)

        assert output_path.exists(), f"Output file was not created at {output_path}"
        assert output_path.is_file()

    def test_sssom_compliant_has_yaml_header(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The output must contain the SSSOM YAML metadata header line."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        output_path = tmp_path / "compliant.tsv"
        export_to_sssom_compliant(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "# mapping_set_id:" in content, (
            "SSSOM-compliant output must contain '# mapping_set_id:' in YAML header"
        )

    def test_sssom_compliant_has_curie_map(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The output must contain a curie_map section in the YAML header."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        output_path = tmp_path / "compliant.tsv"
        export_to_sssom_compliant(sample_hypotheses, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "# curie_map:" in content, (
            "SSSOM-compliant output must contain '# curie_map:' in YAML header"
        )

    def test_sssom_compliant_predicate_is_full_uri(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The predicate_id column must contain full http:// URIs, not CURIEs."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        output_path = tmp_path / "compliant.tsv"
        export_to_sssom_compliant(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment = [l for l in lines if not l.startswith("#") and l.strip()]
        header = non_comment[0].split("\t")
        pred_idx = header.index("predicate_id")

        for data_line in non_comment[1:]:
            cols = data_line.split("\t")
            predicate_val = cols[pred_idx]
            assert predicate_val.startswith("http://") or predicate_val.startswith("https://"), (
                f"predicate_id must be a full URI, got: {predicate_val!r}"
            )

    def test_sssom_compliant_justification_semapv(
        self, tmp_path: Path, sample_hypotheses: list[MappingHypothesis]
    ) -> None:
        """The mapping_justification column values must start with 'semapv:'."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        output_path = tmp_path / "compliant.tsv"
        export_to_sssom_compliant(sample_hypotheses, output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment = [l for l in lines if not l.startswith("#") and l.strip()]
        header = non_comment[0].split("\t")
        just_idx = header.index("mapping_justification")

        for data_line in non_comment[1:]:
            cols = data_line.split("\t")
            justification = cols[just_idx]
            assert justification.startswith("semapv:"), (
                f"mapping_justification must start with 'semapv:', got: {justification!r}"
            )

    def test_sssom_compliant_excludes_no_mapping_by_default(
        self, tmp_path: Path
    ) -> None:
        """Hypotheses with NO_MAPPING predicate must be excluded by default."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        no_map_hyp = _make_hypothesis(
            "map-nomapping",
            "unmappable_field",
            "NoTerm",
            predicate=MappingPredicate.NO_MAPPING,
            confidence=0.10,
            entity_id="csv:test.unmappable",
            term_id="custom:noTerm",
        )
        normal_hyp = _make_hypothesis(
            "map-normal",
            "strain",
            "mouse strain",
            predicate=MappingPredicate.EXACT_MATCH,
            confidence=0.90,
            entity_id="csv:test.strain",
            term_id="mbo:MouseStrain",
        )

        output_path = tmp_path / "compliant_no_map.tsv"
        export_to_sssom_compliant([no_map_hyp, normal_hyp], output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "unmappable_field" not in content, (
            "NO_MAPPING hypothesis must not appear in output by default"
        )
        assert "strain" in content, (
            "Normal hypothesis must still appear in output"
        )

    def test_sssom_compliant_only_top_ranked(
        self, tmp_path: Path
    ) -> None:
        """When hypotheses have rank set, only rank=1 per subject_id must appear."""
        from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

        rank1 = _make_hypothesis(
            "map-rank1",
            "strain",
            "mouse strain",
            predicate=MappingPredicate.EXACT_MATCH,
            confidence=0.92,
            entity_id="csv:test.strain",
            term_id="mbo:MouseStrain",
        )
        rank1.rank = 1

        rank2 = _make_hypothesis(
            "map-rank2",
            "strain",
            "genetic background",
            predicate=MappingPredicate.CLOSE_MATCH,
            confidence=0.75,
            entity_id="csv:test.strain",
            term_id="mbo:GeneticBackground",
        )
        rank2.rank = 2

        output_path = tmp_path / "compliant_ranked.tsv"
        export_to_sssom_compliant([rank1, rank2], output_path)

        lines = output_path.read_text(encoding="utf-8").splitlines()
        non_comment = [l for l in lines if not l.startswith("#") and l.strip()]
        # Header + exactly 1 data row
        data_rows = non_comment[1:]
        assert len(data_rows) == 1, (
            f"Expected exactly 1 data row (rank=1 only), got {len(data_rows)}"
        )
        # The kept row must be for "mouse strain" (rank=1)
        assert "mouse strain" in data_rows[0], (
            "The exported row must be the rank=1 hypothesis"
        )
        assert "genetic background" not in data_rows[0], (
            "The rank=2 hypothesis must not appear in the output"
        )
