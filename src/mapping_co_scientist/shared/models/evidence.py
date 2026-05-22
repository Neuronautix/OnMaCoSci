from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    evidence_type: str
    description: str
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = None
    model_config = {"frozen": False, "extra": "forbid"}


class Provenance(BaseModel):
    created_by: str
    created_at: str
    method: str
    pipeline_run_id: str | None = None
    extra: dict[str, Any] = {}
    model_config = {"frozen": False, "extra": "forbid"}
