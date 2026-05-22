from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class SourceEntity(BaseModel):
    entity_id: str
    label: str
    description: str | None = None
    datatype: str | None = None
    examples: list[str] = Field(default_factory=list)
    source_file: str | None = None
    source_type: str
    extra_context: dict[str, Any] = Field(default_factory=dict)
    model_config = {"frozen": False, "extra": "forbid"}
