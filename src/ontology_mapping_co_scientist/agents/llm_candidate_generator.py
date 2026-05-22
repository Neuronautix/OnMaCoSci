"""
LLM-backed candidate generator agent for the Ontology Mapping Co-Scientist system.

Augments lexical candidate generation with LLM-based semantic similarity scoring.
For each source entity, sends a prompt to Claude asking it to score how well each
top lexical candidate matches semantically. The LLM score becomes an additional
Evidence object layered on top of the lexical score.

Falls back to pure lexical generation when no LLM client is available.

Usage:
    # Lexical-only (no API key needed):
    agent = LLMCandidateGeneratorAgent()

    # With LLM:
    import anthropic
    client = anthropic.Anthropic()
    agent = LLMCandidateGeneratorAgent(llm_client=client)

    # Or via environment variable auto-init:
    agent = LLMCandidateGeneratorAgent.from_env()
"""

from __future__ import annotations

import json
import logging
import os
import time

from ontology_mapping_co_scientist.agents.candidate_generator import (
    CandidateGeneratorAgent,
)
from ontology_mapping_co_scientist.env import load_dotenv
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
)
from ontology_mapping_co_scientist.prompts.templates import get_prompt_hash
from ontology_mapping_co_scientist.scoring.evidence_scoring import (
    compute_aggregate_confidence,
)

logger = logging.getLogger(__name__)

_AGENT_NAME = "LLMCandidateGeneratorAgent"


