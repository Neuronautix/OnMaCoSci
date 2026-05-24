#!/usr/bin/env python3
"""Print a structured review summary from a mapping pipeline output directory.

Usage:
    python scripts/read_run_summary.py <output-dir>

Outputs a compact Markdown summary grouped by source entity/field,
showing the top-1 candidate per source, plus alternatives, adversarial flags,
and review status. Designed to be read by Claude plugin commands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _detect_run_type(output_dir: Path) -> str:
    if (output_dir / "ontology_mapping_candidates.json").exists():
        return "ontology_align"
    if (output_dir / "field_mapping_candidates.json").exists():
        return "schema_align"
    return "unknown"


def _summarise_ontology_run(output_dir: Path) -> str:
    candidates_path = output_dir / "ontology_mapping_candidates.json"
    gaps_path = output_dir / "term_gap_proposals.json"
    sssom_path = output_dir / "ontology_mapping_candidates.sssom.tsv"

    hypotheses: list[dict] = json.loads(candidates_path.read_text(encoding="utf-8"))
    gaps: list[dict] = json.loads(gaps_path.read_text(encoding="utf-8")) if gaps_path.exists() else []

    # Group by source entity
    by_source: dict[str, list[dict]] = {}
    for h in hypotheses:
        key = h["source_concept"]["entity_id"]
        by_source.setdefault(key, []).append(h)

    lines = [
        "## Ontology Alignment Run Summary",
        f"",
        f"- **Output directory**: `{output_dir}`",
        f"- **Run ID**: {hypotheses[0]['provenance']['pipeline_run_id'] if hypotheses else 'unknown'}",
        f"- **Total hypotheses**: {len(hypotheses)}",
        f"- **Source entities**: {len(by_source)}",
        f"- **Term gap proposals**: {len(gaps)}",
        f"- **SSSOM export**: {'present' if sssom_path.exists() else 'missing'}",
        "",
        "---",
        "",
        "### Per-Entity Review Items",
        "",
    ]

    for source_id, hyps in sorted(by_source.items()):
        sorted_hyps = sorted(hyps, key=lambda x: x["confidence"], reverse=True)
        top = sorted_hyps[0]
        source_label = top["source_concept"]["label"]
        target_id = top["target_ontology_entity"]["term_id"]
        target_label = top["target_ontology_entity"]["label"]
        relation = top["ontology_relation"]
        conf = top["confidence"]
        val_status = top["validation_status"]
        review_status = top["human_review_status"]
        warnings = top.get("semantic_warnings", [])
        all_warnings = top.get("warnings", [])

        status_icon = {
            "awaiting_review": "⏳",
            "approved": "✅",
            "rejected": "❌",
            "needs_more_evidence": "🔍",
            "predicate_changed": "✏️",
            "new_term_requested": "🆕",
        }.get(review_status, "?")

        val_icon = {"passed": "✓", "warning": "⚠", "failed": "✗", "pending": "…"}.get(val_status, "?")

        lines.append(f"#### `{source_label}` ({source_id})")
        lines.append(f"")
        lines.append(f"| | |")
        lines.append(f"|---|---|")
        lines.append(f"| **Top mapping** | `{target_id}` ({target_label}) |")
        lines.append(f"| **Relation** | `{relation}` |")
        lines.append(f"| **Confidence** | {conf:.2f} |")
        lines.append(f"| **Validation** | {val_icon} {val_status} |")
        lines.append(f"| **Review status** | {status_icon} {review_status} |")
        lines.append(f"")

        if warnings:
            lines.append("**Semantic warnings:**")
            for w in warnings:
                lines.append(f"- [{w['severity'].upper()}] `{w['warning_type']}`: {w['description']}")
            lines.append("")

        if all_warnings:
            lines.append("**Pipeline warnings:**")
            for w in all_warnings:
                if "[validation]" in w:
                    lines.append(f"- {w}")
            lines.append("")

        if len(sorted_hyps) > 1:
            lines.append("**Alternatives:**")
            for alt in sorted_hyps[1:]:
                alt_target = alt["target_ontology_entity"]["term_id"]
                alt_rel = alt["ontology_relation"]
                alt_conf = alt["confidence"]
                lines.append(f"- `{alt_target}` ({alt_rel}, conf={alt_conf:.2f})")
            lines.append("")

        lines.append("**Human action required**: approve / reject / change-relation / request-evidence / propose-new-term")
        lines.append("")
        lines.append("---")
        lines.append("")

    if gaps:
        lines.append("### Term Gap Proposals")
        lines.append("")
        lines.append("The following source concepts have no suitable ontology mapping:")
        lines.append("")
        for gap in gaps:
            lines.append(f"- **`{gap['source_concept_label']}`** → proposed term: _{gap['proposed_term_label']}_")
            lines.append(f"  - Rationale: {gap['rationale']}")
        lines.append("")

    return "\n".join(lines)


def _summarise_schema_run(output_dir: Path) -> str:
    candidates_path = output_dir / "field_mapping_candidates.json"
    loss_path = output_dir / "information_loss_report.json"

    hypotheses: list[dict] = json.loads(candidates_path.read_text(encoding="utf-8"))
    loss_report: dict = json.loads(loss_path.read_text(encoding="utf-8")) if loss_path.exists() else {}

    # Group by source path (exclude constant-assignment targets which have no source path)
    by_source: dict[str, list[dict]] = {}
    constant_assignments: list[dict] = []
    for h in hypotheses:
        src = h.get("source_path")
        if src is None:
            constant_assignments.append(h)
        else:
            by_source.setdefault(src, []).append(h)

    run_id = hypotheses[0]["provenance"]["pipeline_run_id"] if hypotheses else "unknown"

    lines = [
        "## Schema Alignment Run Summary",
        "",
        f"- **Output directory**: `{output_dir}`",
        f"- **Run ID**: {run_id}",
        f"- **Total hypotheses**: {len(hypotheses)}",
        f"- **Source fields**: {len(by_source)}",
        f"- **Constant assignments**: {len(constant_assignments)}",
        f"- **Coverage**: {loss_report.get('mapped_fields', '?')}/{loss_report.get('total_source_fields', '?')} "
        f"({loss_report.get('mapped_fields', 0) / max(loss_report.get('total_source_fields', 1), 1) * 100:.1f}%)",
        f"- **Unmapped fields**: {loss_report.get('unmapped_fields', '?')}",
        "",
        "---",
        "",
        "### Per-Field Review Items",
        "",
    ]

    for source_path, hyps in sorted(by_source.items()):
        sorted_hyps = sorted(hyps, key=lambda x: x["confidence"], reverse=True)
        top = sorted_hyps[0]
        target_path = top["target_path"]
        operation = top["mapping_operation"]
        conf = top["confidence"]
        val_status = top["validation_status"]
        review_status = top["human_review_status"]
        src_dt = top.get("source_datatype") or "?"
        tgt_dt = top.get("target_datatype") or "?"
        info_loss = top.get("information_loss", False)
        warnings = top.get("warnings", [])

        status_icon = {
            "awaiting_review": "⏳",
            "approved": "✅",
            "rejected": "❌",
            "needs_more_evidence": "🔍",
        }.get(review_status, "?")

        val_icon = {"passed": "✓", "warning": "⚠", "failed": "✗", "pending": "…"}.get(val_status, "?")
        loss_icon = "🔴" if info_loss else ""

        lines.append(f"#### `{source_path}` → `{target_path}`")
        lines.append("")
        lines.append(f"| | |")
        lines.append(f"|---|---|")
        lines.append(f"| **Operation** | `{operation}` |")
        lines.append(f"| **Confidence** | {conf:.2f} |")
        lines.append(f"| **Types** | `{src_dt}` → `{tgt_dt}` |")
        lines.append(f"| **Validation** | {val_icon} {val_status} |")
        lines.append(f"| **Review status** | {status_icon} {review_status} |")
        if info_loss:
            lines.append(f"| **Information loss** | {loss_icon} {top.get('information_loss_description', 'detected')} |")
        if top.get("unit_conversion"):
            lines.append(f"| **Unit conversion** | `{top['unit_conversion']}` |")
        lines.append("")

        if warnings:
            lines.append("**Warnings:**")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        if len(sorted_hyps) > 1:
            lines.append("**Alternatives:**")
            for alt in sorted_hyps[1:]:
                lines.append(
                    f"- `{alt['target_path']}` ({alt['mapping_operation']}, conf={alt['confidence']:.2f})"
                )
            lines.append("")

        lines.append("**Human action required**: approve / reject / change-target / change-operation / request-evidence")
        lines.append("")
        lines.append("---")
        lines.append("")

    if constant_assignments:
        lines.append("### Constant Assignments (no source field)")
        lines.append("")
        for h in constant_assignments:
            rule = h.get("transformation_rule") or {}
            const_val = rule.get("constant_value", "?")
            lines.append(
                f"- `{h['target_path']}` = `\"{const_val}\"` "
                f"(inferred from source column name, conf={h['confidence']:.2f})"
            )
        lines.append("")

    if loss_report.get("lossy_mappings"):
        lines.append("### Information Loss Summary")
        lines.append("")
        for loss in loss_report["lossy_mappings"]:
            lines.append(
                f"- [{loss['severity'].upper()}] `{loss['source_path']}` → "
                f"`{loss.get('target_path', 'unmapped')}`: {loss['description']}"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/read_run_summary.py <output-dir>", file=sys.stderr)
        return 1

    output_dir = Path(sys.argv[1]).resolve()
    if not output_dir.is_dir():
        print(f"Error: directory not found: {output_dir}", file=sys.stderr)
        return 1

    run_type = _detect_run_type(output_dir)
    if run_type == "ontology_align":
        print(_summarise_ontology_run(output_dir))
    elif run_type == "schema_align":
        print(_summarise_schema_run(output_dir))
    else:
        print(f"Error: no recognised candidates file found in {output_dir}", file=sys.stderr)
        print("Expected: ontology_mapping_candidates.json or field_mapping_candidates.json", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
