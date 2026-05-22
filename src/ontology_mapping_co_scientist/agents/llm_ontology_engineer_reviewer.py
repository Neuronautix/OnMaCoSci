"""
LLM-backed ontology engineer reviewer for the Ontology Mapping Co-Scientist system.

Reviews mapping hypotheses for logical consistency from an ontology engineering
perspective: predicate appropriateness, class/property compatibility,
hierarchy placement, and domain/range constraints.

Falls back to a no-op result (empty flags, "proceed") when no LLM client.

Usage:
    # No-op fallback (no API key needed):
    reviewer = LLMOntologyEngineerReviewerAgent()

    # With LLM:
    import anthropic
    client = anthropic.Anthropic()
    reviewer = LLMOntologyEngineerReviewerAgent(llm_client=client)

    # Or via environment variable auto-init:
    reviewer = LLMOntologyEngineerReviewerAgent.from_env()
"""

from __future__ import annotations

import json
import logging
import os
import time

from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
    _compute_overall_severity,
    _derive_recommendation,
)
from ontology_mapping_co_scientist.env import load_dotenv
from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis
from ontology_mapping_co_scientist.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
)
from ontology_mapping_co_scientist.prompts.templates import get_prompt_hash

logger = logging.getLogger(__name__)

_AGENT_NAME = "LLMOntologyEngineerReviewerAgent"


