"""Markdown report generator for the Ontology Mapping Co-Scientist system.

Generates a human-readable Markdown review report from the assembled review
packets produced by the pipeline.  The report is designed to be read by a
domain scientist who will make the final accept/reject decisions on each
proposed mapping.

The report structure is:
1. Title and metadata header
2. Important notice (hypothesis disclaimer)
3. Per-entity sections with top candidate, alternatives, suggested action,
   required conditions
4. Summary tables (by predicate, by confidence bucket, by suggested action)
5. Footer

All packets consumed here are plain dicts produced by
:meth:`~ontology_mapping_co_scientist.agents.human_review.HumanReviewAgent.prepare_review_packet`.
Nested model objects are serialised via ``model_dump()`` so all access is
via dict keys, not attribute access.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis

_PIPELINE_VERSION = "0.1.0"

_BUCKET_HIGH = 0.80
_BUCKET_MEDIUM = 0.60
_BUCKET_LOW = 0.40


def _confidence_bucket(score: float) -> str:
    """Return a human-readable confidence bucket label for *score*."""
    if score >= _BUCKET_HIGH:
        return "High (>=0.80)"
    if score >= _BUCKET_MEDIUM:
        return "Medium (0.60-0.79)"
    if score >= _BUCKET_LOW:
        return "Low (0.40-0.59)"
    return "Very Low (<0.40)"


def _escape_pipe(text: str) -> str:
    """Escape pipe characters so they don't break Markdown tables."""
    return str(text).replace("|", "\\|")


def _format_evidence_list(items: list[dict]) -> str:
    """Format a list of Evidence dicts as Markdown bullet points.

    Args:
        items: List of Evidence dicts (keys: evidence_type, description, score, source).

    Returns:
        A string of Markdown bullet points, or a ``_(none)_`` placeholder.
    """
    if not items:
        return "_None recorded._"
    lines = []
    for ev in items:
        score_str = f" _(score: {ev['score']:.3f})_" if ev.get("score") is not None else ""
        source_str = f" [source: `{ev['source']}`]" if ev.get("source") else ""
        lines.append(
            f"- **{ev.get('evidence_type', 'unknown')}**{score_str}: "
            f"{ev.get('description', '')}{source_str}"
        )
    return "\n".join(lines)


def _format_validation_badge(status: str) -> str:
    """Return a short inline indicator for a validation status."""
    badges = {
        "passed": "passed",
        "failed": "FAILED",
        "warning": "warning",
        "pending": "pending",
    }
    return badges.get(status, status)


