from __future__ import annotations
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class HumanReviewStatus(StrEnum):
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    PREDICATE_CHANGED = "predicate_changed"
    NEW_TERM_REQUESTED = "new_term_requested"


class AdversarialFlag(BaseModel):
    flag_type: str
    description: str
    severity: Literal["low", "medium", "high"]


class AdversarialReviewResult(BaseModel):
    mapping_id: str
    flags: list[AdversarialFlag] = Field(default_factory=list)
    overall_severity: Literal["clean", "low", "medium", "high"]
    recommendation: str

    def has_blocking_issues(self) -> bool:
        return self.overall_severity == "high"
