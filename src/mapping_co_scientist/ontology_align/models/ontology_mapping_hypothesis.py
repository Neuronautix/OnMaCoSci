from __future__ import annotations
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field
from mapping_co_scientist.shared.models.evidence import Evidence, Provenance
from mapping_co_scientist.shared.models.review import ValidationStatus, HumanReviewStatus
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm


class OntologyRelation(StrEnum):
    EXACT_MATCH = "skos:exactMatch"
    CLOSE_MATCH = "skos:closeMatch"
    BROAD_MATCH = "skos:broadMatch"
    NARROW_MATCH = "skos:narrowMatch"
    RELATED_MATCH = "skos:relatedMatch"
    SUBCLASS_OF = "rdfs:subClassOf"
    EQUIVALENT_CLASS = "owl:equivalentClass"
    EQUIVALENT_PROPERTY = "owl:equivalentProperty"
    REQUIRES_ONTOLOGY_EXTENSION = "custom:requiresOntologyExtension"
    NO_SUITABLE_MAPPING = "custom:noSuitableMapping"
    REQUIRES_HUMAN_DECISION = "custom:requiresHumanDecision"


class SemanticWarning(BaseModel):
    warning_type: str
    description: str
    severity: Literal["info", "warning", "error"]
    model_config = {"frozen": False, "extra": "forbid"}


class OntologyMappingHypothesis(BaseModel):
    mapping_id: str
    evidence: list[Evidence] = Field(default_factory=list)
    counter_evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance
    reviewer_notes: list[str] = Field(default_factory=list)
    human_review_status: HumanReviewStatus = HumanReviewStatus.AWAITING_REVIEW
    validation_status: ValidationStatus = ValidationStatus.PENDING
    rank: int | None = None

    source_concept: SourceEntity
    target_ontology_entity: OntologyTerm
    ontology_relation: OntologyRelation
    source_entity_type: str
    target_entity_type: str
    semantic_scope_analysis: str
    hierarchy_compatibility: str
    domain_range_compatibility: str
    proposed_correction: str | None = None
    ontology_extension_required: bool = False
    ontology_extension_proposal: str | None = None
    semantic_warnings: list[SemanticWarning] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"frozen": False, "extra": "forbid"}

    def summary(self) -> str:
        return (
            f"{self.source_concept.entity_id} "
            f"--[{self.ontology_relation}]--> "
            f"{self.target_ontology_entity.term_id} "
            f"(conf={self.confidence:.2f})"
        )

    def __str__(self) -> str:
        return self.summary()
