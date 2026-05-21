"""
Extracts unit annotations from field labels and descriptions and detects unit mismatches.
"""

from __future__ import annotations

import re

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.review import AdversarialFlag

# ---------------------------------------------------------------------------
# Unit pattern registry
# ---------------------------------------------------------------------------

# Each entry maps a compiled regex to a canonical unit string.
# Patterns are tested against lowercased text.
UNIT_PATTERNS: dict[re.Pattern, str] = {
    # Concentration: ng/mL
    re.compile(r"\bng[_/]ml\b|nanograms?\s+per\s+m[lr]"): "ng/mL",
    # Mass ratio: ng/g
    re.compile(r"\bng[_/]g\b"): "ng/g",
    # Concentration: g/dL
    re.compile(r"\bg[_/]dl\b"): "g/dL",
    # Dose: mg/kg
    re.compile(r"\bmg[_/]kg\b"): "mg/kg",
    # Concentration: mmol/L
    re.compile(r"\bmmol[_/]l\b"): "mmol/L",
    # Concentration: µmol/L (also umol)
    re.compile(r"\b[uµ]mol[_/]l\b"): "µmol/L",
    # Enzyme activity: U/L
    re.compile(r"\bu[_/]l\b"): "U/L",
    # Percent
    re.compile(r"\bpercent\b|(?<![a-z])pct(?![a-z])|[_\b]pct\b|%"): "percent",
    # Cell count: 10^9/L
    re.compile(r"\b10[e^]9[_/]l\b|10e9[_/]l"): "10^9/L",
    # Cell count: 10^12/L
    re.compile(r"\b10[e^]12[_/]l\b|10e12[_/]l"): "10^12/L",
    # Time: hours  — matches trailing _h or standalone h (but NOT inside words like hematocrit)
    re.compile(r"(?<![a-z])_h\b|\bh(?:ours?)?\b(?=\s*$|\s+[^a-z]|\s*[_,)])"): "hours",
    # Time: weeks
    re.compile(r"\bweeks?\b"): "weeks",
    # Mass: grams standalone (body_weight_g etc) — after underscore or as sole unit
    re.compile(r"(?:_|\b)g\b(?![\w/])"): "g",
}

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_units(text: str) -> list[str]:
    """Extract canonical unit names from *text*.

    Runs all :data:`UNIT_PATTERNS` against the lowercased text and returns the
    deduplicated list of matched canonical unit names, in the order of first
    match.

    Args:
        text: The string to search (e.g. a field label or description).

    Returns:
        A deduplicated list of canonical unit strings found in *text*.
    """
    lowered = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for pattern, canonical in UNIT_PATTERNS.items():
        if pattern.search(lowered) and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


# ---------------------------------------------------------------------------
# Compatibility check
# ---------------------------------------------------------------------------

# Groups of units that are considered mutually incompatible with each other.
# Units within the same group are compatible; units across groups are not.
_COMPATIBLE_GROUPS: list[frozenset[str]] = [
    frozenset({"ng/mL", "ng/g", "g/dL", "mg/kg", "mmol/L", "µmol/L", "U/L", "g"}),  # mass/conc
    frozenset({"percent"}),
    frozenset({"hours", "weeks"}),   # time units — compatible with each other
    frozenset({"10^9/L", "10^12/L"}),   # cell counts — compatible with each other
]


def _unit_group(unit: str) -> int | None:
    """Return the group index of *unit*, or None if it doesn't belong to a group."""
    for idx, group in enumerate(_COMPATIBLE_GROUPS):
        if unit in group:
            return idx
    return None


def units_compatible(
    source_units: list[str],
    target_units: list[str],
) -> tuple[bool, str]:
    """Determine whether two sets of units are compatible.

    Rules:
    * If either list is empty the comparison is inconclusive — returns
      ``(True, "")``.
    * Units from different *groups* (e.g. a concentration vs a percentage) are
      incompatible.
    * Units within the same group are compatible.
    * Unknown units (not in any group) are treated as compatible.

    Args:
        source_units: Canonical unit names extracted from the source entity.
        target_units: Canonical unit names extracted from the target term.

    Returns:
        ``(True, "")`` when compatible; ``(False, reason)`` when incompatible.
    """
    if not source_units or not target_units:
        return True, ""

    for s_unit in source_units:
        s_group = _unit_group(s_unit)
        if s_group is None:
            continue
        for t_unit in target_units:
            t_group = _unit_group(t_unit)
            if t_group is None:
                continue
            if s_group != t_group:
                return (
                    False,
                    f"Unit '{s_unit}' (source) is incompatible with '{t_unit}' (target): "
                    f"they belong to different measurement domains.",
                )
    return True, ""


# ---------------------------------------------------------------------------
# Adversarial flag builder
# ---------------------------------------------------------------------------


def build_unit_mismatch_flag(
    source_entity: SourceEntity,
    target_term: OntologyTerm,
) -> AdversarialFlag | None:
    """Check for unit mismatches between a source entity and an ontology term.

    Extracts units from:
    * Source: ``label`` + ``description``
    * Target: ``label`` + ``definition`` + ``extra_context.get("units", "")``

    Args:
        source_entity: The source entity to inspect.
        target_term: The candidate ontology term.

    Returns:
        An :class:`~ontology_mapping_co_scientist.models.review.AdversarialFlag`
        with ``flag_type="unit_mismatch"`` and ``severity="high"`` when a
        conflict is detected; ``None`` otherwise.
    """
    source_text_parts = [source_entity.label]
    if source_entity.description:
        source_text_parts.append(source_entity.description)
    source_text = " ".join(source_text_parts)

    target_text_parts = [target_term.label]
    if target_term.definition:
        target_text_parts.append(target_term.definition)
    extra_units = target_term.extra_context.get("units", "")
    if extra_units:
        target_text_parts.append(str(extra_units))
    target_text = " ".join(target_text_parts)

    source_units = extract_units(source_text)
    target_units = extract_units(target_text)

    compatible, reason = units_compatible(source_units, target_units)
    if compatible:
        return None

    return AdversarialFlag(
        flag_type="unit_mismatch",
        description=(
            f"Unit mismatch detected between source entity "
            f"'{source_entity.label}' (units: {source_units}) and "
            f"target term '{target_term.label}' (units: {target_units}). "
            f"{reason}"
        ),
        severity="high",
    )
