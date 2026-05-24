"""Export field mapping hypotheses as a generic YAML mapping specification."""
from __future__ import annotations

from pathlib import Path

import yaml

from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation


def export_mapping_spec(
    hypotheses: list[FieldMappingHypothesis],
    output_path: Path,
    pipeline_run_id: str | None = None,
) -> None:
    """Export field mappings as a reusable YAML mapping specification."""
    spec: dict = {
        "version": "1.0",
        "pipeline_run_id": pipeline_run_id or "unknown",
        "mappings": [],
        "unmapped_fields": [],
        "human_review_required": [],
    }

    for h in hypotheses:
        if h.mapping_operation == MappingOperation.UNMAPPED:
            spec["unmapped_fields"].append({
                "source_path": h.source_path,
                "confidence": h.confidence,
                "reason": "No suitable target field found",
            })
            continue

        if h.mapping_operation == MappingOperation.HUMAN_REVIEW_REQUIRED:
            spec["human_review_required"].append({
                "source_path": h.source_path,
                "target_path": h.target_path,
                "reason": h.warnings[0] if h.warnings else "Ambiguous mapping",
            })
            continue

        mapping_entry: dict = {
            "source_path": h.source_path,
            "target_path": h.target_path,
            "operation": str(h.mapping_operation),
            "confidence": round(h.confidence, 4),
        }

        if h.transformation_rule:
            rule = h.transformation_rule
            if rule.constant_value is not None:
                mapping_entry["constant_value"] = rule.constant_value
            if rule.datatype_from or rule.datatype_to:
                mapping_entry["datatype"] = {"from": rule.datatype_from, "to": rule.datatype_to}
            if rule.unit_from or rule.unit_to:
                mapping_entry["unit"] = {"from": rule.unit_from, "to": rule.unit_to}
            if rule.enumeration_map:
                mapping_entry["enumeration_map"] = rule.enumeration_map
            if rule.expression:
                mapping_entry["expression"] = rule.expression

        if h.information_loss:
            mapping_entry["information_loss"] = h.information_loss_description

        if h.warnings:
            mapping_entry["warnings"] = h.warnings

        spec["mappings"].append(mapping_entry)

    output_path.write_text(yaml.safe_dump(spec, default_flow_style=False, allow_unicode=True), encoding="utf-8")
