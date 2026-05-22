"""Confirms that schema-align never emits ontology predicates or SSSOM output by default."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation
from mapping_co_scientist.schema_align.exporters.generic_mapping_exporter import export_mapping_spec
from mapping_co_scientist.schema_align.exporters.transformation_spec_exporter import export_transformation_rules
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import TransformationRule
from mapping_co_scientist.shared.models.evidence import Provenance

NOW = "2024-01-01T00:00:00"
PROV = Provenance(created_by="test", created_at=NOW, method="test_v1")

SKOS_TERMS = ["skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch", "skos:relatedMatch"]
OWL_TERMS = ["owl:equivalentClass", "owl:equivalentProperty", "rdfs:subClassOf"]
SSSOM_HEADERS = ["mapping_set_id", "predicate_id", "mapping_justification"]


def make_hyp(operation: MappingOperation = MappingOperation.DIRECT_COPY) -> FieldMappingHypothesis:
    return FieldMappingHypothesis(
        mapping_id="test-no-onto",
        source_path="MouseID",
        target_path="animal.externalId",
        mapping_operation=operation,
        confidence=0.80,
        source_datatype="string",
        target_datatype="string",
        provenance=PROV,
    )


class TestNoOntologyPredicates:
    """Verify that schema-align output is free of ontology semantics."""

    def test_mapping_spec_yaml_no_skos(self, tmp_path):
        hyps = [make_hyp()]
        out = tmp_path / "mapping_spec.yaml"
        export_mapping_spec(hyps, out)
        content = out.read_text(encoding="utf-8")
        for term in SKOS_TERMS + OWL_TERMS:
            assert term not in content, f"Found ontology term '{term}' in schema mapping spec"

    def test_mapping_spec_yaml_no_sssom_headers(self, tmp_path):
        hyps = [make_hyp()]
        out = tmp_path / "mapping_spec.yaml"
        export_mapping_spec(hyps, out)
        content = out.read_text(encoding="utf-8")
        for header in SSSOM_HEADERS:
            assert header not in content, f"Found SSSOM header '{header}' in schema mapping spec"

    def test_transformation_rules_json_no_skos(self, tmp_path):
        rules = [TransformationRule(
            rule_id="r001",
            source_path="MouseID",
            target_path="animal.externalId",
            operation=MappingOperation.DIRECT_COPY,
        )]
        out = tmp_path / "rules.json"
        export_transformation_rules(rules, out)
        content = out.read_text(encoding="utf-8")
        for term in SKOS_TERMS + OWL_TERMS:
            assert term not in content, f"Found ontology term '{term}' in transformation rules"

    def test_schema_align_pipeline_no_sssom_output(self, tmp_path):
        """End-to-end: schema pipeline must not create a .sssom.tsv file."""
        source = tmp_path / "source.csv"
        source.write_text("MouseID,Sex\nA001,M\nA002,F\n")
        schema = tmp_path / "target.json"
        schema.write_text("""{
            "type": "object",
            "properties": {
                "externalId": {"type": "string"},
                "sex": {"type": "string"}
            }
        }""")
        output_dir = tmp_path / "out"

        from mapping_co_scientist.schema_align.pipeline import run_schema_alignment_pipeline
        summary = run_schema_alignment_pipeline(
            source_path=source,
            target_schema_path=schema,
            output_dir=output_dir,
        )

        # Check no SSSOM file created
        sssom_files = list(output_dir.glob("*.sssom.tsv"))
        assert not sssom_files, f"schema-align must not create SSSOM files: {sssom_files}"

        # Check outputs directory
        assert output_dir.exists()
        assert (output_dir / "field_mapping_candidates.json").exists()

    def test_schema_model_has_no_ontology_relation_field(self):
        """FieldMappingHypothesis must not have an ontology_relation field."""
        hyp = make_hyp()
        assert not hasattr(hyp, "ontology_relation"), (
            "FieldMappingHypothesis must not have an ontology_relation field"
        )
        assert not hasattr(hyp, "predicate"), (
            "FieldMappingHypothesis must not have a 'predicate' field (use mapping_operation)"
        )

    def test_mapping_operations_are_schema_concepts(self):
        """All MappingOperation values must be schema transformation concepts, not ontology predicates."""
        for op in MappingOperation:
            assert not op.startswith("skos:"), f"MappingOperation '{op}' looks like a SKOS predicate"
            assert not op.startswith("owl:"), f"MappingOperation '{op}' looks like an OWL predicate"
            assert not op.startswith("rdfs:"), f"MappingOperation '{op}' looks like an RDFS predicate"
