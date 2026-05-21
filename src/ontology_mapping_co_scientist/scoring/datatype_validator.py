"""
Validates compatibility between source entity datatypes and target ontology
term types (class vs property) and rdfs:range annotations.
"""

from __future__ import annotations

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.review import AdversarialFlag

# ---------------------------------------------------------------------------
# Compatibility matrices
# ---------------------------------------------------------------------------

# source datatype -> acceptable target term_types
DATATYPE_TERM_TYPE_COMPAT: dict[str, list[str]] = {
    "number":  ["property", "class"],   # can map to a measurement class or a property
    "string":  ["property", "class"],
    "boolean": ["property"],            # booleans are almost always properties, not classes
    "array":   ["class", "property"],
    "object":  ["class"],               # nested objects map to classes
    "unknown": ["property", "class"],   # unknown = permissive
}

# source datatype -> acceptable rdfs:range values (from extra_context.range)
RANGE_COMPAT: dict[str, list[str]] = {
    "number":  ["xsd:decimal", "xsd:float", "xsd:double", "xsd:integer",
                "xsd:int", "xsd:nonNegativeInteger", "owl:DatatypeProperty"],
    "string":  ["xsd:string", "xsd:anyURI", "rdfs:Literal", "owl:DatatypeProperty"],
    "boolean": ["xsd:boolean"],
}


# ---------------------------------------------------------------------------
# Compatibility check
# ---------------------------------------------------------------------------


def check_datatype_compatibility(
    source_entity: SourceEntity,
    target_term: OntologyTerm,
) -> tuple[bool, str]:
    """
    Returns (compatible: bool, reason: str).

    Checks:
    1. If source datatype is known and target term_type is set, verify the
       term_type is acceptable for that datatype.
    2. If source datatype is known and target has an rdfs:range annotation in
       extra_context, verify the range is acceptable.

    Permissive: if target has no term_type or range info, returns (True, "").
    """
    raw_datatype = (source_entity.datatype or "unknown").lower()
    # Normalise "integer" -> "number" for compatibility checks
    if raw_datatype == "integer":
        raw_datatype = "number"

    source_datatype = raw_datatype

    # --- term_type check ---
    target_term_type = (target_term.term_type or "").lower().strip()
    if target_term_type:
        acceptable_types = DATATYPE_TERM_TYPE_COMPAT.get(source_datatype, ["property", "class"])
        if target_term_type not in acceptable_types:
            return (
                False,
                f"Source datatype '{source_datatype}' is not compatible with "
                f"target term_type '{target_term_type}'. "
                f"Expected one of: {acceptable_types}.",
            )

    # --- rdfs:range check ---
    range_value = target_term.extra_context.get("range", "")
    if range_value and source_datatype in RANGE_COMPAT:
        acceptable_ranges = RANGE_COMPAT[source_datatype]
        if range_value not in acceptable_ranges:
            return (
                False,
                f"Source datatype '{source_datatype}' is not compatible with "
                f"target rdfs:range '{range_value}'. "
                f"Expected one of: {acceptable_ranges}.",
            )

    return True, ""


# ---------------------------------------------------------------------------
# Adversarial flag builder
# ---------------------------------------------------------------------------


def build_datatype_flag(
    source_entity: SourceEntity,
    target_term: OntologyTerm,
) -> AdversarialFlag | None:
    """Returns an AdversarialFlag(flag_type="datatype_incompatibility", severity="medium")
    or None if compatible.

    Args:
        source_entity: The source entity to inspect.
        target_term: The candidate ontology term.

    Returns:
        An :class:`AdversarialFlag` with ``flag_type="datatype_incompatibility"`` and
        ``severity="medium"`` when a conflict is detected; ``None`` otherwise.
    """
    compatible, reason = check_datatype_compatibility(source_entity, target_term)
    if compatible:
        return None

    return AdversarialFlag(
        flag_type="datatype_incompatibility",
        description=(
            f"Datatype incompatibility between source entity "
            f"'{source_entity.label}' (datatype={source_entity.datatype!r}) and "
            f"target term '{target_term.label}' (term_type={target_term.term_type!r}). "
            f"{reason}"
        ),
        severity="medium",
    )
