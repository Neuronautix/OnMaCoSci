"""Ontology profiler agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`OntologyProfilerAgent`, which loads an ontology
profile and builds in-memory indexes for efficient candidate lookup during the
mapping pipeline.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from pathlib import Path

from ontology_mapping_co_scientist.io.ontology_profile_loader import load_ontology_profile
from ontology_mapping_co_scientist.models.entities import OntologyTerm
from ontology_mapping_co_scientist.scoring.lexical_similarity import (
    find_best_matches,
    normalize_label,
)

logger = logging.getLogger(__name__)


class OntologyProfilerAgent:
    """Extracts and indexes ontology terms for efficient lookup during mapping."""

    def __init__(self) -> None:
        """Initialise empty term storage and lookup indexes."""
        self._terms: list[OntologyTerm] = []
        self._label_index: dict[str, OntologyTerm] = {}
        self._synonym_index: dict[str, list[OntologyTerm]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_profile(self, filepath: str | Path) -> list[OntologyTerm]:
        """Load ontology terms from a profile file and build lookup indexes.

        Calls :func:`~ontology_mapping_co_scientist.io.ontology_profile_loader.load_ontology_profile`,
        stores the results internally, and then builds normalised label and
        synonym indexes via :meth:`_build_index`.

        Args:
            filepath: Path to the ontology profile file (JSON, OBO, or OWL
                depending on loader support).

        Returns:
            The list of :class:`~ontology_mapping_co_scientist.models.entities.OntologyTerm`
            objects that were loaded.

        Raises:
            FileNotFoundError: If *filepath* does not exist.
            ValueError: If the profile cannot be parsed.
        """
        filepath = Path(filepath)
        logger.info("Loading ontology profile from: %s", filepath)
        self._terms = load_ontology_profile(filepath)
        logger.info("Loaded %d ontology terms from: %s", len(self._terms), filepath)
        self._build_index()
        return self._terms

    def get_all_terms(self) -> list[OntologyTerm]:
        """Return all currently loaded ontology terms.

        Returns:
            The internal list of :class:`~ontology_mapping_co_scientist.models.entities.OntologyTerm`
            objects.  May be empty if :meth:`load_profile` has not been called.
        """
        return self._terms

    def get_candidates_for_label(
        self,
        label: str,
        top_k: int = 5,
    ) -> list[tuple[OntologyTerm, float]]:
        """Retrieve the top-k ontology term candidates for a given label string.

        Uses :func:`~ontology_mapping_co_scientist.scoring.lexical_similarity.find_best_matches`
        against the preferred labels of all loaded terms, then maps the results
        back to full :class:`~ontology_mapping_co_scientist.models.entities.OntologyTerm`
        objects.

        Args:
            label: The source label string to match against.
            top_k: Maximum number of candidates to return (default 5).

        Returns:
            A list of ``(OntologyTerm, score)`` tuples sorted by score
            descending.  May be shorter than *top_k* if fewer terms exist.
        """
        if not self._terms:
            logger.warning("get_candidates_for_label called with no terms loaded.")
            return []

        term_label_pairs = [(t.term_id, t.label) for t in self._terms]
        matches = find_best_matches(label, term_label_pairs, top_k=top_k)

        results: list[tuple[OntologyTerm, float]] = []
        for _tid, matched_label, score in matches:
            normalized = normalize_label(matched_label)
            term = self._label_index.get(normalized)
            if term is not None:
                results.append((term, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def summarize(self) -> dict:
        """Compute a statistical summary of the loaded ontology terms.

        Returns:
            A dictionary with the following keys:

            - ``total_terms`` (*int*) — total number of loaded terms.
            - ``by_type`` (:class:`~collections.Counter`) — counts per
              ``term_type`` value.
            - ``total_synonyms`` (*int*) — total number of synonym strings
              across all terms.
            - ``ontology_ids`` (*list[str]*) — sorted, deduplicated list of
              ``ontology_id`` values.
        """
        by_type: Counter = Counter(t.term_type for t in self._terms)
        total_synonyms = sum(len(t.synonyms) for t in self._terms)
        ontology_ids = sorted({t.ontology_id for t in self._terms})

        summary = {
            "total_terms": len(self._terms),
            "by_type": by_type,
            "total_synonyms": total_synonyms,
            "ontology_ids": ontology_ids,
        }
        logger.debug(
            "Ontology profile summary: total_terms=%d, total_synonyms=%d, ontologies=%s",
            summary["total_terms"],
            summary["total_synonyms"],
            ontology_ids,
        )
        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_index(self) -> None:
        """Populate the normalised label and synonym lookup indexes.

        After calling this method:

        - ``_label_index`` maps each normalised preferred label to its
          :class:`~ontology_mapping_co_scientist.models.entities.OntologyTerm`.
        - ``_synonym_index`` maps each normalised synonym string to the list
          of terms that carry that synonym.

        When two terms share the same normalised label the *last* one wins in
        ``_label_index`` (a warning is logged).
        """
        self._label_index = {}
        self._synonym_index = defaultdict(list)

        for term in self._terms:
            norm_label = normalize_label(term.label)
            if norm_label in self._label_index:
                logger.warning(
                    "Duplicate normalised label %r: term %r overwrites %r",
                    norm_label,
                    term.term_id,
                    self._label_index[norm_label].term_id,
                )
            self._label_index[norm_label] = term

            for synonym in term.synonyms:
                norm_syn = normalize_label(synonym)
                self._synonym_index[norm_syn].append(term)

        logger.debug(
            "Built label index (%d entries) and synonym index (%d entries).",
            len(self._label_index),
            len(self._synonym_index),
        )
