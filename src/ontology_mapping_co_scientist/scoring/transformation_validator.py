"""
Validates custom:requiresTransform mappings by checking that required_conditions
specify an actionable transformation and that example values survive it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    MappingHypothesis,
    MappingPredicate,
    ValidationStatus,
)

# ---------------------------------------------------------------------------
# Transform specification model
# ---------------------------------------------------------------------------


class TransformSpecification(BaseModel):
    """Parsed representation of a transformation condition string."""

    transform_type: str  # "unit_conversion", "format_change", "vocabulary_lookup", "scale", "unknown"
    description: str
    is_actionable: bool  # True if the transform is specific enough to implement

    model_config = {"frozen": False}


# ---------------------------------------------------------------------------
# Keyword patterns for transform type detection
# ---------------------------------------------------------------------------

# Patterns: list of (compiled_regex, transform_type)
# Order matters: more specific patterns should come first.
_TRANSFORM_PATTERNS: list[tuple[re.Pattern, str]] = [
    # unit_conversion: explicit unit names + conversion language
    (
        re.compile(
            r"\b(convert|converting|conversion|transform\s+unit|change\s+unit"
            r"|from\s+\w+\s+to\s+\w+.*(?:mol|gram|liter|unit|mg|ng|mmol|umol|"
            r"nmol|ml|dl|g|kg|percent|%|mw|molecular\s+weight))\b",
            re.IGNORECASE,
        ),
        "unit_conversion",
    ),
    # vocabulary_lookup: code mapping / controlled vocabulary
    (
        re.compile(
            r"\b(map|mapping|lookup|encode|decode|recode|translate|"
            r"code\s+to|codes?\s+[A-Z]|vocabulary|vocab|controlled\s+term)\b",
            re.IGNORECASE,
        ),
        "vocabulary_lookup",
    ),
    # format_change: date/time or string format normalisation
    (
        re.compile(
            r"\b(format|reformat|normalise|normalize|parse|date|datetime|"
            r"timestamp|iso\s*8601|yyyy|dd[-/]mm|string\s+to)\b",
            re.IGNORECASE,
        ),
        "format_change",
    ),
    # scale: numeric scaling / multiplication
    (
        re.compile(
            r"\b(scale|multiply|divide|factor|ratio|×|x\s+\d|\d\s*x\b)\b",
            re.IGNORECASE,
        ),
        "scale",
    ),
]

# Keywords that indicate a vague / non-actionable description
_VAGUE_PATTERN = re.compile(
    r"^(requires?\s+transform(?:ation)?|needs?\s+transform(?:ation)?|"
    r"transform(?:ation)?\s+required|some\s+transform|tbd|todo|unknown)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_transform_condition(condition: str) -> TransformSpecification:
    """
    Parse a required_condition string like:
    - "convert ng/mL to µmol/L using MW=412.5" -> unit_conversion, actionable=True
    - "map sex codes M/F to male/female" -> vocabulary_lookup, actionable=True
    - "requires transformation" -> unknown, actionable=False
    Uses keyword matching (no LLM).

    Args:
        condition: The condition string to parse.

    Returns:
        A :class:`TransformSpecification` describing the parsed condition.
    """
    stripped = condition.strip()

    # Check for vague / non-actionable descriptions first
    if _VAGUE_PATTERN.match(stripped):
        return TransformSpecification(
            transform_type="unknown",
            description=stripped,
            is_actionable=False,
        )

    # Very short conditions (≤ 5 chars) are not actionable
    if len(stripped) <= 5:
        return TransformSpecification(
            transform_type="unknown",
            description=stripped,
            is_actionable=False,
        )

    # Match against known transform patterns
    for pattern, transform_type in _TRANSFORM_PATTERNS:
        if pattern.search(stripped):
            return TransformSpecification(
                transform_type=transform_type,
                description=stripped,
                is_actionable=True,
            )

    # No specific pattern matched — if condition is reasonably long, treat as
    # "unknown but potentially actionable"; if very short, not actionable.
    is_actionable = len(stripped) > 15
    return TransformSpecification(
        transform_type="unknown",
        description=stripped,
        is_actionable=is_actionable,
    )


# ---------------------------------------------------------------------------
# Hypothesis-level validator
# ---------------------------------------------------------------------------


def validate_transform_mapping(
    hypothesis: MappingHypothesis,
) -> tuple[ValidationStatus, list[str]]:
    """
    For custom:requiresTransform hypotheses:
    1. Check required_conditions is not empty
    2. Parse each condition with parse_transform_condition
    3. If any condition is not actionable, return WARNING + message
    4. If required_conditions is empty, return WARNING + "no transform specified"
    5. Return PASSED if all conditions are actionable

    For non-REQUIRES_TRANSFORM predicates, returns (PASSED, []) immediately.

    Args:
        hypothesis: The mapping hypothesis to validate.

    Returns:
        A tuple of (ValidationStatus, list_of_warning_messages).
    """
    if hypothesis.predicate != MappingPredicate.REQUIRES_TRANSFORM:
        return ValidationStatus.PASSED, []

    if not hypothesis.required_conditions:
        return (
            ValidationStatus.WARNING,
            ["no transform specified: required_conditions is empty for a requiresTransform mapping"],
        )

    warnings: list[str] = []
    for condition in hypothesis.required_conditions:
        spec = parse_transform_condition(condition)
        if not spec.is_actionable:
            warnings.append(
                f"transform condition is vague or not actionable: {condition!r} "
                f"(detected type: {spec.transform_type}). "
                "Please specify the exact transformation steps."
            )

    if warnings:
        return ValidationStatus.WARNING, warnings

    return ValidationStatus.PASSED, []
