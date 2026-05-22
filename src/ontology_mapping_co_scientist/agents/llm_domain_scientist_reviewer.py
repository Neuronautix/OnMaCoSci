"""
LLM-backed domain scientist reviewer for the Ontology Mapping Co-Scientist system.

Reviews mapping hypotheses for scientific plausibility from a domain scientist
perspective. Can be initialised with a domain context string (e.g.
"preclinical pharmacokinetics in rodents") that is injected into every prompt.

Falls back to a no-op result when no LLM client.

Usage:
    # No-op fallback (no API key needed):
    reviewer = LLMDomainScientistReviewerAgent()

    # With LLM and domain context:
    import anthropic
    client = anthropic.Anthropic()
    reviewer = LLMDomainScientistReviewerAgent(
        llm_client=client,
        domain_context="preclinical pharmacokinetics in rodents",
    )

    # Or via environment variable auto-init:
    reviewer = LLMDomainScientistReviewerAgent.from_env(
        domain_context="preclinical pharmacokinetics in rodents"
    )
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

_AGENT_NAME = "LLMDomainScientistReviewerAgent"


class LLMDomainScientistReviewerAgent:
    """Reviews mapping hypotheses for scientific plausibility from a domain scientist perspective.

    Can be initialised with a domain context string that is injected into every
    prompt, allowing the agent to specialise its reviews for a particular
    research domain (e.g. "preclinical pharmacokinetics in rodents").

    Falls back to a no-op result (empty flags, "proceed") when no LLM client.

    Args:
        llm_client: An initialised :class:`anthropic.Anthropic` client, or
            ``None`` to use the no-op fallback.
        model: The Claude model ID to use for reviews.
        max_tokens: Maximum number of tokens the model may generate per review.
        domain_context: A string describing the research domain (e.g.
            ``"biomedical research"``). Injected into every prompt.
        cost_tracker: Optional :class:`~.llm_cost_tracker.LLMCostTracker` to
            record token usage and estimated cost.
    """

    def __init__(
        self,
        llm_client=None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 768,
        domain_context: str = "biomedical research",
        cost_tracker=None,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_tokens = max_tokens
        self.domain_context = domain_context
        self.cost_tracker = cost_tracker
        self.llm_disabled_reason: str | None = None
        self.llm_attempted_reviews = 0
        self.llm_successful_reviews = 0
        self.fallback_reviews = 0

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
        domain_context: str = "biomedical research",
        model: str = "claude-haiku-4-5-20251001",
        cost_tracker=None,
    ) -> "LLMDomainScientistReviewerAgent":
        """Construct an agent, auto-detecting an API key from the environment.

        Args:
            domain_context: The research domain context string.
            model: The Claude model ID to use.
            cost_tracker: Optional cost tracker.

        Returns:
            A fully initialised :class:`LLMDomainScientistReviewerAgent`.
        """
        load_dotenv()
        try:
            import anthropic  # noqa: PLC0415

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ValueError("ANTHROPIC_API_KEY is not set")
            max_retries = int(os.environ.get("OMCS_LLM_MAX_RETRIES", "0"))
            client = anthropic.Anthropic(max_retries=max_retries)
            logger.info(
                "%s.from_env: ANTHROPIC_API_KEY found — LLM mode activated (model=%s).",
                _AGENT_NAME,
                model,
            )
            return cls(
                llm_client=client,
                model=model,
                domain_context=domain_context,
                cost_tracker=cost_tracker,
            )
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
        return cls(
            llm_client=None,
            model=model,
            domain_context=domain_context,
            cost_tracker=cost_tracker,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def review_hypothesis(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Review a single mapping hypothesis from a domain scientist perspective.

        Returns a no-op clean result when no LLM client is available.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`AdversarialReviewResult` with flags and recommendation.
        """
        if self.llm_client is None:
            self.fallback_reviews += 1
            return AdversarialReviewResult(
                mapping_id=hypothesis.mapping_id,
                flags=[],
                overall_severity="clean",
                recommendation="proceed",
            )
        if self.llm_disabled_reason is not None:
            logger.warning(
                "%s: LLM disabled; returning clean fallback (%s).",
                _AGENT_NAME,
                self.llm_disabled_reason,
            )
            self.fallback_reviews += 1
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
            if use_llm and self.llm_disabled_reason is not None:
                logger.warning(
                    "%s: stopping LLM review loop after circuit breaker opened (%s).",
                    _AGENT_NAME,
                    self.llm_disabled_reason,
                )
                self.fallback_reviews += len(hypotheses[i:])
                results.extend(
                    AdversarialReviewResult(
                        mapping_id=h.mapping_id,
                        flags=[],
                        overall_severity="clean",
                        recommendation="proceed",
                    )
                    for h in hypotheses[i:]
                )
                break
            if use_llm and i > 0:
                time.sleep(0.1)
            results.append(self.review_hypothesis(hypothesis))

        if use_llm:
            logger.info(
                "%s: %d hypotheses reviewed, %d with high severity "
                "(llm_attempted=%d, llm_success=%d, fallback=%d).",
                _AGENT_NAME,
                len(hypotheses),
                sum(1 for r in results if r.overall_severity == "high"),
                self.llm_attempted_reviews,
                self.llm_successful_reviews,
                self.fallback_reviews,
            )
        else:
            logger.info(
                "%s: %d hypotheses reviewed, %d with high severity (no-op fallback).",
                _AGENT_NAME,
                len(hypotheses),
                sum(1 for r in results if r.overall_severity == "high"),
            )
        return results

    # ------------------------------------------------------------------
    # Private LLM helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, hypothesis: MappingHypothesis) -> str:
        """Build the domain-scientist review prompt for the LLM.

        Injects :attr:`domain_context` into the prompt so the LLM can apply
        domain-specific scientific judgement.

        Args:
            hypothesis: The hypothesis to describe in the prompt.

        Returns:
            A string prompt ready to be sent as the user message.
        """
        src = hypothesis.source_entity
        tgt = hypothesis.target_entity

        examples_str = (
            ", ".join(str(e) for e in src.examples) if src.examples else "none"
        )
        synonyms_str = ", ".join(tgt.synonyms[:5]) if tgt.synonyms else "none"
        evidence_str = (
            "; ".join(e.description for e in hypothesis.evidence[:3])
            if hypothesis.evidence
            else "none"
        )

        return (
            f"You are a domain scientist specialised in {self.domain_context}, "
            "reviewing a proposed ontology mapping for scientific plausibility.\n"
            "\n"
            "PROPOSED MAPPING:\n"
            "Source field:\n"
            f"  - ID: {src.entity_id}\n"
            f"  - Label: {src.label}\n"
            f"  - Description: {src.description or 'none provided'}\n"
            f"  - Datatype: {src.datatype or 'unknown'}\n"
            f"  - Example values: {examples_str}\n"
            "\n"
            "Target ontology term:\n"
            f"  - ID: {tgt.term_id}\n"
            f"  - Label: {tgt.label}\n"
            f"  - Definition: {tgt.definition or 'no definition available'}\n"
            f"  - Synonyms: {synonyms_str}\n"
            "\n"
            f"Proposed predicate: {hypothesis.predicate.value}\n"
            f"Confidence: {hypothesis.confidence:.2f}\n"
            f"Existing evidence: {evidence_str}\n"
            "\n"
            "Please check:\n"
            "1. Does this mapping make biological/scientific sense in the context "
            f"of {self.domain_context}?\n"
            "2. Could the source field represent something conceptually different from "
            "the target in practice (e.g. a 'weight' field that is actually a dose weight, "
            "not body weight)?\n"
            "3. Are there domain-specific edge cases or exceptions that would make "
            "this mapping problematic?\n"
            "4. Would a domain expert be surprised or uncomfortable with this mapping?\n"
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
        """Call the Claude API and parse the domain-scientist review result.

        On API errors, logs a warning and returns a no-op clean result.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`AdversarialReviewResult`.
        """
        prompt = self._build_prompt(hypothesis)
        self.llm_attempted_reviews += 1
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
            hypothesis.provenance.extra["domain_scientist_prompt_hash"] = prompt_hash

            result = self._parse_response(response_text, hypothesis.mapping_id)
            self.llm_successful_reviews += 1
        except Exception as exc:  # noqa: BLE001
            if _is_provider_overloaded(exc):
                self.llm_disabled_reason = (
                    "provider overloaded; stopped further domain-review calls"
                )
            logger.warning(
                "%s: API error for mapping %s (%s: %s). Returning clean result.",
                _AGENT_NAME,
                hypothesis.mapping_id,
                type(exc).__name__,
                exc,
            )
            self.fallback_reviews += 1
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


def _is_provider_overloaded(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    return status_code == 529 or type(exc).__name__ == "OverloadedError"
