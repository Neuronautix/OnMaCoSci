from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel


class HumanReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CHANGE_PREDICATE = "change_predicate"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    CREATE_NEW_TERM = "create_new_ontology_term"


class SuggestedAction(BaseModel):
    action: HumanReviewAction
    reason: str
    suggested_predicate: str | None = None
