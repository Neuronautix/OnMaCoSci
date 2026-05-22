"""Example pipeline runner script for the Ontology Mapping Co-Scientist system.

This script demonstrates two complete pipeline runs:

1.  **OpenAPI source** — maps properties from ``animal_api_sample.json``
    (an OpenAPI schema describing animal research data) against the HCM
    mouse ontology profile.

2.  **CSV source** — maps columns from ``animal_data_sample.csv`` against
    the same ontology profile.

Run from the repository root::

    python scripts/run_example.py

Or make it executable::

    chmod +x scripts/run_example.py
    ./scripts/run_example.py

Both runs write their output files to ``examples/outputs/``.  Each run
produces three files:
- ``<stem>_<timestamp>_mappings.json``  — full hypothesis data
- ``<stem>_<timestamp>_sssom.tsv``      — SSSOM-inspired export
- ``<stem>_<timestamp>_review_report.md`` — human review report

IMPORTANT
---------
The outputs are **hypotheses**, not final mappings.  They must be reviewed
by a domain scientist before any operational use.
"""

import sys
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the src/ package is importable when running from the repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.pipeline.run_mapping_pipeline import run_pipeline  # noqa: E402


def _print_result_summary(result: dict, label: str) -> None:
    """Print a formatted summary of one pipeline run result.

    Args:
        result: The dict returned by :func:`run_pipeline`.
        label: A short human-readable label for this run (e.g. "OpenAPI run").
    """
    print()
    print(f"  [{label}] completed successfully")
    print(f"    Source entities     : {result['total_source_entities']}")
    print(f"    Ontology terms      : {result['total_ontology_terms']}")
    print(f"    Hypotheses generated: {result['total_hypotheses']}")
    print(f"    Validation passed   : {result['hypotheses_passed_validation']}")
    print(f"    Validation failed   : {result['hypotheses_failed_validation']}")
    print(f"    Validation warnings : {result['hypotheses_with_warnings']}")
    print()
    print("    Output files:")
    print(f"      JSON   : {result['output_json']}")
    if result["output_tsv"]:
        print(f"      TSV    : {result['output_tsv']}")
    print(f"      Report : {result['output_report']}")
    if result.get("output_review_queue"):
        print(f"      Review : {result['output_review_queue']}")


def main() -> None:
    """Run both example pipeline passes and report results."""

    # Determine paths relative to this script so the script works from any cwd
    base_dir = Path(__file__).parent.parent.resolve()
    output_dir = base_dir / "examples" / "outputs"

    print()
    print("=" * 70)
    print("  Ontology Mapping Co-Scientist — Example Runner")
    print("=" * 70)
    print()
    print(f"  Repository root : {base_dir}")
    print(f"  Output dir      : {output_dir}")
    print()

    # ------------------------------------------------------------------ #
    # Run 1: OpenAPI source                                               #
    # ------------------------------------------------------------------ #
    openapi_source = base_dir / "examples" / "source_openapi" / "animal_api_sample.json"
    ontology_profile = base_dir / "examples" / "ontology_profiles" / "hcm_mouse_profile.yaml"

    if not openapi_source.exists():
        print(
            f"  WARNING: OpenAPI example file not found: {openapi_source}\n"
            "  Skipping OpenAPI run.  Create the file to enable this example."
        )
        result_openapi = None
    elif not ontology_profile.exists():
        print(
            f"  WARNING: Ontology profile not found: {ontology_profile}\n"
            "  Skipping OpenAPI run.  Create the file to enable this example."
        )
        result_openapi = None
    else:
        print("  [1/2] Running pipeline: OpenAPI source ...")
        try:
            result_openapi = run_pipeline(
                source_filepath=openapi_source,
                ontology_filepath=ontology_profile,
                output_dir=output_dir,
                pipeline_run_id="example-openapi-run-001",
                verbose=True,
            )
            _print_result_summary(result_openapi, "OpenAPI run")
        except Exception as exc:
            print(f"  ERROR in OpenAPI run: {exc}")
            logging.exception("OpenAPI pipeline run failed")
            result_openapi = None

    # ------------------------------------------------------------------ #
    # Run 2: CSV source                                                   #
    # ------------------------------------------------------------------ #
    csv_source = base_dir / "examples" / "source_csv" / "animal_metadata.csv"

    if not csv_source.exists():
        print(
            f"  WARNING: CSV example file not found: {csv_source}\n"
            "  Skipping CSV run.  Create the file to enable this example."
        )
        result_csv = None
    elif not ontology_profile.exists():
        print(
            f"  WARNING: Ontology profile not found: {ontology_profile}\n"
            "  Skipping CSV run."
        )
        result_csv = None
    else:
        print("  [2/2] Running pipeline: CSV source ...")
        try:
            result_csv = run_pipeline(
                source_filepath=csv_source,
                ontology_filepath=ontology_profile,
                output_dir=output_dir,
                pipeline_run_id="example-csv-run-001",
                verbose=True,
            )
            _print_result_summary(result_csv, "CSV run")
        except Exception as exc:
            print(f"  ERROR in CSV run: {exc}")
            logging.exception("CSV pipeline run failed")
            result_csv = None

    # ------------------------------------------------------------------ #
    # Final summary                                                       #
    # ------------------------------------------------------------------ #
    print()
    print("=" * 70)
    runs_completed = sum(1 for r in [result_openapi, result_csv] if r is not None)
    print(f"  Example runs completed: {runs_completed}/2")

    if runs_completed > 0:
        print(f"  All output files are in: {output_dir}")
        print()
        print("  IMPORTANT: All mappings are HYPOTHESES and require human expert")
        print("  review before use in any production or research context.")
        print("  Use the *_review_queue.json files with omcs-review chat.")
    else:
        print()
        print("  No runs completed.  Check that the example input files exist:")
        print(f"    {openapi_source}")
        print(f"    {csv_source}")
        print(f"    {ontology_profile}")
        print()
        print("  See examples/README guidance in the repository for how to create")
        print("  or obtain sample input files.")

    print("=" * 70)
    print()


if __name__ == "__main__":
    # Configure basic logging so progress messages are visible when the script
    # is run directly.  run_pipeline will also configure logging based on the
    # verbose flag, but this ensures any pre-pipeline messages are captured.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    main()
