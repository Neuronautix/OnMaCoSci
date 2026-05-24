from __future__ import annotations
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field


class MappingOperation(StrEnum):
    DIRECT_COPY = "direct_copy"
    RENAME = "rename"
    NESTED_PATH = "nested_path"
    CONSTANT_ASSIGNMENT = "constant_assignment"
    DATATYPE_CONVERSION = "datatype_conversion"
    UNIT_CONVERSION = "unit_conversion"
    ENUMERATION_REMAPPING = "enumeration_remapping"
    CONCATENATION = "concatenation"
    SPLIT = "split"
    CONDITIONAL = "conditional"
    LOOKUP = "lookup"
    UNMAPPED = "unmapped"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class TransformationRule(BaseModel):
    rule_id: str
    source_path: str | None = None      # None for constant_assignment
    target_path: str
    operation: MappingOperation
    constant_value: Any = None           # for CONSTANT_ASSIGNMENT
    datatype_from: str | None = None
    datatype_to: str | None = None
    unit_from: str | None = None
    unit_to: str | None = None
    unit_conversion_factor: float | None = None
    enumeration_map: dict[str, str] = Field(default_factory=dict)
    expression: str | None = None       # e.g. a JSONata expression (future)
    condition: str | None = None        # for CONDITIONAL
    lookup_table: str | None = None     # reference to a lookup table
    notes: str | None = None
    information_loss: bool = False
    information_loss_description: str | None = None
    model_config = {"frozen": False, "extra": "forbid"}
