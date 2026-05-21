"""
LLM-backed adversarial reviewer. Uses an Anthropic Claude model to argue against
proposed mappings from a domain science perspective.

This agent is a drop-in replacement for AdversarialReviewerAgent. When no LLM
client is provided, it falls back to the heuristic AdversarialReviewerAgent.

Requires: anthropic Python SDK (pip install anthropic)
Requires: ANTHROPIC_API_KEY environment variable

The LLM is given a structured prompt asking it to identify problems with a mapping.
Its response is parsed into AdversarialFlag objects. The LLM's reasoning is
recorded as counter-evidence with provenance.

Usage:
    # Heuristic fallback (no API key needed):
    reviewer = LLMAdversarialReviewerAgent()

    # With LLM:
    import anthropic
    client = anthropic.Anthropic()
    reviewer = LLMAdversarialReviewerAgent(llm_client=client)

    # Or via environment variable auto-init:
    reviewer = LLMAdversarialReviewerAgent.from_env()
"""

from __future__ import annotations

import json
import logging
import time

from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
    AdversarialReviewerAgent,
    _compute_overall_severity,
    _derive_recommendation,
)
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
)
from ontology_mapping_co_scientist.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
)

logger = logging.getLogger(__name__)


class LLMAdversarialReviewerAgent:
    """LLM-backed adversarial reviewer that falls back to heuristics when no client is set.

    When an ``llm_client`` is provided (an :class:`anthropic.Anthropic` instance),
    each mapping hypothesis is evaluated by calling the Claude API with a
    structured prompt.  The model is asked to identify domain-science problems
    and return a JSON object that is parsed into :class:`AdversarialFlag` objects.

    When no ``llm_client`` is available, the agent transparently delegates every
    call to a :class:`AdversarialReviewerAgent` instance so that the rest of the
    pipeline continues to work without modification.

    Args:
        llm_client: An initialised :class:`anthropic.Anthropic` client, or
            ``None`` to use the heuristic fallback.
        model: The Claude model ID to use for reviews.
        max_tokens: Maximum number of tokens the model may generate per review.
        fallback_to_heuristic: When ``True`` (default) and ``llm_client`` is
            ``None``, a heuristic :class:`AdversarialReviewerAgent` is
            instantiated and used.  When ``False`` and ``llm_client`` is
            ``None``, a :class:`ValueError` is raised.
    """

    def __init__(
        self,
        llm_client=None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
        fallback_to_heuristic: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_tokens = max_tokens
        self._fallback: AdversarialReviewerAgent | None = None

        if llm_client is None:
            if fallback_to_heuristic:
                self._fallback = AdversarialReviewerAgent()
                logger.info(
                    "LLMAdversarialReviewerAgent: no LLM client provided — "
                    "using heuristic AdversarialReviewerAgent fallback."
                )
            else:
                raise ValueError(
                    "llm_client is None and fallback_to_heuristic=False. "
                    "Either provide an anthropic.Anthropic() client or set "
                    "fallback_to_heuristic=True."
                )

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        model: str = "claude-haiku-4-5-20251001",
    ) -> "LLMAdversarialReviewerAgent":
        """Construct an agent, auto-detecting an API key from the environment.

        Tries to import the ``anthropic`` package and instantiate an
        :class:`anthropic.Anthropic` client.  If either the package is not
        installed or the ``ANTHROPIC_API_KEY`` environment variable is not set,
        the constructor falls back to the heuristic reviewer and logs which mode
        was activated.

        Args:
            model: The Claude model ID to use.

        Returns:
            A fully initialised :class:`LLMAdversarialReviewerAgent`.
        """
        try:
            import anthropic  # noqa: PLC0415

            client = anthropic.Anthropic()
            # Validate key presence by accessing the key attribute (raises if missing)
            _ = client.api_key
            logger.info(
                "LLMAdversarialReviewerAgent.from_env: ANTHROPIC_API_KEY found — "
                "LLM mode activated (model=%s).",
                model,
            )
            return cls(llm_client=client, model=model)
        except ImportError:
            logger.warning(
                "LLMAdversarialReviewerAgent.from_env: 'anthropic' package not "
                "installed.  Install it with: pip install anthropic.  "
                "Falling back to heuristic reviewer."
            )
        except Exception as exc:  # covers AuthenticationError and missing key
            logger.warning(
                "LLMAdversarialReviewerAgent.from_env: Could not initialise "
                "Anthropic client (%s: %s).  "
                "Falling back to heuristic reviewer.",
                type(exc).__name__,
                exc,
            )
        return cls(llm_client=None, fallback_to_heuristic=True, model=model)

    # ------------------------------------------------------------------
    # Public interface (mirrors AdversarialReviewerAgent)
    # ------------------------------------------------------------------

    def review_hypothesis(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Review a single mapping hypothesis.

        Delegates to the LLM if a client is available; otherwise uses the
        heuristic fallback.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`AdversarialReviewResult` with flags and recommendation.
        """
        if self.llm_client is None:
            assert self._fallback is not None
            return self._fallback.review_hypothesis(hypothesis)
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

        high_count = sum(1 for r in results if r.overall_severity == "high")
        mode = "LLM" if use_llm else "heuristic"
        logger.info(
            "LLMAdversarialReviewerAgent (%s): %d hypotheses reviewed, "
            "%d with high severity.",
            mode,
            len(hypotheses),
            high_count,
        )
        return results

    def apply_flags_to_hypotheses(
        self,
        hypotheses: list[MappingHypothesis],
        results: list[AdversarialReviewResult],
    ) -> list[MappingHypothesis]:
        """Merge adversarial flags back into the corresponding hypotheses.

        Delegates to :meth:`AdversarialReviewerAgent.apply_flags_to_hypotheses`
        so that the logic is consistent regardless of which reviewer was used.

        Args:
            hypotheses: Original list of mapping hypotheses.
            results: Adversarial review results (one per hypothesis).

        Returns:
            The same hypotheses list, mutated in place with warnings and
            counter-evidence applied.
        """
        helper = self._fallback if self._fallback is not None else AdversarialReviewerAgent()
        return helper.apply_flags_to_hypotheses(hypotheses, results)

    # ------------------------------------------------------------------
    # Private LLM helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, hypothesis: MappingHypothesis) -> str:
        """Build the structured adversarial-review prompt for the LLM.

        Args:
            hypothesis: The hypothesis to describe in the prompt.

        Returns:
            A string prompt ready to be sent as the user message.
        """
        src = hypothesis.source_entity
        tgt = hypothesis.target_entity

        examples_str = ", ".join(str(e) for e in src.examples) if src.examples else "none"
        evidence_descriptions = "; ".join(
            e.description for e in hypothesis.evidence[:3]
        ) if hypothesis.evidence else "no evidence recorded"

        return (
            "You are an adversarial reviewer for ontology mappings. Your job is to find\n"
            "problems, ambiguities, and weaknesses in proposed mappings. Be critical but fair.\n"
            "\n"
            "PROPOSED MAPPING:\n"
            f"- Source entity: {src.entity_id}\n"
            f"- Source label: {src.label}\n"
            f"- Source description: {src.description or 'none provided'}\n"
            f"- Source datatype: {src.datatype}\n"
            f"- Source examples: {examples_str}\n"
            f"- Predicate: {hypothesis.predicate.value}\n"
            f"- Target term: {tgt.term_id}\n"
            f"- Target label: {tgt.label}\n"
            f"- Target definition: {tgt.definition or 'no definition available'}\n"
            f"- Confidence: {hypothesis.confidence:.2f}\n"
            f"- Existing evidence: {evidence_descriptions}\n"
            "\n"
            "Your task: Identify any problems with this mapping. Consider:\n"
            "1. Is the predicate type (exact/close/broad/narrow/related) appropriate?\n"
            "2. Are there unit mismatches or scale differences?\n"
            "3. Could this source field represent something different than the target term?\n"
            "4. Is an exactMatch claim justified, or should it be closeMatch or broadMatch?\n"
            "5. Are there domain-specific concerns a non-expert might miss?\n"
            "6. Is the target term definition too vague or too specific?\n"
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
            '  "overall_assessment": "brief one-sentence summary",\n'
            '  "recommendation": "proceed|review|reject"\n'
            "}\n"
            "\n"
            "If no problems found, return "
            '{"flags": [], "overall_assessment": "Mapping appears sound.", '
            '"recommendation": "proceed"}'
        )

    def _parse_llm_response(
        self, response_text: str, mapping_id: str
    ) -> AdversarialReviewResult:
        """Parse a raw LLM response string into an :class:`AdversarialReviewResult`.

        Strips markdown code fences if present, then parses JSON.  On any
        parse failure, returns a result with a single ``"llm_parse_error"`` flag
        at low severity so that the pipeline can continue.

        Args:
            response_text: Raw text from the LLM content block.
            mapping_id: The mapping ID this result corresponds to.

        Returns:
            A :class:`AdversarialReviewResult`.
        """
        # Strip markdown fences if present (```json ... ``` or ``` ... ```)
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first line (```json or ```) and last ``` line
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
                "LLMAdversarialReviewerAgent: JSON parse error for mapping %s: %s",
                mapping_id,
                exc,
            )
            error_flag = AdversarialFlag(
                flag_type="llm_parse_error",
                description=(
                    f"The LLM response could not be parsed as valid JSON: {exc}. "
                    "The raw LLM output was discarded; heuristic review is recommended."
                ),
                severity="low",
            )
            return AdversarialReviewResult(
                mapping_id=mapping_id,
                flags=[error_flag],
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
                logger.debug(
                    "LLMAdversarialReviewerAgent: could not parse flag %r: %s",
                    raw,
                    exc,
                )

        overall_severity = _compute_overall_severity(flags)
        # Prefer the LLM's own recommendation when it is valid, otherwise derive.
        llm_recommendation = data.get("recommendation", "")
        if llm_recommendation in ("proceed", "review", "reject"):
            recommendation = llm_recommendation
        else:
            recommendation = _derive_recommendation(overall_severity)

        overall_assessment = data.get("overall_assessment", "")

        logger.debug(
            "LLMAdversarialReviewerAgent: mapping %s — assessment: %s",
            mapping_id,
            overall_assessment,
        )
        return AdversarialReviewResult(
            mapping_id=mapping_id,
            flags=flags,
            overall_severity=overall_severity,
            recommendation=recommendation,
        )

    def _llm_review(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Call the Claude API and parse the result.

        On API errors, logs a warning and falls back to the heuristic reviewer
        when available; otherwise returns a result with a single
        ``"llm_api_error"`` flag.

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
            result = self._parse_llm_response(response_text, hypothesis.mapping_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLMAdversarialReviewerAgent: API error for mapping %s (%s: %s). "
                "Falling back to heuristic reviewer.",
                hypothesis.mapping_id,
                type(exc).__name__,
                exc,
            )
            if self._fallback is not None:
                return self._fallback.review_hypothesis(hypothesis)
            # No fallback available — return a minimal error result
            error_flag = AdversarialFlag(
                flag_type="llm_api_error",
                description=(
                    f"LLM API call failed: {exc}. "
                    "This hypothesis was not reviewed by the LLM."
                ),
                severity="low",
            )
            return AdversarialReviewResult(
                mapping_id=hypothesis.mapping_id,
                flags=[error_flag],
                overall_severity="low",
                recommendation="proceed",
            )

        # Record LLM flags as counter-evidence on the hypothesis (non-mutating
        # here — apply_flags_to_hypotheses handles the mutation step).
        logger.debug(
            "LLMAdversarialReviewerAgent: mapping %s — %d LLM flag(s), "
            "recommendation=%s",
            hypothesis.mapping_id,
            len(result.flags),
            result.recommendation,
        )
        return result
