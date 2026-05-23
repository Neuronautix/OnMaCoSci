from __future__ import annotations

import json
import logging
import re

from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.llm.provider_interface import LLMProviderInterface, LLMMessage
from mapping_co_scientist.shared.llm.prompt_templates import schema_field_scoring_prompt
from mapping_co_scientist.schema_align.agents.field_candidate_generator import FieldCandidateGeneratorAgent
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation
from mapping_co_scientist.shared.models.evidence import Evidence

logger = logging.getLogger(__name__)


class LLMSchemaFieldGenerator(BaseAgent):
    """Wraps the lexical field generator and re-scores candidates with LLM semantic analysis.

    The final confidence for each hypothesis is a weighted blend:
        blended = lexical_weight * lexical_conf + llm_weight * semantic_score

    If the LLM call fails or returns unparseable JSON the lexical scores are
    kept unchanged and a warning is logged.

    Constant-assignment hypotheses (source_path is None) are passed through
    unchanged — they are unit/default-value assignments that the LLM cannot
    meaningfully re-score.
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
        self._lexical_generator = FieldCandidateGeneratorAgent(
            top_k=top_k,
            pipeline_run_id=pipeline_run_id,
        )

    @property
    def agent_name(self) -> str:
        return "LLMSchemaFieldGenerator"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        source_fields,  # list[SchemaEntity]
        target_fields,  # list[SchemaEntity]
    ) -> list[FieldMappingHypothesis]:
        """Generate field mapping candidates with LLM-enhanced scoring."""
        lexical_hyps = self._lexical_generator.generate(source_fields, target_fields)

        # Separate constant-assignment hypotheses (source_path is None) — skip LLM for these
        constant_hyps = [h for h in lexical_hyps if h.source_path is None]
        scored_hyps = [h for h in lexical_hyps if h.source_path is not None]

        # Group non-constant hypotheses by source_path
        by_source: dict[str, list[FieldMappingHypothesis]] = {}
        for hyp in scored_hyps:
            by_source.setdefault(hyp.source_path, []).append(hyp)  # type: ignore[index]

        result: list[FieldMappingHypothesis] = []
        for src in source_fields:
            hyps = by_source.get(src.path, [])
            if not hyps:
                continue
            updated = self._rescore_with_llm(src, hyps)
            result.extend(updated)

        # Append constant-assignment hypotheses unchanged
        result.extend(constant_hyps)

        self.log_step(
            f"LLM-rescored {len(result) - len(constant_hyps)} hypotheses; "
            f"{len(constant_hyps)} constant assignments passed through unchanged"
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rescore_with_llm(
        self,
        src,  # SchemaEntity
        hyps: list[FieldMappingHypothesis],
    ) -> list[FieldMappingHypothesis]:
        """Call the LLM to rescore *hyps* for *src*, then blend and re-rank."""
        candidates = self._build_candidate_list(hyps)

        prompt_text = schema_field_scoring_prompt(
            source_path=src.path,
            source_datatype=src.datatype or "",
            source_description=src.description or "",
            candidates=candidates,
        )
        messages = [LLMMessage(role="user", content=prompt_text)]

        try:
            response = self.llm.complete(messages)
            llm_scores = self._parse_llm_response(response.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] LLM call failed for field '%s': %s — keeping lexical scores",
                self.agent_name,
                src.path,
                exc,
            )
            llm_scores = {}

        return self._apply_scores(hyps, llm_scores)

    def _build_candidate_list(
        self, hyps: list[FieldMappingHypothesis]
    ) -> list[dict]:
        """Serialise hypotheses into a compact representation for the LLM prompt."""
        candidates = []
        for hyp in hyps:
            lexical_score = next(
                (e.score for e in hyp.evidence if e.evidence_type == "lexical_similarity"),
                hyp.confidence,
            )
            candidates.append({
                "target_path": hyp.target_path,
                "target_datatype": hyp.target_datatype or "",
                "operation": hyp.mapping_operation.value,
                "lexical_score": round(lexical_score or 0.0, 4),
            })
        return candidates

    def _parse_llm_response(self, content: str) -> dict[str, dict]:
        """Parse the LLM JSON response into a dict keyed by target_path.

        Returns {} on any parse failure so callers can gracefully fall back.
        """
        try:
            data = json.loads(content.strip())
        except json.JSONDecodeError:
            # Try to extract a JSON array from the content (model sometimes wraps in prose)
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
            target_path = item.get("target_path")
            if not target_path:
                continue
            try:
                score = float(item.get("semantic_score", 0.0))
                score = max(0.0, min(1.0, score))
            except (TypeError, ValueError):
                score = 0.0
            result[target_path] = {
                "semantic_score": score,
                "operation": item.get("operation", ""),
                "rationale": item.get("rationale", ""),
                "valid": bool(item.get("valid", True)),
            }
        return result

    def _apply_scores(
        self,
        hyps: list[FieldMappingHypothesis],
        llm_scores: dict[str, dict],
    ) -> list[FieldMappingHypothesis]:
        """Blend LLM scores with lexical scores, update evidence, operations, and warnings."""
        for hyp in hyps:
            llm_info = llm_scores.get(hyp.target_path)

            lexical_conf = next(
                (e.score for e in hyp.evidence if e.evidence_type == "lexical_similarity"),
                hyp.confidence,
            ) or hyp.confidence

            if llm_info is not None:
                semantic_score = llm_info["semantic_score"]
                rationale = llm_info["rationale"]
                suggested_operation = llm_info["operation"]
                is_valid = llm_info["valid"]

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

                # If LLM flags the operation as invalid, add a warning
                if not is_valid:
                    hyp.warnings.append(
                        f"LLM flagged operation '{hyp.mapping_operation.value}' as invalid "
                        f"for {hyp.source_path} -> {hyp.target_path}. Rationale: {rationale}"
                    )

                # Update operation if LLM suggests a different valid one
                if suggested_operation and suggested_operation != hyp.mapping_operation.value:
                    try:
                        new_operation = MappingOperation(suggested_operation)
                    except ValueError:
                        logger.warning(
                            "[%s] Unknown operation '%s' suggested by LLM for %s -> %s",
                            self.agent_name,
                            suggested_operation,
                            hyp.source_path,
                            hyp.target_path,
                        )
                        new_operation = None

                    if new_operation is not None:
                        old_operation = hyp.mapping_operation
                        hyp.mapping_operation = new_operation
                        hyp.reviewer_notes.append(
                            f"LLM suggested operation change: {old_operation.value} -> "
                            f"{new_operation.value}. Rationale: {rationale}"
                        )

        # Re-rank within the group by blended confidence
        hyps.sort(key=lambda h: h.confidence, reverse=True)
        for i, hyp in enumerate(hyps):
            hyp.rank = i + 1

        return hyps