class LLMCandidateGeneratorAgent:
    """Augments lexical candidate generation with LLM-based semantic similarity scoring.

    For each source entity, sends a prompt to Claude asking it to score how well
    each top lexical candidate matches semantically. The LLM score becomes an
    additional Evidence object layered on top of the lexical score.

    Falls back to pure lexical generation when no LLM client is available.

    Args:
        llm_client: An initialised :class:`anthropic.Anthropic` client, or
            ``None`` to use the lexical fallback only.
        model: The Claude model ID to use for scoring.
        max_tokens: Maximum number of tokens the model may generate per call.
        fallback_to_lexical: When ``True`` (default), falls back to the lexical
            generator when ``llm_client`` is ``None`` or on API error.
        top_k_for_llm: Only send the top N lexical candidates to the LLM to
            save tokens. Candidates ranked below this threshold are returned
            with lexical evidence only.
        cost_tracker: Optional :class:`~.llm_cost_tracker.LLMCostTracker` to
            record token usage and estimated cost.
    """

    def __init__(
        self,
        llm_client=None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 512,
        fallback_to_lexical: bool = True,
        top_k_for_llm: int = 3,
        max_entities_for_llm: int | None = None,
        call_delay_seconds: float = 0.5,
        cost_tracker=None,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_tokens = max_tokens
        self.fallback_to_lexical = fallback_to_lexical
        self.top_k_for_llm = top_k_for_llm
        self.max_entities_for_llm = max_entities_for_llm
        self.call_delay_seconds = call_delay_seconds
        self.cost_tracker = cost_tracker
        self.llm_entities_scored = 0
        self.llm_disabled_reason: str | None = None

        # Always instantiate a lexical generator as the base layer
        self._lexical_generator = CandidateGeneratorAgent(top_k=5)

        if llm_client is None:
            logger.info(
                "%s: no LLM client provided — using lexical-only generation.",
                _AGENT_NAME,
            )

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        model: str = "claude-haiku-4-5-20251001",
        cost_tracker=None,
    ) -> "LLMCandidateGeneratorAgent":
        """Construct an agent, auto-detecting an API key from the environment.

        Tries to import the ``anthropic`` package and instantiate an
        :class:`anthropic.Anthropic` client.  If either the package is not
        installed or the ``ANTHROPIC_API_KEY`` environment variable is not set,
        the constructor falls back to the lexical-only generator.

        Args:
            model: The Claude model ID to use.
            cost_tracker: Optional cost tracker.

        Returns:
            A fully initialised :class:`LLMCandidateGeneratorAgent`.
        """
        load_dotenv()
        try:
            import anthropic  # noqa: PLC0415

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ValueError("ANTHROPIC_API_KEY is not set")
            max_retries = int(os.environ.get("OMCS_LLM_MAX_RETRIES", "0"))
            client = anthropic.Anthropic(max_retries=max_retries)
            call_delay_seconds = float(os.environ.get("OMCS_LLM_CALL_DELAY_SECONDS", "0.5"))
            max_entities_raw = os.environ.get("OMCS_LLM_MAX_CANDIDATE_ENTITIES")
            max_entities_for_llm = int(max_entities_raw) if max_entities_raw else None
            top_k_for_llm = int(os.environ.get("OMCS_LLM_CANDIDATE_TOP_K", "3"))
            logger.info(
                "%s.from_env: ANTHROPIC_API_KEY found — LLM mode activated (model=%s).",
                _AGENT_NAME,
                model,
            )
            return cls(
                llm_client=client,
                model=model,
                top_k_for_llm=top_k_for_llm,
                max_entities_for_llm=max_entities_for_llm,
                call_delay_seconds=call_delay_seconds,
                cost_tracker=cost_tracker,
            )
        except ImportError:
            logger.warning(
                "%s.from_env: 'anthropic' package not installed. "
                "Falling back to lexical-only generation.",
                _AGENT_NAME,
            )
        except Exception as exc:  # covers AuthenticationError and missing key
            logger.warning(
                "%s.from_env: Could not initialise Anthropic client (%s: %s). "
                "Falling back to lexical-only generation.",
                _AGENT_NAME,
                type(exc).__name__,
                exc,
            )
        return cls(llm_client=None, fallback_to_lexical=True, model=model, cost_tracker=cost_tracker)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        source_entities: list[SourceEntity],
        ontology_terms: list[OntologyTerm],
        pipeline_run_id: str | None = None,
    ) -> list[MappingHypothesis]:
        """Generate mapping hypothesis candidates, augmented with LLM scoring.

        For each source entity:

        1. Runs lexical candidate generation via the base
           :class:`CandidateGeneratorAgent`.
        2. Groups hypotheses by source entity ID.
        3. For each source entity, takes the top :attr:`top_k_for_llm` candidates.
        4. If ``llm_client`` is available, calls the LLM to get semantic scores
           for the top candidates and merges these as additional Evidence objects.
        5. Recomputes confidence after adding LLM evidence.
        6. Returns all hypotheses.

        Args:
            source_entities: Source entities to map.
            ontology_terms: The complete pool of candidate ontology terms.
            pipeline_run_id: Optional pipeline run identifier.

        Returns:
            A flat list of :class:`MappingHypothesis` objects.
        """
        # Step 1: Get lexical candidates
        hypotheses = self._lexical_generator.generate_candidates(
            source_entities=source_entities,
            ontology_terms=ontology_terms,
            pipeline_run_id=pipeline_run_id,
        )

        if self.llm_client is None:
            logger.debug("%s: no LLM client, returning lexical-only candidates.", _AGENT_NAME)
            return hypotheses

        # Step 2: Group by source entity id
        by_entity: dict[str, list[MappingHypothesis]] = {}
        for h in hypotheses:
            by_entity.setdefault(h.source_entity.entity_id, []).append(h)

        # Step 3 & 4: Score top candidates per entity
        scored_entities = 0
        for index, (entity_id, entity_hypotheses) in enumerate(by_entity.items()):
            if self.llm_disabled_reason is not None:
                logger.warning(
                    "%s: LLM candidate scoring disabled for remaining entities: %s",
                    _AGENT_NAME,
                    self.llm_disabled_reason,
                )
                break

            if (
                self.max_entities_for_llm is not None
                and scored_entities >= self.max_entities_for_llm
            ):
                logger.info(
                    "%s: LLM candidate budget reached (%d entities); remaining "
                    "entities use lexical-only evidence.",
                    _AGENT_NAME,
                    self.max_entities_for_llm,
                )
                break

            if index > 0 and self.call_delay_seconds > 0:
                time.sleep(self.call_delay_seconds)

            # Sort by current confidence descending, take top_k_for_llm
            sorted_hyps = sorted(entity_hypotheses, key=lambda h: h.confidence, reverse=True)
            top_candidates = sorted_hyps[: self.top_k_for_llm]

            if not top_candidates:
                continue

            source_entity = top_candidates[0].source_entity
            llm_scores = self._llm_score_candidates(source_entity, top_candidates)

            if not llm_scores:
                continue

            scored_entities += 1
            # Step 5: Merge LLM evidence and recompute confidence
            for h in top_candidates:
                term_id = h.target_entity.term_id
                if term_id not in llm_scores:
                    continue
                llm_score, rationale = llm_scores[term_id]
                target_label = h.target_entity.label

                llm_ev = Evidence(
                    evidence_type="llm_semantic_similarity",
                    description=(
                        f"LLM score for {target_label}: {llm_score:.2f} — {rationale}"
                    ),
                    score=llm_score,
                    source=f"anthropic/{self.model}",
                )
                h.evidence.append(llm_ev)
                h.confidence = compute_aggregate_confidence(h.evidence, h.counter_evidence)

        logger.info(
            "%s: LLM scoring complete for %d/%d source entities.",
            _AGENT_NAME,
            scored_entities,
            len(by_entity),
        )
        self.llm_entities_scored = scored_entities
        return hypotheses

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_scoring_prompt(
        self,
        source_entity: SourceEntity,
        candidates: list[MappingHypothesis],
    ) -> str:
        """Build a prompt asking the LLM to score each candidate's semantic match.

        Args:
            source_entity: The source entity being mapped.
            candidates: The top-N lexical candidates to score.

        Returns:
            A string prompt ready to be sent as the user message.
        """
        examples_str = (
            ", ".join(str(e) for e in source_entity.examples)
            if source_entity.examples
            else "none"
        )

        candidates_text_parts: list[str] = []
        for i, h in enumerate(candidates, start=1):
            tgt = h.target_entity
            syns = ", ".join(tgt.synonyms[:3]) if tgt.synonyms else "none"
            candidates_text_parts.append(
                f"  {i}. term_id={tgt.term_id!r}\n"
                f"     label={tgt.label!r}\n"
                f"     definition={tgt.definition or 'none'!r}\n"
                f"     synonyms={syns}\n"
                f"     current_predicate={h.predicate.value}"
            )
        candidates_text = "\n".join(candidates_text_parts)

        return (
            "You are a semantic similarity expert scoring ontology mapping candidates.\n"
            "\n"
            "SOURCE FIELD:\n"
            f"- ID: {source_entity.entity_id}\n"
            f"- Label: {source_entity.label}\n"
            f"- Description: {source_entity.description or 'none provided'}\n"
            f"- Datatype: {source_entity.datatype or 'unknown'}\n"
            f"- Examples: {examples_str}\n"
            "\n"
            "CANDIDATE ONTOLOGY TERMS:\n"
            f"{candidates_text}\n"
            "\n"
            "For each candidate, provide a semantic similarity score from 0.0 to 1.0\n"
            "indicating how well the source field semantically matches the ontology term.\n"
            "A score of 1.0 means the concepts are identical; 0.0 means completely unrelated.\n"
            "\n"
            "Respond in this EXACT JSON format (no markdown, raw JSON only):\n"
            '{"scores": [\n'
            '  {"term_id": "...", "score": 0.0, "rationale": "one sentence"}\n'
            "]}\n"
            "\n"
            "Include one entry per candidate in the same order listed above."
        )

    def _parse_scoring_response(
        self,
        response_text: str,
        candidates: list[MappingHypothesis],
    ) -> dict[str, tuple[float, str]]:
        """Parse the LLM scoring response into a term_id -> (score, rationale) dict.

        Strips markdown fences if present. On JSON parse errors or structural
        issues, logs a warning and returns an empty dict so the pipeline can
        continue without LLM augmentation.

        Args:
            response_text: Raw text from the LLM content block.
            candidates: The candidates that were scored (used for term_id validation).

        Returns:
            Dict mapping term_id to ``(llm_score, rationale)`` tuples.
        """
        text = response_text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            inner_lines = []
            skip_first = True
            for line in lines:
                if skip_first:
                    skip_first = False
                    continue
                if line.strip() == "```":
                    break
                inner_lines.append(line)
            text = "\n".join(inner_lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "%s: JSON parse error in scoring response: %s",
                _AGENT_NAME,
                exc,
            )
            return {}

        scores: dict[str, tuple[float, str]] = {}
        valid_term_ids = {h.target_entity.term_id for h in candidates}

        for entry in data.get("scores", []):
            try:
                term_id = str(entry.get("term_id", ""))
                if term_id not in valid_term_ids:
                    logger.debug(
                        "%s: unknown term_id '%s' in LLM response; skipping.",
                        _AGENT_NAME,
                        term_id,
                    )
                    continue
                raw_score = entry.get("score", 0.0)
                # Clamp to [0.0, 1.0]
                llm_score = max(0.0, min(1.0, float(raw_score)))
                rationale = str(entry.get("rationale", "No rationale provided."))
                scores[term_id] = (llm_score, rationale)
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: could not parse score entry %r: %s", _AGENT_NAME, entry, exc)

        return scores

    def _llm_score_candidates(
        self,
        source_entity: SourceEntity,
        candidates: list[MappingHypothesis],
    ) -> dict[str, tuple[float, str]]:
        """Build prompt, call the LLM, and parse the scoring response.

        On any error (API or parse), logs a warning and returns an empty dict
        so the pipeline can continue with lexical-only evidence.

        Args:
            source_entity: The source entity being scored against.
            candidates: Top-N lexical candidates to score.

        Returns:
            Dict mapping term_id to ``(llm_score, rationale)`` tuples, or
            empty dict on error.
        """
        prompt = self._build_scoring_prompt(source_entity, candidates)
        try:
            response = self.llm_client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.content[0].text

            # Record token usage if a cost tracker is available
            if self.cost_tracker is not None:
                try:
                    self.cost_tracker.record(
                        agent_name=_AGENT_NAME,
                        model=self.model,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                    )
                except Exception as tracker_exc:  # noqa: BLE001
                    logger.debug(
                        "%s: cost tracker error: %s", _AGENT_NAME, tracker_exc
                    )

            # Record prompt hash in the hypothesis provenance (first candidate only)
            prompt_hash = get_prompt_hash(prompt)
            for h in candidates:
                h.provenance.extra["llm_prompt_hash"] = prompt_hash

            return self._parse_scoring_response(response_text, candidates)

        except Exception as exc:  # noqa: BLE001
            if _is_provider_overloaded(exc):
                self.llm_disabled_reason = (
                    "provider overloaded; stopped further candidate-scoring calls"
                )
            logger.warning(
                "%s: API error scoring candidates for entity '%s' (%s: %s).",
                _AGENT_NAME,
                source_entity.entity_id,
                type(exc).__name__,
                exc,
            )
            return {}


def _is_provider_overloaded(exc: Exception) -> bool:
    """Return whether an LLM exception indicates provider overload."""
    status_code = getattr(exc, "status_code", None)
    return status_code == 529 or type(exc).__name__ == "OverloadedError"
