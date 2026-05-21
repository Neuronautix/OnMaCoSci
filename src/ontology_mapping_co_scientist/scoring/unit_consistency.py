"""
Full unit registry-based unit compatibility check using pint.
More precise than the regex-based unit_extractor — can detect that
ng/mL and µmol/L are both concentration units (compatible with transform)
while g/dL and mmol/L are not the same dimension.

Gracefully degrades to the regex unit_extractor if pint is not installed.
"""

from __future__ import annotations

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.scoring.unit_extractor import (
    extract_units,
    units_compatible,
)

# ---------------------------------------------------------------------------
# Optional pint import
# ---------------------------------------------------------------------------

try:
    import pint

    ureg = pint.UnitRegistry()
    HAS_PINT = True
except ImportError:
    HAS_PINT = False

# ---------------------------------------------------------------------------
# Unit -> pint string mapping
# ---------------------------------------------------------------------------

# Mapping from canonical unit names (from unit_extractor) to pint unit strings.
# None means "no pint equivalent — only comparable within the same canonical name".
UNIT_TO_PINT: dict[str, str | None] = {
    "ng/mL":   "nanogram / milliliter",
    "ng/g":    "nanogram / gram",
    "g/dL":    "gram / deciliter",
    "mg/kg":   "milligram / kilogram",
    "mmol/L":  "millimol / liter",
    "µmol/L":  "micromol / liter",
    "U/L":     None,  # enzyme activity — no pint equivalent, treat as comparable to U/L only
    "percent": "percent",
    "g":       "gram",
    "hours":   "hour",
    "weeks":   "week",
    "10^9/L":  None,  # cell counts — comparable within cell count units only
    "10^12/L": None,
}

# Groups of canonical unit names that have no pint equivalent and are only
# compatible with themselves
_OPAQUE_GROUPS: dict[str, frozenset[str]] = {
    "enzyme_activity": frozenset({"U/L"}),
    "cell_counts":     frozenset({"10^9/L", "10^12/L"}),
}


def _pint_dimensionality(unit_str: str) -> object | None:
    """Return the pint dimensionality of a unit string, or None on failure."""
    if not HAS_PINT:
        return None
    try:
        return ureg.parse_expression(unit_str).dimensionality
    except Exception:
        return None


def check_unit_compatibility_pint(
    source_units: list[str],
    target_units: list[str],
) -> tuple[bool, str]:
    """
    Uses pint dimensionality comparison when available.

    Rules:
    - If either list is empty, returns (True, "") — inconclusive.
    - For units with pint equivalents: compare dimensionality; different
      dimensionality means incompatible.
    - For units without pint equivalents (None in UNIT_TO_PINT): check opaque
      group membership — units in different opaque groups are incompatible.
    - Falls back to unit_extractor.units_compatible if pint unavailable.

    Args:
        source_units: Canonical unit names from the source entity.
        target_units: Canonical unit names from the target term.

    Returns:
        ``(True, "")`` if compatible; ``(False, reason)`` if not.
    """
    if not source_units or not target_units:
        return True, ""

    if not HAS_PINT:
        # Fall back to regex-based group comparison
        return units_compatible(source_units, target_units)

    for s_canonical in source_units:
        s_pint = UNIT_TO_PINT.get(s_canonical)
        for t_canonical in target_units:
            t_pint = UNIT_TO_PINT.get(t_canonical)

            # Both have pint equivalents — compare dimensionality
            if s_pint is not None and t_pint is not None:
                s_dim = _pint_dimensionality(s_pint)
                t_dim = _pint_dimensionality(t_pint)
                if s_dim is not None and t_dim is not None and s_dim != t_dim:
                    return (
                        False,
                        f"Unit '{s_canonical}' (dim={s_dim}) is dimensionally "
                        f"incompatible with '{t_canonical}' (dim={t_dim}).",
                    )

            # At least one has no pint equivalent — check opaque groups
            else:
                s_group = _find_opaque_group(s_canonical)
                t_group = _find_opaque_group(t_canonical)
                if s_group is not None and t_group is not None and s_group != t_group:
                    return (
                        False,
                        f"Unit '{s_canonical}' and '{t_canonical}' belong to "
                        f"different measurement domains ('{s_group}' vs '{t_group}').",
                    )
                # One has pint, one is opaque — treat as incompatible if the opaque
                # one is in a known group (e.g. cell counts vs concentration)
                if s_pint is not None and t_group is not None:
                    return (
                        False,
                        f"Unit '{s_canonical}' is a pint-measurable quantity but "
                        f"'{t_canonical}' belongs to an incommensurable domain '{t_group}'.",
                    )
                if t_pint is not None and s_group is not None:
                    return (
                        False,
                        f"Unit '{t_canonical}' is a pint-measurable quantity but "
                        f"'{s_canonical}' belongs to an incommensurable domain '{s_group}'.",
                    )

    return True, ""


def _find_opaque_group(canonical: str) -> str | None:
    """Return the opaque group name for a canonical unit, or None."""
    for group_name, members in _OPAQUE_GROUPS.items():
        if canonical in members:
            return group_name
    return None


# ---------------------------------------------------------------------------
# Top-level function
# ---------------------------------------------------------------------------


def get_unit_compatibility(
    source_entity: SourceEntity,
    target_term: OntologyTerm,
) -> tuple[bool, str]:
    """Top-level function: extract units from both sides, check compatibility.

    Extraction strategy:
    - Source: label + description
    - Target: label + definition + extra_context.get("units", "")

    Uses pint-based check when available, falls back to regex groups.

    Args:
        source_entity: The source entity to inspect.
        target_term: The candidate ontology term.

    Returns:
        ``(True, "")`` if compatible or inconclusive; ``(False, reason)`` if
        a confirmed incompatibility is found.
    """
    # Build source text
    source_parts = [source_entity.label]
    if source_entity.description:
        source_parts.append(source_entity.description)
    source_text = " ".join(source_parts)

    # Build target text
    target_parts = [target_term.label]
    if target_term.definition:
        target_parts.append(target_term.definition)
    extra_units = target_term.extra_context.get("units", "")
    if extra_units:
        target_parts.append(str(extra_units))
    target_text = " ".join(target_parts)

    source_units = extract_units(source_text)
    target_units = extract_units(target_text)

    return check_unit_compatibility_pint(source_units, target_units)
