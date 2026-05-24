from __future__ import annotations
from pydantic import BaseModel, Field
from mapping_co_scientist.shared.models.review import ValidationStatus


class TermGapProposal(BaseModel):
    proposal_id: str
    source_concept_id: str
    source_concept_label: str
    proposed_term_label: str
    proposed_term_definition: str
    proposed_parent_term: str | None = None
    proposed_term_type: str = "class"
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: ValidationStatus = ValidationStatus.PENDING
    reviewer_notes: list[str] = Field(default_factory=list)
    model_config = {"frozen": False, "extra": "forbid"}
