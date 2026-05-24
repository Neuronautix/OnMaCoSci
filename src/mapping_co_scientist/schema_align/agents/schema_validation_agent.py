from __future__ import annotations

import logging

from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.review import ValidationStatus

logger = logging.getLogger(__name__)


class SchemaValidationAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "SchemaValidationAgent"

    def validate_all(self, hypotheses: list[FieldMappingHypothesis]) -> list[FieldMappingHypothesis]:
        for h in hypotheses:
            self._validate(h)
        return hypotheses

    def _validate(self, h: FieldMappingHypothesis) -> None:
        issues = []

        # datatype conversion without a rule
        if (
            h.mapping_operation == MappingOperation.DATATYPE_CONVERSION
            and (h.transformation_rule is None or h.transformation_rule.expression is None)
        ):
            issues.append("DATATYPE_CONVERSION requires a transformation expression")

        # information loss must be flagged
        if h.information_loss:
            description = h.information_loss_description or "Information loss flagged without description"
            issues.append(f"Information loss: {description}")

        if issues:
            h.validation_status = ValidationStatus.WARNING
            for issue in issues:
                if issue not in h.warnings:
                    h.warnings.append(f"[validation] {issue}")
        else:
            h.validation_status = ValidationStatus.PASSED
