from __future__ import annotations
import logging
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.review import AdversarialFlag, AdversarialReviewResult
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation

logger = logging.getLogger(__name__)


class SchemaAdversarialReviewerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "SchemaAdversarialReviewer"

    def review(self, hypothesis: FieldMappingHypothesis) -> AdversarialReviewResult:
        flags: list[AdversarialFlag] = []
        flags.extend(self._check_datatype_mismatch(hypothesis))
        flags.extend(self._check_information_loss(hypothesis))
        flags.extend(self._check_unmapped(hypothesis))
        flags.extend(self._check_ambiguous_source(hypothesis))
        flags.extend(self._check_unit_mismatch(hypothesis))
        flags.extend(self._check_low_confidence(hypothesis))

        severity = "clean"
        for f in flags:
            if f.severity == "high":
                severity = "high"
            elif f.severity == "medium" and severity != "high":
                severity = "medium"
            elif f.severity == "low" and severity == "clean":
                severity = "low"

        recommendation = "reject" if severity == "high" else ("review" if severity in ("medium", "low") else "proceed")

        return AdversarialReviewResult(
            mapping_id=hypothesis.mapping_id,
            flags=flags,
            overall_severity=severity,
            recommendation=recommendation,
        )

    def review_all(self, hypotheses: list[FieldMappingHypothesis]) -> dict[str, AdversarialReviewResult]:
        return {h.mapping_id: self.review(h) for h in hypotheses}

    def _check_datatype_mismatch(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        if h.source_datatype and h.target_datatype and h.source_datatype != h.target_datatype:
            if not ({h.source_datatype, h.target_datatype} <= {"number", "integer"}):
                return [AdversarialFlag(
                    flag_type="datatype_mismatch",
                    description=f"Type mismatch: source={h.source_datatype}, target={h.target_datatype}. Explicit conversion rule required.",
                    severity="medium",
                )]
        return []

    def _check_information_loss(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        if h.information_loss:
            return [AdversarialFlag(
                flag_type="information_loss",
                description=h.information_loss_description or "Information loss detected in this mapping.",
                severity="high",
            )]
        return []

    def _check_unmapped(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        if h.mapping_operation == MappingOperation.UNMAPPED:
            return [AdversarialFlag(
                flag_type="unmapped_field",
                description=f"Source field '{h.source_path}' has no suitable target mapping.",
                severity="medium",
            )]
        return []

    def _check_ambiguous_source(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        # Check for ActivityCount-style ambiguity
        if h.source_path and any(
            kw in h.source_path.lower() for kw in ["count", "index", "score"]
        ) and h.confidence < 0.70:
            return [AdversarialFlag(
                flag_type="ambiguous_measurement",
                description=(
                    f"Field '{h.source_path}' appears to be a measurement count or index. "
                    "Its definition, sampling context, and units require clarification before safe reuse."
                ),
                severity="medium",
            )]
        return []

    def _check_unit_mismatch(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        if h.unit_conversion:
            return [AdversarialFlag(
                flag_type="unit_conversion_required",
                description=f"Unit conversion required: {h.unit_conversion}. Verify conversion factor.",
                severity="medium",
            )]
        return []

    def _check_low_confidence(self, h: FieldMappingHypothesis) -> list[AdversarialFlag]:
        if h.confidence < 0.35:
            return [AdversarialFlag(
                flag_type="low_confidence",
                description=f"Confidence {h.confidence:.2f} is below minimum threshold of 0.35.",
                severity="medium",
            )]
        return []
