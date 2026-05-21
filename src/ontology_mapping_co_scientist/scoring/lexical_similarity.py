"""Lexical similarity scoring for the Ontology Mapping Co-Scientist system.

Provides label normalisation, pairwise string similarity, candidate ranking,
and predicate inference based on similarity scores.

RapidFuzz (https://github.com/maxbachmann/RapidFuzz) is used as the primary
similarity engine when available.  If it is not importable the module falls
back silently to :class:`difflib.SequenceMatcher`, which is always present in
the Python standard library.  The public API is identical in both cases; only
the exact numerical scores may differ slightly between the two backends.
"""

from __future__ import annotations

import re
import unicodedata

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingPredicate

# ---------------------------------------------------------------------------
# Optional rapidfuzz import with difflib fallback
# ---------------------------------------------------------------------------

try:
    from rapidfuzz import fuzz as _fuzz

    def _similarity_backend(a: str, b: str) -> float:
        """Compute WRatio similarity using rapidfuzz, returning a score in [0, 1]."""
        # rapidfuzz returns scores in the range [0, 100]
        return _fuzz.WRatio(a, b) / 100.0

    _BACKEND_NAME = "rapidfuzz.WRatio"

except ImportError:  # pragma: no cover
    import difflib as _difflib  # type: ignore[no-redef]

    def _similarity_backend(a: str, b: str) -> float:  # type: ignore[misc]
        """Compute similarity using difflib.SequenceMatcher, returning a score in [0, 1]."""
        return _difflib.SequenceMatcher(None, a, b).ratio()

    _BACKEND_NAME = "difflib.SequenceMatcher"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_label(label: str) -> str:
    """Normalise a label string for robust lexical comparison.

    Normalisation steps applied in order:

    1. Unicode NFC normalisation to canonicalise composed characters.
    2. Strip leading/trailing whitespace.
    3. Lowercase the entire string.
    4. Replace underscores (``_``) and hyphens (``-``) with a single space.
    5. Collapse any run of whitespace to a single space.
    6. Strip again (catches edge cases introduced by step 5).

    Args:
        label: The raw label string to normalise.

    Returns:
        The normalised label string.

    Examples:
        >>> normalize_label("Mouse_Strain")
        'mouse strain'
        >>> normalize_label("  body-weight (g)  ")
        'body weight (g)'
        >>> normalize_label("GENETIC__Background")
        'genetic background'
    """
    normalised = unicodedata.normalize("NFC", label)
    normalised = normalised.strip().lower()
    normalised = normalised.replace("_", " ").replace("-", " ")
    normalised = _WHITESPACE_RE.sub(" ", normalised)
    return normalised.strip()


def compute_similarity(a: str, b: str) -> float:
    """Compute lexical similarity between two strings.

    Uses RapidFuzz's ``WRatio`` (weighted ratio) if available, otherwise falls
    back to :class:`difflib.SequenceMatcher`.  The inputs are **not**
    pre-normalised by this function; call :func:`normalize_label` first if
    case/whitespace-insensitive comparison is needed.

    Args:
        a: First string.
        b: Second string.

    Returns:
        A similarity score in the range ``[0.0, 1.0]`` where ``1.0`` indicates
        identical strings and ``0.0`` indicates no similarity.
    """
    if not a or not b:
        return 0.0
    return _similarity_backend(a, b)


def find_best_matches(
    source_label: str,
    candidates: list[tuple[str, str]],
    top_k: int = 5,
) -> list[tuple[str, str, float]]:
    """Find the best-matching ontology terms for a source label.

    Both *source_label* and each candidate label are normalised with
    :func:`normalize_label` before comparison so that surface differences in
    case, punctuation, and spacing do not artificially penalise good matches.
    The original (un-normalised) ``term_id`` and ``label`` values from
    *candidates* are preserved in the returned tuples.

    Args:
        source_label: The label of the source entity to match.
        candidates: A list of ``(term_id, label)`` tuples representing the
            candidate ontology terms.  An empty list causes an empty list to be
            returned immediately.
        top_k: Maximum number of results to return (default ``5``).  If fewer
            candidates exist than *top_k*, all of them are returned.

    Returns:
        A list of ``(term_id, label, score)`` tuples sorted by *score*
        descending.  *score* is in ``[0.0, 1.0]``.

    Examples:
        >>> candidates = [
        ...     ("mbo:MouseStrain", "mouse strain"),
        ...     ("mbo:BodyWeight", "body weight"),
        ...     ("mbo:Sex", "sex"),
        ... ]
        >>> results = find_best_matches("strain", candidates, top_k=2)
        >>> results[0][0]  # top hit term_id
        'mbo:MouseStrain'
    """
    if not candidates:
        return []

    norm_source = normalize_label(source_label)

    scored: list[tuple[str, str, float]] = []
    for term_id, label in candidates:
        norm_label = normalize_label(label)
        score = compute_similarity(norm_source, norm_label)
        scored.append((term_id, label, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]


def label_to_predicate(score: float) -> MappingPredicate:
    """Map a lexical similarity score to a :class:`MappingPredicate`.

    The thresholds below are calibrated for the WRatio metric and serve as a
    conservative starting point; they can be tuned via the pipeline
    configuration.

    ============= ========================= ====================================
    Score range   Predicate                 Rationale
    ============= ========================= ====================================
    ≥ 0.90        EXACT_MATCH               Near-identical labels — likely
                                            synonyms or the same concept.
    0.75 – 0.89   CLOSE_MATCH               Very similar but not identical;
                                            adequate for most analytical uses.
    0.55 – 0.74   BROAD_MATCH               Moderate overlap; term may be more
                                            general.  Flagged for human review.
    0.40 – 0.54   RELATED_MATCH             Weak lexical overlap; concepts may
                                            be thematically related but
                                            semantically distinct.
    < 0.40        NO_MAPPING                Insufficient lexical evidence to
                                            propose a mapping.
    ============= ========================= ====================================

    Args:
        score: A similarity score in ``[0.0, 1.0]``.

    Returns:
        The appropriate :class:`MappingPredicate` enum member.
    """
    if score >= 0.90:
        return MappingPredicate.EXACT_MATCH
    if score >= 0.75:
        return MappingPredicate.CLOSE_MATCH
    if score >= 0.55:
        return MappingPredicate.BROAD_MATCH
    if score >= 0.40:
        return MappingPredicate.RELATED_MATCH
    return MappingPredicate.NO_MAPPING


# ---------------------------------------------------------------------------
# Module-level metadata (useful for provenance logging)
# ---------------------------------------------------------------------------

#: Name of the similarity backend in use.  Exposed so that callers can record
#: it in :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.Provenance`
#: without re-importing the backend selection logic.
SIMILARITY_BACKEND: str = _BACKEND_NAME
