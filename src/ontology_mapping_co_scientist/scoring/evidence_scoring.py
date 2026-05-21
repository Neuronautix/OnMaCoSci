"""Evidence construction and confidence aggregation for ontology mappings.

This module provides factory functions for building :class:`Evidence` objects
from specific evidence strategies, and an aggregation function that combines
multiple evidence items (supporting and counter) into a single scalar
confidence score.

The two primary evidence types produced here are:

* **lexical_similarity** – derived from a string-similarity metric between the
  source entity label and a candidate ontology term label.
* **synonym_match** – triggered when the source label matches one of the
  candidate term's recorded synonyms.
"""

from __future__ import annotations

from ontology_mapping_co_scientist.models.mapping_hypothesis import Evidence


# ---------------------------------------------------------------------------
# Evidence factory functions
# ---------------------------------------------------------------------------


def build_lexical_evidence(
    source_label: str,
    target_label: str,
    score: float,
) -> Evidence:
    """Build an :class:`Evidence` object for a lexical-similarity match.

    Creates a single evidence item recording the string-similarity score
    between *source_label* and *target_label* as computed by the lexical
    scoring backend (RapidFuzz WRatio or difflib fallback).

    Args:
        source_label: Human-readable label of the source entity being mapped.
        target_label: Preferred label of the candidate ontology term.
        score: Normalised similarity score in ``[0.0, 1.0]`` produced by the
            similarity backend.

    Returns:
        An :class:`Evidence` instance with:

        * ``evidence_type = "lexical_similarity"``
        * ``description`` – a human-readable sentence quoting both labels and
          the rounded score.
        * ``score`` – the raw *score* value (clamped to ``[0.0, 1.0]``).
        * ``source`` – ``"rapidfuzz.WRatio"`` (or the active backend name).

    Example::

        ev = build_lexical_evidence("strain", "mouse strain", 0.82)
        # ev.description == "Lexical similarity between 'strain' and 'mouse strain': 0.82"
    """
    clamped = max(0.0, min(1.0, score))
    description = (
        f"Lexical similarity between '{source_label}' and '{target_label}': "
        f"{clamped:.2f}"
    )
    return Evidence(
        evidence_type="lexical_similarity",
        description=description,
        score=clamped,
        source="rapidfuzz.WRatio",
    )


def build_synonym_evidence(
    source_label: str,
    matched_synonym: str,
    term_id: str,
    score: float,
) -> Evidence:
    """Build an :class:`Evidence` object for a synonym match.

    Created when the source entity label matches (or strongly resembles) one
    of the synonyms recorded for a candidate ontology term.  Synonym matches
    are treated as strong evidence because they indicate the data producer may
    be using a community-recognised alternative name.

    Args:
        source_label: Human-readable label of the source entity.
        matched_synonym: The synonym string from the ontology term that was
            matched against *source_label*.
        term_id: The CURIE or IRI of the ontology term whose synonym was
            matched, e.g. ``"mbo:MouseStrain"``.
        score: Normalised similarity score in ``[0.0, 1.0]`` between
            *source_label* and *matched_synonym*.

    Returns:
        An :class:`Evidence` instance with:

        * ``evidence_type = "synonym_match"``
        * ``description`` – a sentence describing which synonym of which term
          was matched.
        * ``score`` – the *score* value clamped to ``[0.0, 1.0]``.
        * ``source`` – ``"synonym_lookup"``

    Example::

        ev = build_synonym_evidence("strain", "mouse strain", "mbo:MouseStrain", 0.95)
        # ev.description == "Source label 'strain' matches synonym 'mouse strain' of term mbo:MouseStrain"
    """
    clamped = max(0.0, min(1.0, score))
    description = (
        f"Source label '{source_label}' matches synonym '{matched_synonym}' "
        f"of term {term_id}"
    )
    return Evidence(
        evidence_type="synonym_match",
        description=description,
        score=clamped,
        source="synonym_lookup",
    )


# ---------------------------------------------------------------------------
# Confidence aggregation
# ---------------------------------------------------------------------------


def compute_aggregate_confidence(
    evidences: list[Evidence],
    counter_evidences: list[Evidence],
) -> float:
    """Aggregate a list of supporting and counter evidence into a single score.

    Algorithm
    ---------
    1. Compute the **mean** of all supporting evidence scores (items whose
       :attr:`~Evidence.score` is not ``None``).  If all scores are ``None``
       or the list is empty, the base score is ``0.0``.
    2. Subtract ``0.1`` for each item in *counter_evidences* that carries a
       non-``None`` score, and an additional ``0.05`` for each item that has
       ``score = None`` (qualitative counter-evidence is still penalising but
       less so).
    3. Clamp the result to ``[0.0, 1.0]``.

    This intentionally simple heuristic is designed to be transparent and
    easy to override by a more sophisticated scoring agent.

    Args:
        evidences: List of supporting :class:`Evidence` items.  Items with
            ``score = None`` are counted in the denominator only if at least
            one other item has a numeric score; otherwise they are ignored.
        counter_evidences: List of counter :class:`Evidence` items arguing
            against the mapping.  Each contributes a penalty to the aggregate
            score.

    Returns:
        A float in ``[0.0, 1.0]`` representing the aggregate confidence.

    Examples:
        >>> ev1 = Evidence(evidence_type="lexical_similarity",
        ...                description="...", score=0.85, source=None)
        >>> ev2 = Evidence(evidence_type="synonym_match",
        ...                description="...", score=0.90, source=None)
        >>> compute_aggregate_confidence([ev1, ev2], [])
        0.875
        >>> # Two counter-evidences each subtract 0.1
        >>> counter = [
        ...     Evidence(evidence_type="type_mismatch", description="...",
        ...              score=0.6, source=None),
        ... ]
        >>> compute_aggregate_confidence([ev1, ev2], counter)
        0.775
    """
    # --- Supporting evidence mean ---
    scored_values: list[float] = [
        e.score for e in evidences if e.score is not None
    ]

    if scored_values:
        base_score = sum(scored_values) / len(scored_values)
    else:
        base_score = 0.0

    # --- Counter-evidence penalties ---
    penalty = 0.0
    for ce in counter_evidences:
        if ce.score is not None:
            # Scaled penalty: higher-scored counter-evidence penalises more
            penalty += 0.1
        else:
            # Qualitative counter-evidence: smaller fixed penalty
            penalty += 0.05

    aggregate = base_score - penalty
    return max(0.0, min(1.0, aggregate))