def _entity_section(packet: dict) -> str:
    """Render the Markdown section for one source entity.

    Args:
        packet: A review packet dict with keys: source_entity_id,
            source_entity_label, top_mapping (dict), alternative_mappings
            (list[dict]), suggested_action (dict), all_warnings (list[str]).

    Returns:
        A Markdown string for this entity's section, ending with ``---``.
    """
    entity_id = packet.get("source_entity_id", "unknown")
    entity_label = packet.get("source_entity_label", entity_id)
    top: dict | None = packet.get("top_mapping")
    alternatives: list[dict] = packet.get("alternative_mappings", [])
    suggested: dict | None = packet.get("suggested_action")
    all_warnings: list[str] = packet.get("all_warnings", [])

    lines: list[str] = []

    # Section heading
    lines.append(f"## {_escape_pipe(entity_label)} (`{_escape_pipe(entity_id)}`)")
    lines.append("")

    # Entity metadata (from source_entity sub-dict in top_mapping if available)
    if top:
        src = top.get("source_entity", {})
        datatype_str = f"`{src.get('datatype')}`" if src.get("datatype") else "_unknown_"
        examples = src.get("examples", [])
        examples_str = (
            ", ".join(f"`{e}`" for e in examples[:5]) if examples else "_none_"
        )
        desc_str = src.get("description") or "_no description_"
        source_type = src.get("source_type", "unknown")
        lines.append(
            f"**Source type**: `{source_type}` | **Datatype**: {datatype_str}"
        )
        lines.append("")
        lines.append(f"**Description**: {_escape_pipe(desc_str)}")
        lines.append("")
        lines.append(f"**Example values**: {examples_str}")
        lines.append("")

    # Global warnings (aggregated across all hypotheses for this entity)
    if all_warnings:
        lines.append("> **Warnings for this entity:**")
        lines.append(">")
        for w in all_warnings:
            lines.append(f"> - {w}")
        lines.append("")

    # Top candidate mapping
    lines.append("### Top Candidate Mapping")
    lines.append("")

    if top is None or top.get("predicate") == "custom:noMapping":
        lines.append(
            "_No suitable ontology term was found for this source entity._"
        )
        lines.append("")
    else:
        target = top.get("target_entity") or {}
        predicate = top.get("predicate", "unknown")
        confidence = top.get("confidence", 0.0)
        val_status = top.get("validation_status", "pending")
        mapping_id = top.get("mapping_id", "")
        val_badge = _format_validation_badge(val_status)

        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **Target ID** | `{_escape_pipe(target.get('term_id', 'unknown'))}` |")
        lines.append(f"| **Target Label** | {_escape_pipe(target.get('label', 'unknown'))} |")
        if target.get("definition"):
            defn = target["definition"]
            defn_short = defn[:200] + ("..." if len(defn) > 200 else "")
            lines.append(f"| **Definition** | {_escape_pipe(defn_short)} |")
        if target.get("synonyms"):
            syns = ", ".join(target["synonyms"][:4])
            lines.append(f"| **Synonyms** | {_escape_pipe(syns)} |")
        lines.append(f"| **Predicate** | `{_escape_pipe(predicate)}` |")
        lines.append(f"| **Confidence** | `{confidence:.4f}` |")
        lines.append(f"| **Validation** | {val_badge} |")
        lines.append(f"| **Mapping ID** | `{_escape_pipe(mapping_id)}` |")
        lines.append("")

        # Evidence
        evidence = top.get("evidence", [])
        lines.append("**Supporting evidence:**")
        lines.append("")
        lines.append(_format_evidence_list(evidence))
        lines.append("")

        # Counter-evidence / warnings
        counter_ev = top.get("counter_evidence", [])
        top_warnings = top.get("warnings", [])
        if counter_ev or top_warnings:
            lines.append("**Counter-evidence / Warnings:**")
            lines.append("")
            if counter_ev:
                lines.append(_format_evidence_list(counter_ev))
            for w in top_warnings:
                lines.append(f"- {w}")
            lines.append("")

        # Required conditions
        required_conditions = top.get("required_conditions", [])
        if required_conditions:
            lines.append("**Required conditions for this mapping to be valid:**")
            lines.append("")
            for cond in required_conditions:
                lines.append(f"- {cond}")
            lines.append("")

        # Provenance
        prov = top.get("provenance", {})
        if prov:
            lines.append("<details>")
            lines.append("<summary>Provenance</summary>")
            lines.append("")
            lines.append(f"- **Created by**: `{prov.get('created_by', 'unknown')}`")
            lines.append(f"- **Method**: `{prov.get('method', 'unknown')}`")
            lines.append(f"- **Created at**: `{prov.get('created_at', 'unknown')}`")
            if prov.get("pipeline_run_id"):
                lines.append(f"- **Pipeline run ID**: `{prov['pipeline_run_id']}`")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # Alternative mappings table
    valid_alts = [
        a for a in alternatives if a.get("predicate") != "custom:noMapping"
    ]
    if valid_alts:
        lines.append("### Alternative Mappings")
        lines.append("")
        lines.append(
            "| Rank | Target ID | Label | Predicate | Confidence | Validation |"
        )
        lines.append(
            "|------|-----------|-------|-----------|------------|------------|"
        )
        for alt in valid_alts[:3]:
            alt_target = alt.get("target_entity") or {}
            val_badge = _format_validation_badge(alt.get("validation_status", "pending"))
            lines.append(
                f"| {alt.get('rank', '-')} "
                f"| `{_escape_pipe(alt_target.get('term_id', 'unknown'))}` "
                f"| {_escape_pipe(alt_target.get('label', 'unknown'))} "
                f"| `{_escape_pipe(alt.get('predicate', 'unknown'))}` "
                f"| `{alt.get('confidence', 0.0):.4f}` "
                f"| {val_badge} |"
            )
        lines.append("")

    # Suggested human action
    if suggested:
        lines.append("### Suggested Human Action")
        lines.append("")
        lines.append(f"**Action**: `{suggested.get('action', 'unknown')}`")
        lines.append("")
        lines.append(f"**Reason**: {suggested.get('reason', '')}")
        if suggested.get("suggested_predicate"):
            lines.append("")
            lines.append(
                f"**Suggested replacement predicate**: `{suggested['suggested_predicate']}`"
            )
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _summary_section(
    review_packets: list[dict],
    hypotheses: list["MappingHypothesis"],
    validation_summary: dict,
) -> str:
    """Render the summary section of the report.

    Args:
        review_packets: The per-entity review packets.
        hypotheses: All mapping hypotheses (as MappingHypothesis objects for stats).
        validation_summary: Validation count dict from the pipeline.

    Returns:
        A Markdown string for the summary section.
    """
    lines: list[str] = []
    lines.append("## Pipeline Summary")
    lines.append("")

    # Validation counts
    lines.append("### Validation Status")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Passed | {validation_summary.get('passed', 0)} |")
    lines.append(f"| Failed | {validation_summary.get('failed', 0)} |")
    lines.append(f"| Warning | {validation_summary.get('warnings', 0)} |")
    lines.append(f"| **Total** | **{validation_summary.get('total', 0)}** |")
    lines.append("")

    # By predicate
    pred_counts: Counter = Counter()
    for h in hypotheses:
        pred_counts[str(h.predicate)] += 1

    lines.append("### Hypotheses by Predicate")
    lines.append("")
    lines.append("| Predicate | Count |")
    lines.append("|-----------|-------|")
    for pred, count in sorted(pred_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{pred}` | {count} |")
    lines.append("")

    # By confidence bucket
    bucket_counts: Counter = Counter()
    for h in hypotheses:
        bucket_counts[_confidence_bucket(h.confidence)] += 1

    bucket_order = [
        "High (>=0.80)",
        "Medium (0.60-0.79)",
        "Low (0.40-0.59)",
        "Very Low (<0.40)",
    ]
    lines.append("### Hypotheses by Confidence Bucket")
    lines.append("")
    lines.append("| Confidence Bucket | Count |")
    lines.append("|-------------------|-------|")
    for bucket in bucket_order:
        lines.append(f"| {bucket} | {bucket_counts.get(bucket, 0)} |")
    lines.append("")

    # By suggested action (top hypothesis per entity)
    action_counts: Counter = Counter()
    for packet in review_packets:
        sa = packet.get("suggested_action")
        if sa:
            action_counts[sa.get("action", "unknown")] += 1

    lines.append("### Suggested Actions (Top Hypothesis per Entity)")
    lines.append("")
    lines.append("| Suggested Action | Count |")
    lines.append("|------------------|-------|")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{action}` | {count} |")
    lines.append("")

    return "\n".join(lines)


def generate_markdown_report(
    review_packets: list[dict],
    hypotheses: list["MappingHypothesis"],
    validation_summary: dict,
    output_path: str | Path,
    pipeline_run_id: str | None = None,
) -> None:
    """Generate and write a Markdown review report to *output_path*.

    The report is structured for consumption by a domain scientist who must
    review and act on each proposed mapping hypothesis.  It includes:

    1. Title and metadata (generated_at, run_id, entity/hypothesis counts)
    2. An explicit notice that all mappings are hypotheses requiring human review
    3. Per-entity sections: top candidate, evidence, warnings, alternative
       mappings, suggested action, provenance
    4. A summary section: validation counts, predicate distribution, confidence
       buckets, suggested action distribution
    5. A footer

    Args:
        review_packets: Per-entity review packets as produced by
            :meth:`~ontology_mapping_co_scientist.agents.human_review.HumanReviewAgent.prepare_all_packets`.
            Each packet is a dict with keys: source_entity_id,
            source_entity_label, top_mapping, alternative_mappings,
            suggested_action, all_warnings.
        hypotheses: The complete list of all MappingHypothesis objects from the
            pipeline, used for aggregate statistics.
        validation_summary: A dict of validation count statistics.
        output_path: Destination file path for the Markdown report.
        pipeline_run_id: Optional pipeline run identifier for the header.

    Returns:
        None.  The report is written to *output_path*.
    """
    output_path = Path(output_path)
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    n_entities = len(review_packets)
    n_hypotheses = len(hypotheses)

    lines: list[str] = []

    # Title
    lines.append("# Ontology Mapping Review Report")
    lines.append("")

    # Metadata
    lines.append("## Report Metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| **Generated at** | `{generated_at}` |")
    if pipeline_run_id:
        lines.append(f"| **Pipeline run ID** | `{pipeline_run_id}` |")
    lines.append(f"| **Total source entities** | {n_entities} |")
    lines.append(f"| **Total mapping hypotheses** | {n_hypotheses} |")
    lines.append(f"| **Validation passed** | {validation_summary.get('passed', 0)} |")
    lines.append(f"| **Validation failed** | {validation_summary.get('failed', 0)} |")
    lines.append(f"| **With warnings** | {validation_summary.get('warnings', 0)} |")
    lines.append(f"| **Pipeline version** | `{_PIPELINE_VERSION}` |")
    lines.append("")

    # Important notice
    lines.append("> **IMPORTANT NOTICE FOR REVIEWERS**")
    lines.append(">")
    lines.append(
        "> These mappings are **hypotheses**, not ground truth.  Each mapping "
        "represents the pipeline's best computational guess based on lexical "
        "similarity between source entity labels and ontology term labels and synonyms."
    )
    lines.append(">")
    lines.append(
        "> **Each mapping requires human expert review before use in production, "
        "research publications, or data integration workflows.**"
    )
    lines.append(">")
    lines.append(
        "> The pipeline cannot reason about biological or domain semantics.  "
        "A high confidence score means the labels are lexically similar — it "
        "does not guarantee that the mapping is semantically correct."
    )
    lines.append("")

    if not review_packets:
        lines.append("_No review packets were generated._")
        lines.append("")
    else:
        # Quick index
        lines.append("## Mapping Review")
        lines.append("")
        lines.append("**Quick index:**")
        lines.append("")
        for packet in review_packets:
            entity_id = packet.get("source_entity_id", "unknown")
            entity_label = packet.get("source_entity_label", entity_id)
            top = packet.get("top_mapping")
            sa = packet.get("suggested_action") or {}
            action = sa.get("action", "unknown")
            if top and top.get("predicate") != "custom:noMapping":
                tgt = top.get("target_entity") or {}
                target_str = (
                    f"`{tgt.get('term_id', 'unknown')}` "
                    f"({top.get('predicate', '')}, "
                    f"conf={top.get('confidence', 0.0):.3f})"
                )
            else:
                target_str = "_no mapping_"
            anchor = entity_label.lower().replace(" ", "-").replace("/", "").replace("_", "-")
            lines.append(
                f"- [{entity_label}](#{anchor}) → {target_str} | action: `{action}`"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        # Per-entity sections
        for packet in review_packets:
            lines.append(_entity_section(packet))

    # Summary section
    lines.append(_summary_section(review_packets, hypotheses, validation_summary))

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"_Report generated by **ontology-mapping-co-scientist v{_PIPELINE_VERSION}** "
        f"at {generated_at}._"
    )
    lines.append("")
    lines.append(
        "_All mappings in this report are computational hypotheses and must be "
        "reviewed by a qualified domain expert before operational use._"
    )
    lines.append("")

    report_text = "\n".join(lines)
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
        fh.write("\n")
