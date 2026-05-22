from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class OntologyTerm(BaseModel):
    term_id: str
    label: str
    definition: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    parent_terms: list[str] = Field(default_factory=list)
    term_type: str
    ontology_id: str
    ontology_source: str | None = None
    extra_context: dict[str, Any] = Field(default_factory=dict)
    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        return f"OntologyTerm(id={self.term_id!r}, label={self.label!r})"
