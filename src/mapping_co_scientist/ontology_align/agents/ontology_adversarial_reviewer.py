from __future__ import annotations
import logging
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.review import AdversarialFlag, AdversarialReviewResult
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation
)

logger = logging.getLogger(__name__)


class OntologyAdversarialReviewerAgent(BaseAgent):
    """Reviews ontology mapping hypotheses for semantic correctness issues."""

    @property
    def agent_name(self) -> str:
        return "OntologyAdversarialReviewer"

    def review(self, hypothesis: OntologyMappingHypothesis) -> AdversarialReviewResult:
        flags: list[AdversarialFlag] = []

        flags.extend(self._check_exactmatch_overreach(hypothesis))
        flags.extend(self._check_equivalentclass_overreach(hypothesis))
        flags.extend(self._check_low_confidence(hypothesis))
        flags.extend(self._check_missing_definition(hypothesis))
        flags.extend(self._check_type_compatibility(hypothesis))
        flags.extend(self._check_semantic_warnings(hypothesis))

        severity = "clean"
        for f in flags:
            if f.severity == "high" and severity not in ("high",):
                severity = "high"
            elif f.severity == "medium" and severity not in ("high",):
                severity = "medium"
            elif f.severity == "low" and severity == "clean":
                severity = "low"

        if severity == "high":
            recommendation = "reject"
        elif severity in ("medium", "low"):
            recommendation = "review"
        else:
            recommendation = "proceed"

        return AdversarialReviewResult(
            mapping_id=hypothesis.mapping_id,
            flags=flags,
            overall_severity=severity,
            recommendation=recommendation,
        )

    def review_all(self, hypotheses: list[OntologyMappingHypothesis]) -> dict[str, AdversarialReviewResult]:
        return {h.mapping_id: self.review(h) for h in hypotheses}

    def _check_exactmatch_overreach(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        if h.ontology_relation == OntologyRelation.EXACT_MATCH:
            return [AdversarialFlag(
                flag_type="exactmatch_requires_validation",
                description=(
                    "skos:exactMatch implies full semantic interchangeability. "
                    "This requires explicit ontology engineer validation beyond lexical similarity. "
                    "Recommend downgrading to skos:closeMatch pending expert review."
                ),
                severity="high",
            )]
        return []

    def _check_equivalentclass_overreach(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        if h.ontology_relation in (OntologyRelation.EQUIVALENT_CLASS, OntologyRelation.EQUIVALENT_PROPERTY):
            return [AdversarialFlag(
                flag_type="owl_equivalence_overreach",
                description=(
                    f"owl:equivalentClass/Property is a very strong logical claim. "
                    "It requires formal ontology review and explicit justification. "
                    "This should not be asserted without OWL reasoning support."
                ),
                severity="high",
            )]
        return []

    def _check_low_confidence(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        if h.confidence < 0.40:
            return [AdversarialFlag(
                flag_type="low_confidence",
                description=f"Confidence {h.confidence:.2f} is below 0.40 threshold. Mapping is speculative.",
                severity="medium",
            )]
        return []

    def _check_missing_definition(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        if not h.target_ontology_entity.definition:
            return [AdversarialFlag(
                flag_type="missing_ontology_definition",
                description=(
                    f"Target term '{h.target_ontology_entity.term_id}' lacks a formal definition. "
                    "Semantic validation cannot be performed without a definition."
                ),
                severity="low",
            )]
        return []

    def _check_type_compatibility(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        flags = []
        if h.source_entity_type == "measurement" and h.target_entity_type == "class":
            flags.append(AdversarialFlag(
                flag_type="measurement_to_class_mismatch",
                description=(
                    "Source appears to be a measurement/value but target is an ontology class. "
                    "Consider whether target should be an object property or data property."
                ),
                severity="medium",
            ))
        if h.source_entity_type == "identifier" and h.target_entity_type == "class":
            flags.append(AdversarialFlag(
                flag_type="identifier_to_class_mismatch",
                description=(
                    "Source is an identifier field but target is an ontology class. "
                    "Identifiers typically map to annotation properties or data properties, not classes."
                ),
                severity="medium",
            ))
        return flags

    def _check_semantic_warnings(self, h: OntologyMappingHypothesis) -> list[AdversarialFlag]:
        return [
            AdversarialFlag(
                flag_type=f"semantic_warning_{w.warning_type}",
                description=w.description,
                severity={"info": "low", "warning": "medium", "error": "high"}.get(w.severity, "medium"),
            )
            for w in h.semantic_warnings
        ]
