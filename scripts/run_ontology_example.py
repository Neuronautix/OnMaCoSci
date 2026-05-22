#!/usr/bin/env python3
"""Run the ontology alignment example using the preclinical mouse metadata domain."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from mapping_co_scientist.ontology_align.pipeline import run_ontology_alignment_pipeline

SOURCE = REPO_ROOT / "examples" / "ontology_align" / "inputs" / "animal_fields.csv"
ONTOLOGY = REPO_ROOT / "examples" / "ontology_align" / "inputs" / "hcm_profile.yaml"
OUTPUT_DIR = REPO_ROOT / "examples" / "ontology_align" / "outputs"


def main() -> None:
    print("=" * 60)
    print("Ontology Alignment Example")
    print("=" * 60)
    print(f"Source:   {SOURCE}")
    print(f"Ontology: {ONTOLOGY}")
    print(f"Output:   {OUTPUT_DIR}")
    print()

    summary = run_ontology_alignment_pipeline(
        source_path=SOURCE,
        ontology_path=ONTOLOGY,
        output_dir=OUTPUT_DIR,
        pipeline_run_id="example-oa-001",
        top_k=3,
        verbose=True,
    )

    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)
    print(f"Source entities:      {summary['source_entities']}")
    print(f"Ontology terms:       {summary['ontology_terms']}")
    print(f"Hypotheses generated: {summary['hypotheses_generated']}")
    print(f"Term gaps identified: {summary['term_gaps_identified']}")
    print()
    print("Output files:")
    for key, path in summary["outputs"].items():
        print(f"  {key:35s} {path}")

    print()
    print("Inspect first:")
    print("  1. ontology_review_report.md — human-readable review with warnings")
    print("  2. ontology_mapping_candidates.sssom.tsv — SSSOM-compatible export")
    print("  3. term_gap_proposals.json — unmapped concepts needing new terms")

    print()
    print("Key behaviours to observe:")
    print("  - strain → GeneticBackground uses narrowMatch (not exactMatch)")
    print("  - No exactMatch is auto-assigned from lexical similarity alone")
    print("  - High-scoring pairs get semantic warnings flagged for review")
    print("  - locomotor_activity_index may have no suitable ontology term")


if __name__ == "__main__":
    main()
