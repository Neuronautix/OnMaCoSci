from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class SchemaEntity(BaseModel):
    """A field or path in a schema (source or target side)."""
    entity_id: str  # e.g. "csv:MouseID" or "json:animal.externalId"
    path: str       # e.g. "MouseID" or "animal.externalId"
    label: str      # human-readable name
    datatype: str | None = None  # "string", "number", "integer", "boolean", "array", "object"
    format: str | None = None    # "date", "datetime", "uri", "email", etc.
    unit: str | None = None      # e.g. "g", "kg", "mm"
    examples: list[str] = Field(default_factory=list)
    description: str | None = None
    required: bool = False
    nullable: bool = True
    enumeration: list[str] = Field(default_factory=list)  # allowed values
    source_file: str | None = None
    source_type: str = "unknown"  # "csv", "json_schema", "openapi", "json"
    extra_context: dict[str, Any] = Field(default_factory=dict)
    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        return f"SchemaEntity(path={self.path!r}, type={self.datatype!r})"
