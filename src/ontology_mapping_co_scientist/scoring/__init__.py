"""Scoring utilities for the Ontology Mapping Co-Scientist system."""

from ontology_mapping_co_scientist.scoring.lexical_similarity import (
    compute_similarity,
    find_best_matches,
    normalize_label,
)

__all__ = ["compute_similarity", "find_best_matches", "normalize_label"]
