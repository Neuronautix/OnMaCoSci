"""
Expands entity labels using a biomedical synonym dictionary.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Default path to the bundled synonym dictionary
_DEFAULT_TSV: Path = (
    Path(__file__).parent.parent / "data" / "biomedical_synonyms.tsv"
)


def load_synonym_dictionary(
    filepath: str | Path | None = None,
) -> dict[str, list[str]]:
    """Load the biomedical synonym dictionary from a TSV file.

    The TSV format has two columns separated by a tab:

    * ``term`` — the canonical term (key).
    * ``synonyms`` — pipe-separated list of synonyms for that term.

    Comment lines (starting with ``#``) and blank lines are skipped.  The
    first row is expected to be a header (``term\\tsynonyms``) and is skipped
    automatically when it matches that pattern.

    Args:
        filepath: Path to the TSV file.  When ``None`` (default) the bundled
            ``data/biomedical_synonyms.tsv`` file is used.

    Returns:
        A dict mapping canonical term strings to lists of synonym strings.
        E.g.::

            {"AUC": ["area under the curve", "drug exposure", ...], ...}
    """
    path = Path(filepath) if filepath is not None else _DEFAULT_TSV

    dictionary: dict[str, list[str]] = {}

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 2:
                continue
            term = row[0].strip()
            raw_synonyms = row[1].strip()
            # Skip header row
            if term.lower() == "term" and raw_synonyms.lower() == "synonyms":
                continue
            synonyms = [s.strip() for s in raw_synonyms.split("|") if s.strip()]
            if term:
                # Merge duplicates (e.g. NOAEL appears twice in spec)
                existing = dictionary.get(term, [])
                merged = existing + [s for s in synonyms if s not in existing]
                dictionary[term] = merged

    return dictionary


def expand_label(
    label: str,
    dictionary: dict[str, list[str]],
) -> list[str]:
    """Return all known synonyms for *label*.

    Checks whether *label* appears as:

    1. A canonical key in *dictionary* — returns that key's synonym list.
    2. A value in any synonym list — returns the synonyms for the matching
       canonical term (excluding the matched value itself, since the caller
       already has it).

    The search is case-insensitive.

    Args:
        label: The label to look up.
        dictionary: The synonym dictionary returned by
            :func:`load_synonym_dictionary`.

    Returns:
        A list of synonym strings, or ``[]`` if no match is found.  The
        original *label* is **not** included in the returned list (it is
        added by :func:`get_expanded_labels`).
    """
    label_lower = label.lower()
    results: list[str] = []
    seen: set[str] = set()

    for canonical, synonyms in dictionary.items():
        if canonical.lower() == label_lower:
            # Direct key match — add all synonyms
            for s in synonyms:
                if s.lower() != label_lower and s not in seen:
                    seen.add(s)
                    results.append(s)
            # Also add the canonical form itself as a synonym if different
            if canonical not in seen and canonical.lower() != label_lower:
                seen.add(canonical)
                results.insert(0, canonical)
            continue

        # Check synonym list
        for s in synonyms:
            if s.lower() == label_lower:
                # Add canonical key and all other synonyms
                if canonical not in seen and canonical.lower() != label_lower:
                    seen.add(canonical)
                    results.append(canonical)
                for other_s in synonyms:
                    if other_s.lower() != label_lower and other_s not in seen:
                        seen.add(other_s)
                        results.append(other_s)
                break

    return results


def get_expanded_labels(
    entity_label: str,
    dictionary: dict[str, list[str]],
) -> list[str]:
    """Return the original label plus all its known synonyms, deduplicated.

    This is the primary entry point for synonym-based query expansion.  The
    returned list always starts with the original *entity_label* and is
    followed by any synonyms found via :func:`expand_label`.

    Args:
        entity_label: The label to expand.
        dictionary: The synonym dictionary returned by
            :func:`load_synonym_dictionary`.

    Returns:
        A deduplicated list ``[entity_label, *synonyms]``.
    """
    synonyms = expand_label(entity_label, dictionary)
    seen: set[str] = {entity_label.lower()}
    expanded: list[str] = [entity_label]
    for s in synonyms:
        if s.lower() not in seen:
            seen.add(s.lower())
            expanded.append(s)
    return expanded
