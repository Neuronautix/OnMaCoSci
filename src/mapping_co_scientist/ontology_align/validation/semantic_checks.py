from __future__ import annotations
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation
)


def check_exactmatch_overreach(h: OntologyMappingHypothesis) -> list[str]:
    """Return list of warning strings if exactMatch is overreaching."""
    warnings = []
    if h.ontology_relation == OntologyRelation.EXACT_MATCH and h.confidence < 0.95:
        warnings.append(
            f"skos:exactMatch proposed at confidence {h.confidence:.2f}. "
            "exactMatch requires high confidence AND semantic validation."
        )
    return warnings


def check_subclass_hierarchy(h: OntologyMappingHypothesis) -> list[str]:
    """Check for basic hierarchy compatibility issues."""
    warnings = []
    if h.hierarchy_compatibility == "incompatible":
        warnings.append(
            f"Hierarchy incompatibility detected for mapping "
            f"{h.source_concept.entity_id} -> {h.target_ontology_entity.term_id}"
        )
    return warnings
