"""CLI for schema alignment tool."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="schema-align",
        description="Align fields between two operational schemas.",
    )
    parser.add_argument("--source", required=True, type=Path, help="Source CSV or JSON file")
    parser.add_argument("--target-schema", required=True, type=Path, help="Target JSON Schema or OpenAPI file")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    parser.add_argument("--top-k", type=int, default=3, help="Max candidates per source field")
    parser.add_argument("--run-id", type=str, default=None, help="Pipeline run ID")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args(argv)

    from mapping_co_scientist.schema_align.pipeline import run_schema_alignment_pipeline

    try:
        summary = run_schema_alignment_pipeline(
            source_path=args.source,
            target_schema_path=args.target_schema,
            output_dir=args.output_dir,
            pipeline_run_id=args.run_id,
            top_k=args.top_k,
            verbose=args.verbose,
        )
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
