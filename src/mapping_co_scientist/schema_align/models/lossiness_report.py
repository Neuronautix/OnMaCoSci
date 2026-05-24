from __future__ import annotations
from pydantic import BaseModel, Field
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation


class LossyMapping(BaseModel):
    source_path: str
    target_path: str | None = None
    operation: MappingOperation
    loss_type: str  # "unmapped_field", "precision_loss", "context_loss", "aggregation_loss", "format_loss"
    description: str
    severity: str  # "info", "warning", "error"
    model_config = {"frozen": False, "extra": "forbid"}


class LossinessReport(BaseModel):
    pipeline_run_id: str
    total_source_fields: int
    mapped_fields: int
    unmapped_fields: int
    lossy_mappings: list[LossyMapping] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)

    @property
    def coverage_pct(self) -> float:
        if self.total_source_fields == 0:
            return 0.0
        return self.mapped_fields / self.total_source_fields * 100.0

    model_config = {"frozen": False, "extra": "forbid"}
