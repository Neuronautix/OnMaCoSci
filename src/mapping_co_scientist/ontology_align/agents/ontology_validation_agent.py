from __future__ import annotations
import logging
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.review import ValidationStatus
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation, SemanticWarning
)

logger = logging.getLogger(__name__)


class OntologyValidationAgent(BaseAgent):
    """Runs semantic validation checks on ontology mapping hypotheses."""

    @property
    def agent_name(self) -> str:
        return "OntologyValidationAgent"

    def validate_all(self, hypotheses: list[OntologyMappingHypothesis]) -> list[OntologyMappingHypothesis]:
        for h in hypotheses:
            self._validate(h)
        return hypotheses

    def _validate(self, h: OntologyMappingHypothesis) -> None:
        issues = []

        if h.ontology_relation == OntologyRelation.EXACT_MATCH:
            if not any("exactMatch" in note.lower() or "exact" in note.lower() for note in h.reviewer_notes):
                issues.append("exactMatch proposed without explicit justification")

        if h.ontology_relation in (OntologyRelation.EQUIVALENT_CLASS, OntologyRelation.EQUIVALENT_PROPERTY):
            issues.append("owl:equivalentClass/Property must not be auto-generated; requires OWL engineer review")

        if h.confidence < 0.50 and h.ontology_relation in (
            OntologyRelation.EXACT_MATCH, OntologyRelation.CLOSE_MATCH
        ):
            issues.append(f"Confidence {h.confidence:.2f} too low for {h.ontology_relation}")

        if issues:
            h.validation_status = ValidationStatus.WARNING
            for issue in issues:
                if issue not in h.warnings:
                    h.warnings.append(f"[validation] {issue}")
        else:
            h.validation_status = ValidationStatus.PASSED
