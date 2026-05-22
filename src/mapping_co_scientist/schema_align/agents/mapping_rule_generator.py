from __future__ import annotations
import logging
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import TransformationRule, MappingOperation

logger = logging.getLogger(__name__)


class MappingRuleGeneratorAgent(BaseAgent):
    """Consolidates approved field mapping hypotheses into executable transformation rules."""

    @property
    def agent_name(self) -> str:
        return "MappingRuleGenerator"

    def generate_rules(
        self,
        hypotheses: list[FieldMappingHypothesis],
        approved_only: bool = False,
    ) -> list[TransformationRule]:
        """Extract TransformationRule objects from hypotheses."""
        rules = []
        from mapping_co_scientist.shared.models.review import HumanReviewStatus

        for h in hypotheses:
            if approved_only and h.human_review_status != HumanReviewStatus.APPROVED:
                continue
            if h.mapping_operation == MappingOperation.UNMAPPED:
                continue
            if h.transformation_rule is not None:
                rules.append(h.transformation_rule)

        self.log_step(f"Generated {len(rules)} transformation rules")
        return rules
