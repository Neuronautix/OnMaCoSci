from __future__ import annotations
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis

_COMPATIBLE_PAIRS: set[frozenset] = {
    frozenset({"number", "integer"}),
    frozenset({"string", "string"}),
}


def check_datatype_compatibility(h: FieldMappingHypothesis) -> list[str]:
    issues = []
    if h.source_datatype is None or h.target_datatype is None:
        return issues
    if h.source_datatype == h.target_datatype:
        return issues
    pair = frozenset({h.source_datatype, h.target_datatype})
    if pair not in _COMPATIBLE_PAIRS:
        issues.append(
            f"Incompatible datatypes: {h.source_datatype} -> {h.target_datatype}. "
            "Explicit conversion rule required."
        )
    return issues
