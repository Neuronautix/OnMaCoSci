"""Tests for SSSOM-like export from ontology-align."""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

import pytest

from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.shared.models.evidence import Provenance
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis,
    OntologyRelation,
)
from mapping_co_scientist.ontology_align.exporters.sssom_exporter import export_sssom, SSSOM_COLUMNS


NOW = "2024-01-01T00:00:00"


def make_hyp(
    source_label: str,
    target_id: str,
    target_label: str,
    relation: OntologyRelation = OntologyRelation.CLOSE_MATCH,
    confidence: float = 0.80,
) -> OntologyMappingHypothesis:
    return OntologyMappingHypothesis(
        mapping_id=f"map-{source_label}-{target_id}".replace(":", "_"),
        source_concept=SourceEntity(
            entity_id=f"csv:{source_label}",
            label=source_label,
            source_type="csv",
        ),
        target_ontology_entity=OntologyTerm(
            term_id=target_id,
            label=target_label,
            term_type="class",
            ontology_id="hcm",
        ),
        ontology_relation=relation,
        confidence=confidence,
        source_entity_type="field",
        target_entity_type="class",
        semantic_scope_analysis="test",
        hierarchy_compatibility="unknown",
        domain_range_compatibility="unknown",
        provenance=Provenance(
            created_by="test",
            created_at=NOW,
            method="test_v1",
        ),
    )


class TestSSSOMExport:
    def test_exports_tsv_file(self, tmp_path):
        hyps = [
            make_hyp("strain", "hcm:GeneticBackground", "GeneticBackground", OntologyRelation.NARROW_MATCH),
            make_hyp("sex", "hcm:BiologicalSex", "BiologicalSex", OntologyRelation.CLOSE_MATCH),
        ]
        out = tmp_path / "test.sssom.tsv"
        export_sssom(hyps, out)
        assert out.exists()

    def test_sssom_has_metadata_header(self, tmp_path):
        hyps = [make_hyp("strain", "hcm:GeneticBackground", "GeneticBackground")]
        out = tmp_path / "test.sssom.tsv"
        export_sssom(hyps, out, pipeline_run_id="test-run-001")
        content = out.read_text(encoding="utf-8")
        assert "# mapping_set_id" in content
        assert "# mapping_date" in content
        assert "# license" in content

    def test_sssom_columns_present(self, tmp_path):
        hyps = [make_hyp("strain", "hcm:GeneticBackground", "GeneticBackground")]
        out = tmp_path / "test.sssom.tsv"
        export_sssom(hyps, out)
        content = out.read_text(encoding="utf-8")
        # Strip comment lines
        data_lines = [l for l in content.splitlines() if not l.startswith("#") and l.strip()]
        assert data_lines, "No data rows found"
        header = data_lines[0].split("\t")
        for col in ["subject_id", "predicate_id", "object_id", "confidence"]:
            assert col in header, f"Missing SSSOM column: {col}"

    def test_sssom_predicate_correct(self, tmp_path):
        hyps = [make_hyp("strain", "hcm:GeneticBackground", "GeneticBackground", OntologyRelation.NARROW_MATCH)]
        out = tmp_path / "test.sssom.tsv"
        export_sssom(hyps, out)
        content = out.read_text(encoding="utf-8")
        data_lines = [l for l in content.splitlines() if not l.startswith("#") and l.strip()]
        reader = csv.DictReader(data_lines, delimiter="\t")
        rows = list(reader)
        assert rows
        assert rows[0]["predicate_id"] == "skos:narrowMatch"

    def test_sssom_no_exactmatch_default(self, tmp_path):
        """By default, lexical pipeline should not produce exactMatch predicate in SSSOM data rows."""
        from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import (
            SemanticCandidateGeneratorAgent,
        )
        from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
        from mapping_co_scientist.shared.models.source_entity import SourceEntity

        source = [SourceEntity(entity_id="csv:sex", label="sex", source_type="csv")]
        targets = [OntologyTerm(
            term_id="hcm:BiologicalSex", label="sex",
            term_type="class", ontology_id="hcm"
        )]
        gen = SemanticCandidateGeneratorAgent(top_k=3)
        hyps = gen.generate(source, targets)

        out = tmp_path / "no_exact.sssom.tsv"
        export_sssom(hyps, out)
        content = out.read_text(encoding="utf-8")

        # Check the predicate_id column in data rows — not comments (warnings may mention exactMatch)
        data_lines = [l for l in content.splitlines() if not l.startswith("#") and l.strip()]
        reader = csv.DictReader(data_lines, delimiter="\t")
        for row in reader:
            assert row.get("predicate_id") != "skos:exactMatch", (
                "Lexical pipeline must not produce exactMatch predicate in SSSOM data rows"
            )

    def test_warnings_captured_in_comment(self, tmp_path):
        from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import SemanticWarning
        hyp = make_hyp("strain", "hcm:GeneticBackground", "GeneticBackground")
        hyp.semantic_warnings.append(SemanticWarning(
            warning_type="scope_mismatch",
            description="strain is narrower than GeneticBackground",
            severity="warning",
        ))
        out = tmp_path / "with_warnings.sssom.tsv"
        export_sssom([hyp], out)
        content = out.read_text(encoding="utf-8")
        assert "scope_mismatch" in content
