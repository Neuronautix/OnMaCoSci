#!/usr/bin/env python3
"""Run the schema alignment example: map preclinical CSV to MetadatApp import schema."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from mapping_co_scientist.schema_align.pipeline import run_schema_alignment_pipeline

SOURCE = REPO_ROOT / "examples" / "schema_align" / "inputs" / "source_animal_records.csv"
TARGET = REPO_ROOT / "examples" / "schema_align" / "inputs" / "metadatapp_import_schema.json"
OUTPUT_DIR = REPO_ROOT / "examples" / "schema_align" / "outputs"


def main() -> None:
    print("=" * 60)
    print("Schema Alignment Example")
    print("=" * 60)
    print(f"Source CSV:    {SOURCE}")
    print(f"Target Schema: {TARGET}")
    print(f"Output:        {OUTPUT_DIR}")
    print()

    summary = run_schema_alignment_pipeline(
        source_path=SOURCE,
        target_schema_path=TARGET,
        output_dir=OUTPUT_DIR,
        pipeline_run_id="example-sa-001",
        top_k=3,
        verbose=True,
    )

    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)
    print(f"Source fields:        {summary['source_fields']}")
    print(f"Target fields:        {summary['target_fields']}")
    print(f"Hypotheses generated: {summary['hypotheses_generated']}")
    print(f"Transformation rules: {summary['transformation_rules']}")
    print(f"Unmapped fields:      {summary['unmapped_fields']}")
    print(f"Coverage:             {summary['coverage_pct']}%")
    print()
    print("Output files:")
    for key, path in summary["outputs"].items():
        print(f"  {key:30s} {path}")

    print()
    print("Inspect first:")
    print("  1. approved_mapping_spec.yaml — machine-readable mapping specification")
    print("  2. transformation_validation_report.md — human review report with flags")
    print("  3. information_loss_report.md — detected data loss")

    print()
    print("Key behaviours to observe:")
    print("  - Weight_g → measurements.bodyWeight.value (nested_path)")
    print("  - measurements.bodyWeight.unit = 'g' (constant_assignment from column suffix)")
    print("  - RecordingDate → measurements.activity.date (rename + nested)")
    print("  - ActivityCount flagged as ambiguous measurement")
    print("  - No SSSOM file created (schema-align is not an ontology tool)")


if __name__ == "__main__":
    main()
