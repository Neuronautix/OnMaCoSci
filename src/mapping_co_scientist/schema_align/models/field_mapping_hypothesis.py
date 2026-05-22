from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from mapping_co_scientist.shared.models.evidence import Evidence, Provenance
from mapping_co_scientist.shared.models.review import ValidationStatus, HumanReviewStatus
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.models.transformation_rule import TransformationRule, MappingOperation


class CardinalityRelation(BaseModel):
    source_cardinality: str  # "1", "0..1", "1..*", "0..*"
    target_cardinality: str
    note: str | None = None
    model_config = {"frozen": False, "extra": "forbid"}


class FieldMappingHypothesis(BaseModel):
    # --- Shared base fields ---
    mapping_id: str
    evidence: list[Evidence] = Field(default_factory=list)
    counter_evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance
    reviewer_notes: list[str] = Field(default_factory=list)
    human_review_status: HumanReviewStatus = HumanReviewStatus.AWAITING_REVIEW
    validation_status: ValidationStatus = ValidationStatus.PENDING
    rank: int | None = None
    warnings: list[str] = Field(default_factory=list)

    # --- Schema-specific fields ---
    source_path: str | None = None           # None for unmapped or constant targets
    target_path: str
    mapping_operation: MappingOperation
    source_datatype: str | None = None
    target_datatype: str | None = None
    cardinality_relation: CardinalityRelation | None = None
    transformation_required: bool = False
    transformation_expression: str | None = None
    unit_conversion: str | None = None       # e.g. "g -> kg (factor: 0.001)"
    enumeration_mapping: dict[str, str] = Field(default_factory=dict)
    missing_value_policy: str | None = None  # "null", "omit", "default:<value>"
    information_loss: bool = False
    information_loss_description: str | None = None
    executable_test_status: str = "not_tested"  # "not_tested", "passed", "failed"
    transformation_rule: TransformationRule | None = None

    model_config = {"frozen": False, "extra": "forbid"}

    def summary(self) -> str:
        src = self.source_path or "<constant>"
        return (
            f"{src} -> {self.target_path} "
            f"[{self.mapping_operation}] "
            f"(conf={self.confidence:.2f})"
        )

    def __str__(self) -> str:
        return self.summary()
