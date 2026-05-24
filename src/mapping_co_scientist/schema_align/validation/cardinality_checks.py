from __future__ import annotations
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis


def check_cardinality_compatibility(h: FieldMappingHypothesis) -> list[str]:
    issues = []
    if h.cardinality_relation is None:
        return issues
    src = h.cardinality_relation.source_cardinality
    tgt = h.cardinality_relation.target_cardinality
    # If source is multi-valued but target is single-valued
    if src in ("1..*", "0..*") and tgt in ("1", "0..1"):
        issues.append(
            f"Cardinality mismatch: source={src} -> target={tgt}. "
            "Aggregation or selection strategy required."
        )
    return issues
