from __future__ import annotations

import json
import logging

from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.llm.provider_interface import LLMProviderInterface, LLMMessage
from mapping_co_scientist.shared.llm.prompt_templates import ontology_candidate_scoring_prompt
from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import (
    SemanticCandidateGeneratorAgent,
)
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis,
    OntologyRelation,
)
from mapping_co_scientist.shared.models.evidence import Evidence

logger = logging.getLogger(__name__)


class LLMOntologyCandidateGenerator(BaseAgent):
    """Wraps the lexical generator and re-scores candidates with LLM semantic analysis.

    The final confidence for each hypothesis is a weighted blend:
        blended = lexical_weight * lexical_conf + llm_weight * semantic_score

    If the LLM call fails or returns unparseable JSON the lexical scores are
    kept unchanged and a warning is logged.
    """

    def __init__(
        self,
        llm: LLMProviderInterface,
        top_k: int = 3,
        pipeline_run_id: str = "",
        lexical_weight: float = 0.4,
        llm_weight: float = 0.6,
    ) -> None:
        self.llm = llm
        self.top_k = top_k
        self.pipeline_run_id = pipeline_run_id
        self.lexical_weight = lexical_weight
        self.llm_weight = llm_weight
        self._lexical_generator = SemanticCandidateGeneratorAgent(
            top_k=top_k,
            pipeline_run_id=pipeline_run_id,
        )

    @property
    def agent_name(self) -> str:
        return "LLMOntologyCandidateGenerator"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        source_entities,  # list[SourceEntity]
        ontology_terms,   # list[OntologyTerm]
    ) -> list[OntologyMappingHypothesis]:
        """Generate ontology mapping candidates with LLM-enhanced scoring."""
        lexical_hyps = self._lexical_generator.generate(source_entities, ontology_terms)

        # Group hypotheses by source entity id
        by_source: dict[str, list[OntologyMappingHypothesis]] = {}
        for hyp in lexical_hyps:
            sid = hyp.source_concept.entity_id
            by_source.setdefault(sid, []).append(hyp)

        result: list[OntologyMappingHypothesis] = []
        for entity in source_entities:
            hyps = by_source.get(entity.entity_id, [])
            if not hyps:
                continue
            updated = self._rescore_with_llm(entity, hyps)
            result.extend(updated)

        self.log_step(
            f"LLM-rescored {len(result)} hypotheses for {len(source_entities)} entities"
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rescore_with_llm(
        self,
        entity,  # SourceEntity
        hyps: list[OntologyMappingHypothesis],
    ) -> list[OntologyMappingHypothesis]:
        """Call the LLM to rescore *hyps* for *entity*, then blend and re-rank."""
        candidates = self._build_candidate_list(hyps)

        prompt_text = ontology_candidate_scoring_prompt(
            source_label=entity.label,
            source_type=getattr(entity, "source_type", "field"),
            source_description=entity.description or "",
            candidates=candidates,
        )
        messages = [LLMMessage(role="user", content=prompt_text)]

        try:
            response = self.llm.complete(messages)
            llm_scores = self._parse_llm_response(response.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] LLM call failed for entity '%s': %s — keeping lexical scores",
                self.agent_name,
                entity.label,
                exc,
            )
            llm_scores = {}

        return self._apply_scores(hyps, llm_scores)

    def _build_candidate_list(
        self, hyps: list[OntologyMappingHypothesis]
    ) -> list[dict]:
        """Serialise hypotheses into a compact representation for the LLM prompt."""
        candidates = []
        for hyp in hyps:
            term = hyp.target_ontology_entity
            # Lexical evidence score (first evidence item is always the lexical one)
            lexical_score = next(
                (e.score for e in hyp.evidence if e.evidence_type == "lexical_similarity"),
                hyp.confidence,
            )
            candidates.append({
                "term_id": term.term_id,
                "label": term.label,
                "definition": term.definition or "",
                "relation": hyp.ontology_relation.value,
                "lexical_score": round(lexical_score or 0.0, 4),
            })
        return candidates

    def _parse_llm_response(self, content: str) -> dict[str, dict]:
        """Parse the LLM JSON response into a dict keyed by term_id.

        Returns {} on any parse failure so callers can gracefully fall back.
        """
        try:
            data = json.loads(content.strip())
        except json.JSONDecodeError:
            # Try to extract a JSON array from the content (model sometimes wraps in prose)
            import re
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.warning("[%s] Could not parse LLM response as JSON", self.agent_name)
                    return {}
            else:
                logger.warning("[%s] No JSON array found in LLM response", self.agent_name)
                return {}

        if not isinstance(data, list):
            logger.warning("[%s] LLM response is not a JSON array", self.agent_name)
            return {}

        result: dict[str, dict] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            term_id = item.get("term_id")
            if not term_id:
                continue
            try:
                score = float(item.get("semantic_score", 0.0))
                score = max(0.0, min(1.0, score))
            except (TypeError, ValueError):
                score = 0.0
            result[term_id] = {
                "semantic_score": score,
                "relation": item.get("relation", ""),
                "rationale": item.get("rationale", ""),
            }
        return result

    def _apply_scores(
        self,
        hyps: list[OntologyMappingHypothesis],
        llm_scores: dict[str, dict],
    ) -> list[OntologyMappingHypothesis]:
        """Blend LLM scores with lexical scores, update evidence and relations."""
        for hyp in hyps:
            term_id = hyp.target_ontology_entity.term_id
            llm_info = llm_scores.get(term_id)

            lexical_conf = next(
                (e.score for e in hyp.evidence if e.evidence_type == "lexical_similarity"),
                hyp.confidence,
            ) or hyp.confidence

            if llm_info is not None:
                semantic_score = llm_info["semantic_score"]
                rationale = llm_info["rationale"]
                suggested_relation = llm_info["relation"]

                blended = (
                    self.lexical_weight * lexical_conf
                    + self.llm_weight * semantic_score
                )
                blended = max(0.0, min(1.0, blended))
                hyp.confidence = blended

                # Add LLM evidence
                hyp.evidence.append(Evidence(
                    evidence_type="llm_semantic_score",
                    description=rationale,
                    score=semantic_score,
                    source=self.llm.model_name,
                ))

                # Update relation if LLM suggests a different one
                if suggested_relation and suggested_relation != hyp.ontology_relation.value:
                    try:
                        new_relation = OntologyRelation(suggested_relation)
                    except ValueError:
                        logger.warning(
                            "[%s] Unknown relation '%s' suggested by LLM for %s",
                            self.agent_name,
                            suggested_relation,
                            term_id,
                        )
                        new_relation = None

                    if new_relation is not None:
                        old_relation = hyp.ontology_relation
                        hyp.ontology_relation = new_relation
                        hyp.reviewer_notes.append(
                            f"LLM suggested relation change: {old_relation.value} -> "
                            f"{new_relation.value}. Rationale: {rationale}"
                        )

        # Re-rank within the group by blended confidence
        hyps.sort(key=lambda h: h.confidence, reverse=True)
        for i, hyp in enumerate(hyps):
            hyp.rank = i + 1

        return hyps
