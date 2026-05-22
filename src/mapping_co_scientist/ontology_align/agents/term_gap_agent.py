from __future__ import annotations
import logging
import uuid
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation
)
from mapping_co_scientist.ontology_align.models.term_gap_proposal import TermGapProposal

logger = logging.getLogger(__name__)


class TermGapAgent(BaseAgent):
    """Identifies ontology gaps and proposes new terms for unmapped source concepts."""

    @property
    def agent_name(self) -> str:
        return "TermGapAgent"

    def identify_gaps(
        self,
        source_entities: list[SourceEntity],
        hypotheses: list[OntologyMappingHypothesis],
    ) -> list[TermGapProposal]:
        mapped_ids = {h.source_concept.entity_id for h in hypotheses
                      if h.ontology_relation != OntologyRelation.NO_SUITABLE_MAPPING
                      and h.confidence >= 0.40}

        proposals = []
        for entity in source_entities:
            if entity.entity_id not in mapped_ids:
                proposal = self._create_proposal(entity)
                proposals.append(proposal)

        self.log_step(f"Identified {len(proposals)} ontology gaps")
        return proposals

    def _create_proposal(self, entity: SourceEntity) -> TermGapProposal:
        return TermGapProposal(
            proposal_id=f"gap-{uuid.uuid4().hex[:8]}",
            source_concept_id=entity.entity_id,
            source_concept_label=entity.label,
            proposed_term_label=entity.label.replace("_", " ").title(),
            proposed_term_definition=(
                f"[Auto-generated stub] A term representing '{entity.label}' "
                f"from source '{entity.source_type}'. Definition requires expert review."
            ),
            rationale=(
                f"No suitable ontology term found for source concept '{entity.label}'. "
                "An ontology extension may be required."
            ),
            confidence=0.5,
        )