class LLMOntologyEngineerReviewerAgent:
    """Reviews mapping hypotheses for logical consistency from an ontology engineering perspective.

    Checks predicate appropriateness, class/property compatibility,
    hierarchy placement, and domain/range constraints.

    Falls back to a no-op result (empty flags, "proceed") when no LLM client.

    Args:
        llm_client: An initialised :class:`anthropic.Anthropic` client, or
            ``None`` to use the no-op fallback.
        model: The Claude model ID to use for reviews.
        max_tokens: Maximum number of tokens the model may generate per review.
        cost_tracker: Optional :class:`~.llm_cost_tracker.LLMCostTracker` to
            record token usage and estimated cost.
    """

    def __init__(
        self,
        llm_client=None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 768,
        cost_tracker=None,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_tokens = max_tokens
        self.cost_tracker = cost_tracker

        if llm_client is None:
            logger.info(
                "%s: no LLM client provided — using no-op fallback.",
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
    ) -> "LLMOntologyEngineerReviewerAgent":
        """Construct an agent, auto-detecting an API key from the environment.

        Args:
            model: The Claude model ID to use.
            cost_tracker: Optional cost tracker.

        Returns:
            A fully initialised :class:`LLMOntologyEngineerReviewerAgent`.
        """
        load_dotenv()
        try:
            import anthropic  # noqa: PLC0415

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ValueError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic()
            logger.info(
                "%s.from_env: ANTHROPIC_API_KEY found — LLM mode activated (model=%s).",
                _AGENT_NAME,
                model,
            )
            return cls(llm_client=client, model=model, cost_tracker=cost_tracker)
        except ImportError:
            logger.warning(
                "%s.from_env: 'anthropic' package not installed. "
                "Falling back to no-op reviewer.",
                _AGENT_NAME,
            )
        except Exception as exc:  # covers AuthenticationError and missing key
            logger.warning(
                "%s.from_env: Could not initialise Anthropic client (%s: %s). "
                "Falling back to no-op reviewer.",
                _AGENT_NAME,
                type(exc).__name__,
                exc,
            )
        return cls(llm_client=None, model=model, cost_tracker=cost_tracker)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def review_hypothesis(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Review a single mapping hypothesis from an ontology engineering perspective.

        Returns a no-op clean result when no LLM client is available.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`AdversarialReviewResult` with flags and recommendation.
        """
        if self.llm_client is None:
            return AdversarialReviewResult(
                mapping_id=hypothesis.mapping_id,
                flags=[],
                overall_severity="clean",
                recommendation="proceed",
            )
        return self._llm_review(hypothesis)

    def review_all(
        self, hypotheses: list[MappingHypothesis]
    ) -> list[AdversarialReviewResult]:
        """Review all hypotheses in *hypotheses*.

        When using the LLM, a small delay of 0.1 s is inserted between calls
        to reduce the risk of hitting rate limits.

        Args:
            hypotheses: The mapping hypotheses to review.

        Returns:
            A list of :class:`AdversarialReviewResult` in the same order as
            *hypotheses*.
        """
        results: list[AdversarialReviewResult] = []
        use_llm = self.llm_client is not None

        for i, hypothesis in enumerate(hypotheses):
            if use_llm and i > 0:
                time.sleep(0.1)
            results.append(self.review_hypothesis(hypothesis))

        logger.info(
            "%s: %d hypotheses reviewed, %d with high severity.",
            _AGENT_NAME,
            len(hypotheses),
            sum(1 for r in results if r.overall_severity == "high"),
        )
        return results

    # ------------------------------------------------------------------
    # Private LLM helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, hypothesis: MappingHypothesis) -> str:
        """Build the ontology-engineer review prompt for the LLM.

        Args:
            hypothesis: The hypothesis to describe in the prompt.

        Returns:
            A string prompt ready to be sent as the user message.
        """
        src = hypothesis.source_entity
        tgt = hypothesis.target_entity

        synonyms_str = ", ".join(tgt.synonyms[:5]) if tgt.synonyms else "none"
        parents_str = ", ".join(tgt.parent_terms[:5]) if tgt.parent_terms else "none"
        evidence_str = (
            "; ".join(e.description for e in hypothesis.evidence[:3])
            if hypothesis.evidence
            else "none"
        )

        return (
            "You are an ontology engineer reviewing a proposed ontology mapping for "
            "logical correctness.\n"
            "\n"
            "PROPOSED MAPPING:\n"
            "Source entity:\n"
            f"  - ID: {src.entity_id}\n"
            f"  - Label: {src.label}\n"
            f"  - Description: {src.description or 'none provided'}\n"
            f"  - Datatype: {src.datatype or 'unknown'}\n"
            f"  - Source type: {src.source_type}\n"
            "\n"
            "Target ontology term:\n"
            f"  - ID: {tgt.term_id}\n"
            f"  - Label: {tgt.label}\n"
            f"  - Definition: {tgt.definition or 'no definition available'}\n"
            f"  - Synonyms: {synonyms_str}\n"
            f"  - Parent terms: {parents_str}\n"
            f"  - Term type: {tgt.term_type}\n"
            "\n"
            f"Proposed predicate: {hypothesis.predicate.value}\n"
            f"Confidence: {hypothesis.confidence:.2f}\n"
            f"Existing evidence: {evidence_str}\n"
            "\n"
            "Please check:\n"
            "1. Is the predicate (exact/close/broad/narrow) logically appropriate "
            "given the class hierarchy and definitions?\n"
            "2. Is the source field's datatype compatible with the target term_type "
            "(class vs property)?\n"
            "3. Are there hierarchy issues (is the target too specific or too general)?\n"
            "4. Would this mapping create logical contradictions?\n"
            "5. Is an exactMatch claim too strong (should it be closeMatch)?\n"
            "\n"
            "Respond in this EXACT JSON format (no markdown, raw JSON only):\n"
            "{\n"
            '  "flags": [\n'
            "    {\n"
            '      "flag_type": "short_snake_case_identifier",\n'
            '      "description": "Clear explanation of the problem",\n'
            '      "severity": "low|medium|high"\n'
            "    }\n"
            "  ],\n"
            '  "recommendation": "proceed|review|reject"\n'
            "}\n"
            "\n"
            "If no problems found, return "
            '{"flags": [], "recommendation": "proceed"}'
        )

    def _parse_response(
        self, response_text: str, mapping_id: str
    ) -> AdversarialReviewResult:
        """Parse a raw LLM response into an :class:`AdversarialReviewResult`.

        Strips markdown fences if present. On parse failure, returns a result
        with a single ``"llm_parse_error"`` flag.

        Args:
            response_text: Raw text from the LLM content block.
            mapping_id: The mapping ID this result corresponds to.

        Returns:
            An :class:`AdversarialReviewResult`.
        """
        text = response_text.strip()
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
                "%s: JSON parse error for mapping %s: %s",
                _AGENT_NAME,
                mapping_id,
                exc,
            )
            return AdversarialReviewResult(
                mapping_id=mapping_id,
                flags=[
                    AdversarialFlag(
                        flag_type="llm_parse_error",
                        description=f"LLM response could not be parsed: {exc}",
                        severity="low",
                    )
                ],
                overall_severity="low",
                recommendation="proceed",
            )

        raw_flags = data.get("flags", [])
        flags: list[AdversarialFlag] = []
        for raw in raw_flags:
            try:
                severity = raw.get("severity", "low")
                if severity not in ("low", "medium", "high"):
                    severity = "low"
                flags.append(
                    AdversarialFlag(
                        flag_type=str(raw.get("flag_type", "unknown_issue")),
                        description=str(raw.get("description", "No description provided.")),
                        severity=severity,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: could not parse flag %r: %s", _AGENT_NAME, raw, exc)

        overall_severity = _compute_overall_severity(flags)
        llm_recommendation = data.get("recommendation", "")
        if llm_recommendation in ("proceed", "review", "reject"):
            recommendation = llm_recommendation
        else:
            recommendation = _derive_recommendation(overall_severity)

        return AdversarialReviewResult(
            mapping_id=mapping_id,
            flags=flags,
            overall_severity=overall_severity,
            recommendation=recommendation,
        )

    def _llm_review(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Call the Claude API and parse the ontology-engineer review result.

        On API errors, logs a warning and returns a no-op clean result.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`AdversarialReviewResult`.
        """
        prompt = self._build_prompt(hypothesis)
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

            # Record prompt hash in the hypothesis provenance
            prompt_hash = get_prompt_hash(prompt)
            hypothesis.provenance.extra["ontology_engineer_prompt_hash"] = prompt_hash

            result = self._parse_response(response_text, hypothesis.mapping_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: API error for mapping %s (%s: %s). Returning clean result.",
                _AGENT_NAME,
                hypothesis.mapping_id,
                type(exc).__name__,
                exc,
            )
            return AdversarialReviewResult(
                mapping_id=hypothesis.mapping_id,
                flags=[
                    AdversarialFlag(
                        flag_type="llm_api_error",
                        description=f"LLM API call failed: {exc}",
                        severity="low",
                    )
                ],
                overall_severity="low",
                recommendation="proceed",
            )

        logger.debug(
            "%s: mapping %s — %d flag(s), recommendation=%s",
            _AGENT_NAME,
            hypothesis.mapping_id,
            len(result.flags),
            result.recommendation,
        )
        return result
