"""Pipeline entry point for the Ontology Mapping Co-Scientist system.

This module provides :func:`run_pipeline`, a high-level function that executes
the full mapping pipeline from source file ingestion through candidate
generation, adversarial review, ranking, and export.  It also provides
:func:`main` for use as a CLI entry point via the ``omcs-run`` console script.

Pipeline stages
---------------
1.  **SourceProfilerAgent** — loads source entities from a CSV or OpenAPI JSON file.
2.  **OntologyProfilerAgent** — loads ontology terms from a YAML profile.
3.  **CandidateGeneratorAgent** — generates lexical-similarity-based mapping
    hypotheses (top-k per source entity).
4.  **AdversarialReviewerAgent** — flags quality problems in each hypothesis.
5.  **RankingAgent** — re-ranks hypotheses per source entity by composite score.
6.  **HumanReviewAgent** — assembles review packets (hypothesis + review result +
    suggested action) for human consumption.
7.  **ValidationAgent** — runs automated checks and sets :attr:`validation_status`.
8.  **Export** — writes a JSON file and an SSSOM-inspired TSV file to the output
    directory, plus a Markdown review report.

The pipeline is intentionally synchronous and single-process for the MVP.
Parallelism and LLM integration are deferred to Phase 2 of the roadmap.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ontology_mapping_co_scientist.agents.source_profiler import SourceProfilerAgent
from ontology_mapping_co_scientist.agents.ontology_profiler import OntologyProfilerAgent
from ontology_mapping_co_scientist.agents.candidate_generator import CandidateGeneratorAgent
from ontology_mapping_co_scientist.env import load_dotenv
from ontology_mapping_co_scientist.io.exporters import export_to_json, export_to_sssom_tsv
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    MappingHypothesis,
    MappingPredicate,
    ValidationStatus,
)
from ontology_mapping_co_scientist.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
    HumanReviewAction,
    SuggestedAction,
)

logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Adversarial reviewer (inlined MVP implementation)
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD_HIGH = 0.7
_CONFIDENCE_THRESHOLD_MEDIUM = 0.4
_SYNONYM_ONLY_THRESHOLD = 0.05  # lex_score headroom below synonym_score


def _adversarial_review(hypothesis: MappingHypothesis) -> AdversarialReviewResult:
    """Run adversarial checks on a single mapping hypothesis.

    Checks performed:
    - Low confidence (< 0.4 → high severity; < 0.7 → medium severity)
    - Missing ontology term definition
    - Synonym-only match (no lexical evidence on preferred label)
    - ``custom:noMapping`` predicate (always flagged for human review)
    - Very short entity label (may lead to over-broad matches)

    Args:
        hypothesis: The mapping hypothesis to review.

    Returns:
        An :class:`AdversarialReviewResult` with zero or more flags.
    """
    flags: list[AdversarialFlag] = []

    # --- Low confidence ---
    if hypothesis.predicate != MappingPredicate.NO_MAPPING:
        if hypothesis.confidence < _CONFIDENCE_THRESHOLD_MEDIUM:
            flags.append(AdversarialFlag(
                flag_type="low_confidence",
                description=(
                    f"Confidence score {hypothesis.confidence:.3f} is below the "
                    f"minimum acceptable threshold of {_CONFIDENCE_THRESHOLD_MEDIUM:.2f}. "
                    "This mapping requires careful human verification before use."
                ),
                severity="high",
            ))
        elif hypothesis.confidence < _CONFIDENCE_THRESHOLD_HIGH:
            flags.append(AdversarialFlag(
                flag_type="low_confidence",
                description=(
                    f"Confidence score {hypothesis.confidence:.3f} is moderate (below "
                    f"{_CONFIDENCE_THRESHOLD_HIGH:.2f}). Human review is recommended."
                ),
                severity="medium",
            ))

    # --- Missing definition ---
    if (
        hypothesis.predicate != MappingPredicate.NO_MAPPING
        and hypothesis.target_entity is not None
        and not hypothesis.target_entity.definition
    ):
        flags.append(AdversarialFlag(
            flag_type="missing_definition",
            description=(
                f"Ontology term '{hypothesis.target_entity.term_id}' has no formal "
                "definition recorded in the profile.  Without a definition it is "
                "impossible to verify the semantic accuracy of the mapping."
            ),
            severity="medium",
        ))

    # --- Synonym-only match ---
    if hypothesis.predicate != MappingPredicate.NO_MAPPING:
        lex_scores = [
            ev.score for ev in hypothesis.evidence
            if ev.evidence_type == "lexical_similarity" and ev.score is not None
        ]
        syn_scores = [
            ev.score for ev in hypothesis.evidence
            if ev.evidence_type == "synonym_match" and ev.score is not None
        ]
        best_lex = max(lex_scores) if lex_scores else 0.0
        best_syn = max(syn_scores) if syn_scores else 0.0
        if best_syn > 0 and best_lex == 0.0:
            flags.append(AdversarialFlag(
                flag_type="synonym_only_match",
                description=(
                    "This mapping is supported only by synonym similarity "
                    f"(score={best_syn:.3f}); the preferred label of the target term "
                    "did not match the source entity label. "
                    "Synonym-based mappings are more prone to false positives."
                ),
                severity="low",
            ))

    # --- No mapping ---
    if hypothesis.predicate == MappingPredicate.NO_MAPPING:
        flags.append(AdversarialFlag(
            flag_type="no_mapping_found",
            description=(
                "No ontology term reached the minimum confidence threshold for this "
                "source entity.  A domain expert should determine whether: "
                "(a) an existing term was missed, "
                "(b) a related term should be used with a broader/narrower predicate, "
                "or (c) a new ontology term should be requested."
            ),
            severity="high",
        ))

    # --- Short entity label (ambiguity risk) ---
    if (
        hypothesis.predicate != MappingPredicate.NO_MAPPING
        and len(hypothesis.source_entity.label.split()) == 1
        and len(hypothesis.source_entity.label) <= 4
    ):
        flags.append(AdversarialFlag(
            flag_type="ambiguous_short_label",
            description=(
                f"Source entity label '{hypothesis.source_entity.label}' is very short "
                "(1 word, ≤4 characters).  Short labels are prone to spurious lexical "
                "matches.  Verify that the matched ontology term is semantically correct."
            ),
            severity="low",
        ))

    # Compute overall severity
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    if not flags:
        overall_severity: str = "clean"
        recommendation = "proceed"
    else:
        max_rank = max(severity_rank[f.severity] for f in flags)
        overall_severity = {3: "high", 2: "medium", 1: "low"}[max_rank]
        recommendation = "reject" if overall_severity == "high" else "review"

    return AdversarialReviewResult(
        mapping_id=hypothesis.mapping_id,
        flags=flags,
        overall_severity=overall_severity,  # type: ignore[arg-type]
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# Ranking agent (inlined MVP implementation)
# ---------------------------------------------------------------------------


def _rank_hypotheses(hypotheses: list[MappingHypothesis]) -> list[MappingHypothesis]:
    """Assign :attr:`rank` to hypotheses, grouped by source entity.

    Within each source entity group, hypotheses are sorted by:
    1. ``custom:noMapping`` predicates are always ranked last.
    2. Confidence score descending.
    3. Mapping ID lexicographically (tie-break for determinism).

    Args:
        hypotheses: All hypotheses from the candidate generation step.

    Returns:
        The same list with :attr:`rank` fields populated, sorted so that rank 1
        for each entity appears before rank 2, etc.
    """
    from collections import defaultdict

    groups: dict[str, list[MappingHypothesis]] = defaultdict(list)
    for h in hypotheses:
        groups[h.source_entity.entity_id].append(h)

    ranked: list[MappingHypothesis] = []
    for entity_id in sorted(groups):
        group = groups[entity_id]
        group.sort(
            key=lambda h: (
                1 if h.predicate == MappingPredicate.NO_MAPPING else 0,
                -h.confidence,
                h.mapping_id,
            )
        )
        for i, h in enumerate(group, start=1):
            h.rank = i
        ranked.extend(group)

    return ranked


# ---------------------------------------------------------------------------
# Validation agent (inlined MVP implementation)
# ---------------------------------------------------------------------------


def _validate_hypothesis(hypothesis: MappingHypothesis) -> None:
    """Run automated validation checks and update :attr:`validation_status` in-place.

    Current checks:
    - Confidence must be in [0.0, 1.0] (always true given Pydantic constraints,
      but explicitly checked for defence-in-depth).
    - Non-NO_MAPPING hypotheses must have at least one evidence item.
    - The predicate value must be a recognised :class:`MappingPredicate`.

    Warnings are appended to :attr:`MappingHypothesis.warnings` when issues are
    found at non-failing severity.

    Args:
        hypothesis: The hypothesis to validate.  Modified in-place.
    """
    issues: list[str] = []
    warnings: list[str] = []

    # Check confidence bounds (redundant but explicit)
    if not (0.0 <= hypothesis.confidence <= 1.0):
        issues.append(
            f"Confidence {hypothesis.confidence} is outside [0.0, 1.0]."
        )

    # Non-NO_MAPPING must have evidence
    if (
        hypothesis.predicate != MappingPredicate.NO_MAPPING
        and not hypothesis.evidence
    ):
        warnings.append(
            "Mapping hypothesis has no supporting evidence items. "
            "Confidence score cannot be independently verified."
        )

    # Rank 1 hypothesis must not be NO_MAPPING unless it is the only candidate
    if hypothesis.rank == 1 and hypothesis.predicate == MappingPredicate.NO_MAPPING:
        warnings.append(
            "The top-ranked hypothesis for this source entity is NO_MAPPING. "
            "Consider whether any existing term could serve as a partial match."
        )

    hypothesis.warnings.extend(warnings)

    if issues:
        hypothesis.validation_status = ValidationStatus.FAILED
        hypothesis.warnings.extend(
            [f"[VALIDATION FAILED] {issue}" for issue in issues]
        )
    elif warnings:
        hypothesis.validation_status = ValidationStatus.WARNING
    else:
        hypothesis.validation_status = ValidationStatus.PASSED


# ---------------------------------------------------------------------------
# Human review agent (inlined MVP implementation)
# ---------------------------------------------------------------------------


def _suggest_action(
    hypothesis: MappingHypothesis,
    review_result: AdversarialReviewResult,
) -> SuggestedAction:
    """Generate a suggested human review action for a hypothesis.

    Decision logic:
    - NO_MAPPING → create_new_ontology_term
    - Any high-severity flag → reject (unless it is a no_mapping flag)
    - Confidence ≥ 0.85 and no flags → approve
    - Confidence ≥ 0.70 and clean review → approve
    - Synonym-only match → request_more_evidence
    - Otherwise → request_more_evidence or change_predicate (if ambiguity flag)

    Args:
        hypothesis: The mapping hypothesis.
        review_result: The adversarial review result for this hypothesis.

    Returns:
        A :class:`SuggestedAction` recommendation.
    """
    flag_types = {f.flag_type for f in review_result.flags}
    has_high = review_result.overall_severity == "high"

    if hypothesis.predicate == MappingPredicate.NO_MAPPING:
        return SuggestedAction(
            action=HumanReviewAction.CREATE_NEW_TERM,
            reason=(
                "No ontology term was found with sufficient confidence. "
                "A domain scientist should determine whether a new ontology "
                "term is needed or whether an existing term was missed."
            ),
        )

    if has_high and "low_confidence" in flag_types:
        return SuggestedAction(
            action=HumanReviewAction.REJECT,
            reason=(
                f"Confidence score {hypothesis.confidence:.3f} is too low to "
                "accept this mapping without additional evidence. "
                "Consider re-running with additional synonym data or requesting "
                "a broader match predicate instead."
            ),
        )

    if "broad_narrow_ambiguity" in flag_types:
        # Suggest changing predicate toward closeMatch as a safer fallback
        return SuggestedAction(
            action=HumanReviewAction.CHANGE_PREDICATE,
            reason=(
                "The relationship between source entity and target term is "
                "directionally ambiguous.  Consider using skos:closeMatch "
                "as a more conservative predicate until the hierarchy is clarified."
            ),
            suggested_predicate=MappingPredicate.CLOSE_MATCH,
        )

    if review_result.overall_severity == "clean" and hypothesis.confidence >= 0.85:
        return SuggestedAction(
            action=HumanReviewAction.APPROVE,
            reason=(
                f"High confidence ({hypothesis.confidence:.3f}) with no adversarial "
                "flags.  This mapping appears well-supported by lexical similarity "
                "evidence and is recommended for approval."
            ),
        )

    if review_result.overall_severity in ("clean", "low") and hypothesis.confidence >= 0.70:
        return SuggestedAction(
            action=HumanReviewAction.APPROVE,
            reason=(
                f"Confidence {hypothesis.confidence:.3f} meets the acceptable "
                "threshold and only low-severity flags were raised. "
                "A quick review of the target term definition is recommended "
                "before approving."
            ),
        )

    if "synonym_only_match" in flag_types:
        return SuggestedAction(
            action=HumanReviewAction.REQUEST_MORE_EVIDENCE,
            reason=(
                "This mapping is supported only by synonym similarity. "
                "Reviewing the full ontology term definition and comparing it "
                "against the source entity description would strengthen confidence."
            ),
        )

    return SuggestedAction(
        action=HumanReviewAction.REQUEST_MORE_EVIDENCE,
        reason=(
            f"Confidence {hypothesis.confidence:.3f} is in the uncertain range and "
            "one or more adversarial flags were raised. "
            "A domain scientist review is needed before this mapping can be promoted."
        ),
    )


def _build_review_packets(
    hypotheses: list[MappingHypothesis],
    review_results: dict[str, AdversarialReviewResult],
) -> list[dict]:
    """Assemble per-source-entity review packets.

    Each packet is a plain dict designed to be consumed by both the Markdown
    report generator (which uses dict-key access) and any downstream tooling.

    Packet structure::

        {
          "source_entity_id": str,
          "source_entity_label": str,
          "source_entity": SourceEntity,          # original model object
          "top_hypothesis": MappingHypothesis,    # original model object
          "all_hypotheses": list[MappingHypothesis],
          "adversarial_result": AdversarialReviewResult,
          "suggested_action": SuggestedAction,
          # Serialised forms for the report renderer:
          "top_mapping": dict,                    # model_dump of top hypothesis
          "alternative_mappings": list[dict],     # model_dumps of alternatives
        }

    Args:
        hypotheses: All ranked hypotheses.
        review_results: Mapping from mapping_id to adversarial review result.

    Returns:
        A list of review packet dicts, one per unique source entity, sorted by
        entity_id for deterministic output.
    """
    from collections import defaultdict

    entity_groups: dict[str, list[MappingHypothesis]] = defaultdict(list)
    for h in hypotheses:
        entity_groups[h.source_entity.entity_id].append(h)

    packets = []
    for entity_id in sorted(entity_groups):
        group = sorted(
            entity_groups[entity_id],
            key=lambda h: (h.rank if h.rank is not None else 9999),
        )
        top = group[0]
        adv_result = review_results.get(top.mapping_id)
        if adv_result is None:
            adv_result = AdversarialReviewResult(
                mapping_id=top.mapping_id,
                flags=[],
                overall_severity="clean",
                recommendation="proceed",
            )
        suggested = _suggest_action(top, adv_result)

        # Serialise hypotheses for the report renderer (dict-key access)
        top_mapping_dict = top.model_dump(mode="json")

        # Collect adversarial flag descriptions as warnings for display
        adv_warnings = [
            f"[{f.severity.upper()}] {f.flag_type}: {f.description}"
            for f in adv_result.flags
        ]
        all_entity_warnings = list(top.warnings) + adv_warnings

        alt_dicts = [
            h.model_dump(mode="json")
            for h in group[1:]
            if h.mapping_id != top.mapping_id
        ]

        # Attach aggregated warnings to the top_mapping dict so the renderer
        # can display them without accessing the model object directly.
        top_mapping_dict["_adv_flags"] = [
            f.model_dump(mode="json") for f in adv_result.flags
        ]

        packets.append({
            # Keys used by the report renderer (dict-key access)
            "source_entity_id": entity_id,
            "source_entity_label": top.source_entity.label,
            "top_mapping": top_mapping_dict,
            "alternative_mappings": alt_dicts,
            "suggested_action": suggested.model_dump(mode="json"),
            "all_warnings": all_entity_warnings,
            # Original model objects for downstream Python code
            "source_entity": top.source_entity,
            "top_hypothesis": top,
            "all_hypotheses": group,
            "adversarial_result": adv_result,
        })

    return packets


def _highest_review_severity(results: list[AdversarialReviewResult]) -> str:
    severity_rank = {"clean": 0, "low": 1, "medium": 2, "high": 3}
    highest = max(
        (result.overall_severity for result in results),
        key=lambda severity: severity_rank.get(severity, 0),
        default="clean",
    )
    return highest


def _merge_review_results(
    mapping_id: str,
    results: list[tuple[str, AdversarialReviewResult]],
) -> AdversarialReviewResult:
    """Merge review outputs from heuristic and LLM reviewer agents."""
    flags: list[AdversarialFlag] = []
    raw_results = [result for _, result in results]

    for agent_name, result in results:
        for flag in result.flags:
            flags.append(
                AdversarialFlag(
                    flag_type=f"{agent_name}:{flag.flag_type}",
                    description=f"{agent_name}: {flag.description}",
                    severity=flag.severity,
                )
            )

    overall_severity = _highest_review_severity(raw_results)
    recommendations = {result.recommendation for result in raw_results}
    if "reject" in recommendations or overall_severity == "high":
        recommendation = "reject"
    elif "review" in recommendations or overall_severity == "medium":
        recommendation = "review"
    else:
        recommendation = "proceed"

    return AdversarialReviewResult(
        mapping_id=mapping_id,
        flags=flags,
        overall_severity=overall_severity,  # type: ignore[arg-type]
        recommendation=recommendation,
    )


def _agent_has_llm_client(agent: object) -> bool:
    """Return whether an LLM-backed agent actually has an active client."""
    return bool(getattr(agent, "llm_client", None) is not None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_pipeline(
    source_filepath: str | Path,
    ontology_filepath: str | Path,
    output_dir: str | Path,
    pipeline_run_id: str | None = None,
    verbose: bool = False,
    llm_adversarial_review: bool = False,
    llm_enabled: bool = False,
    require_llm: bool = False,
    llm_model: str = "claude-haiku-4-5-20251001",
    domain_context: str = "biomedical research",
    llm_review_top_k: int = 1,
    llm_candidate_top_k: int = 2,
    llm_max_candidate_entities: int | None = 10,
    llm_max_review_hypotheses: int | None = 10,
    ledger_path: str | Path | None = None,
) -> dict:
    """Execute the full ontology mapping pipeline.

    This is the primary programmatic entry point.  It chains all pipeline
    stages in order, writes output files to *output_dir*, and returns a
    summary dict.

    Args:
        source_filepath: Path to the source data file.  Supported formats:

            - ``.csv`` — column-per-entity CSV file
            - ``.json`` — OpenAPI 3.x or Swagger 2.x schema

        ontology_filepath: Path to the ontology profile YAML file.  Must
            conform to the format described in
            :mod:`~ontology_mapping_co_scientist.io.ontology_profile_loader`.
        output_dir: Directory where output files will be written.  Will be
            created if it does not exist.
        pipeline_run_id: An optional string identifier for this pipeline run.
            Defaults to a freshly generated UUID4 if not provided.
        verbose: When ``True``, set the root logger to ``INFO`` level so that
            per-stage progress messages are visible.  When ``False`` (default),
            only ``WARNING`` and above are emitted.

    Returns:
        A summary dict with the following keys:

        - ``pipeline_run_id`` (str) — the run identifier used.
        - ``source_filepath`` (str) — resolved absolute path to the source file.
        - ``ontology_filepath`` (str) — resolved absolute path to the ontology file.
        - ``total_source_entities`` (int) — number of source entities profiled.
        - ``total_ontology_terms`` (int) — number of ontology terms loaded.
        - ``total_hypotheses`` (int) — total mapping hypotheses generated.
        - ``hypotheses_passed_validation`` (int)
        - ``hypotheses_failed_validation`` (int)
        - ``hypotheses_with_warnings`` (int)
        - ``output_json`` (str) — path to the exported JSON file.
        - ``output_tsv`` (str) — path to the exported SSSOM TSV file.
        - ``output_report`` (str) — path to the Markdown review report.
        - ``review_packets`` (list[dict]) — the assembled review packets.
        - ``hypotheses`` (list[MappingHypothesis]) — the full hypothesis list.

    Raises:
        FileNotFoundError: If *source_filepath* or *ontology_filepath* do not
            exist.
        ValueError: If the source file format is not supported.
    """
    # --- Logging setup ---
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Ensure the root logger respects the requested level even if already
    # configured (e.g. when run_pipeline is called multiple times in a script).
    logging.getLogger().setLevel(log_level)

    if pipeline_run_id is None:
        pipeline_run_id = str(uuid.uuid4())

    source_filepath = Path(source_filepath).resolve()
    ontology_filepath = Path(ontology_filepath).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_stem = source_filepath.stem
    output_prefix = f"{source_stem}_{run_ts}"

    logger.info(
        "=== Ontology Mapping Co-Scientist v%s | run_id=%s ===",
        _PIPELINE_VERSION,
        pipeline_run_id,
    )
    logger.info("Source file   : %s", source_filepath)
    logger.info("Ontology file : %s", ontology_filepath)
    logger.info("Output dir    : %s", output_dir)

    llm_stage_modes: dict[str, str] = {}
    llm_disabled_reasons: dict[str, str] = {}
    llm_call_stats: dict[str, dict[str, int]] = {}
    llm_budget: dict[str, int | None] = {
        "candidate_top_k": llm_candidate_top_k,
        "max_candidate_entities": llm_max_candidate_entities,
        "review_top_k": llm_review_top_k,
        "max_review_hypotheses": llm_max_review_hypotheses,
    }

    # ------------------------------------------------------------------
    # Stage 1: Source profiling
    # ------------------------------------------------------------------
    logger.info("[Stage 1/7] Source profiling ...")
    source_agent = SourceProfilerAgent()
    source_entities = source_agent.profile_auto(source_filepath)
    source_summary = source_agent.summarize(source_entities)
    logger.info(
        "  -> %d source entities discovered (missing_descriptions=%d)",
        source_summary["total"],
        source_summary["missing_descriptions"],
    )

    # ------------------------------------------------------------------
    # Stage 2: Ontology profiling
    # ------------------------------------------------------------------
    logger.info("[Stage 2/7] Ontology profiling ...")
    onto_agent = OntologyProfilerAgent()
    ontology_terms = onto_agent.load_profile(ontology_filepath)
    onto_summary = onto_agent.summarize()
    logger.info(
        "  -> %d ontology terms loaded from %s",
        onto_summary["total_terms"],
        onto_summary["ontology_ids"],
    )

    # ------------------------------------------------------------------
    # Stage 3: Candidate generation
    # ------------------------------------------------------------------
    logger.info("[Stage 3/7] Candidate generation ...")
    if llm_enabled:
        from ontology_mapping_co_scientist.agents.llm_candidate_generator import (
            LLMCandidateGeneratorAgent,
        )

        candidate_agent = LLMCandidateGeneratorAgent.from_env(model=llm_model)
        candidate_agent.top_k_for_llm = max(1, llm_candidate_top_k)
        candidate_agent.max_entities_for_llm = llm_max_candidate_entities
        llm_stage_modes["candidate_generation"] = (
            "llm" if _agent_has_llm_client(candidate_agent) else "lexical_fallback"
        )
        if llm_max_candidate_entities == 0:
            llm_stage_modes["candidate_generation"] = "budget_skipped"
        if require_llm and not _agent_has_llm_client(candidate_agent):
            raise RuntimeError(
                "LLM candidate generation was requested, but no active LLM client "
                "is available. Install the llm extra and set ANTHROPIC_API_KEY."
            )
    else:
        candidate_agent = CandidateGeneratorAgent(top_k=5, min_confidence=0.0)
        llm_stage_modes["candidate_generation"] = "disabled"

    hypotheses = candidate_agent.generate_candidates(
        source_entities=source_entities,
        ontology_terms=ontology_terms,
        pipeline_run_id=pipeline_run_id,
    )
    if llm_enabled and getattr(candidate_agent, "llm_disabled_reason", None):
        llm_disabled_reasons["candidate_generation"] = candidate_agent.llm_disabled_reason
        llm_stage_modes["candidate_generation"] = "disabled_overloaded"
    if llm_enabled:
        llm_call_stats["candidate_generation"] = {
            "entities_scored": getattr(candidate_agent, "llm_entities_scored", 0),
        }
    logger.info("  -> %d hypotheses generated", len(hypotheses))

    # ------------------------------------------------------------------
    # Stage 4: Adversarial review
    # ------------------------------------------------------------------
    logger.info("[Stage 4/7] Adversarial review ...")
    review_results: dict[str, AdversarialReviewResult] = {}
    llm_reviewed_hypotheses = 0

    if llm_enabled:
        from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
            AdversarialReviewerAgent,
        )
        from ontology_mapping_co_scientist.agents.llm_adversarial_reviewer import (
            LLMAdversarialReviewerAgent,
        )
        from ontology_mapping_co_scientist.agents.llm_domain_scientist_reviewer import (
            LLMDomainScientistReviewerAgent,
        )
        from ontology_mapping_co_scientist.agents.llm_ontology_engineer_reviewer import (
            LLMOntologyEngineerReviewerAgent,
        )

        heuristic_reviewer = AdversarialReviewerAgent()
        llm_adversarial = LLMAdversarialReviewerAgent.from_env(model=llm_model)
        ontology_reviewer = LLMOntologyEngineerReviewerAgent.from_env(model=llm_model)
        domain_reviewer = LLMDomainScientistReviewerAgent.from_env(
            model=llm_model,
            domain_context=domain_context,
        )
        llm_stage_modes["adversarial_review"] = (
            "llm" if _agent_has_llm_client(llm_adversarial) else "heuristic_fallback"
        )
        llm_stage_modes["ontology_engineer_review"] = (
            "llm" if _agent_has_llm_client(ontology_reviewer) else "noop_fallback"
        )
        llm_stage_modes["domain_scientist_review"] = (
            "llm" if _agent_has_llm_client(domain_reviewer) else "noop_fallback"
        )
        if require_llm and not all(
            _agent_has_llm_client(agent)
            for agent in (llm_adversarial, ontology_reviewer, domain_reviewer)
        ):
            raise RuntimeError(
                "LLM review was requested, but one or more LLM reviewer agents "
                "do not have an active LLM client. Install the llm extra and set "
                "ANTHROPIC_API_KEY."
            )

        # The heuristic critic covers every hypothesis. LLM reviewers are then
        # applied only to the top N hypotheses per source entity to avoid API
        # overload and keep expert-model attention on actionable candidates.
        hypotheses = _rank_hypotheses(hypotheses)
        llm_review_targets = [
            h
            for h in hypotheses
            if h.rank is not None and h.rank <= max(1, llm_review_top_k)
        ]
        if llm_max_review_hypotheses is not None:
            llm_review_targets = llm_review_targets[:max(0, llm_max_review_hypotheses)]
        llm_reviewed_hypotheses = len(llm_review_targets)
        logger.info(
            "  LLM reviewer scope: %d/%d hypotheses (top %d per source entity).",
            llm_reviewed_hypotheses,
            len(hypotheses),
            max(1, llm_review_top_k),
        )

        heuristic_results = {
            result.mapping_id: result
            for result in heuristic_reviewer.review_all(hypotheses)
        }
        llm_adv_results = {
            result.mapping_id: result
            for result in llm_adversarial.review_all(llm_review_targets)
        }
        ontology_results = {
            result.mapping_id: result
            for result in ontology_reviewer.review_all(llm_review_targets)
        }
        domain_results = {
            result.mapping_id: result
            for result in domain_reviewer.review_all(llm_review_targets)
        }
        for stage_name, reviewer_agent in (
            ("adversarial_review", llm_adversarial),
            ("ontology_engineer_review", ontology_reviewer),
            ("domain_scientist_review", domain_reviewer),
        ):
            llm_call_stats[stage_name] = {
                "attempted": getattr(reviewer_agent, "llm_attempted_reviews", 0),
                "succeeded": getattr(reviewer_agent, "llm_successful_reviews", 0),
                "fallback": getattr(reviewer_agent, "fallback_reviews", 0),
            }
            reason = getattr(reviewer_agent, "llm_disabled_reason", None)
            if reason:
                llm_disabled_reasons[stage_name] = reason
                llm_stage_modes[stage_name] = "disabled_overloaded"
        for h in hypotheses:
            if h.mapping_id in llm_adv_results:
                review_results[h.mapping_id] = _merge_review_results(
                    h.mapping_id,
                    [
                        ("heuristic", heuristic_results[h.mapping_id]),
                        ("llm_adversarial", llm_adv_results[h.mapping_id]),
                        ("llm_ontology_engineer", ontology_results[h.mapping_id]),
                        ("llm_domain_scientist", domain_results[h.mapping_id]),
                    ],
                )
            else:
                review_results[h.mapping_id] = heuristic_results[h.mapping_id]
    elif llm_adversarial_review:
        from ontology_mapping_co_scientist.agents.llm_adversarial_reviewer import (
            LLMAdversarialReviewerAgent,
        )
        _llm_reviewer = LLMAdversarialReviewerAgent.from_env(model=llm_model)
        llm_stage_modes["adversarial_review"] = (
            "llm" if _agent_has_llm_client(_llm_reviewer) else "heuristic_fallback"
        )
        logger.info(
            "  LLM adversarial review enabled (mode=%s).",
            llm_stage_modes["adversarial_review"],
        )
        for result in _llm_reviewer.review_all(hypotheses):
            review_results[result.mapping_id] = result
    else:
        llm_stage_modes["adversarial_review"] = "disabled"
        for h in hypotheses:
            result = _adversarial_review(h)
            review_results[h.mapping_id] = result
            if result.has_blocking_issues():
                logger.debug(
                    "  [BLOCK] %s — %d high-severity flag(s)",
                    h.mapping_id,
                    sum(1 for f in result.flags if f.severity == "high"),
                )

    n_blocked = sum(1 for r in review_results.values() if r.has_blocking_issues())
    logger.info(
        "  -> %d hypotheses reviewed; %d with blocking issues",
        len(review_results),
        n_blocked,
    )

    # ------------------------------------------------------------------
    # Stage 5: Ranking
    # ------------------------------------------------------------------
    logger.info("[Stage 5/7] Ranking ...")
    hypotheses = _rank_hypotheses(hypotheses)
    logger.info("  -> hypotheses ranked per source entity")

    # ------------------------------------------------------------------
    # Stage 6: Validation
    # ------------------------------------------------------------------
    logger.info("[Stage 6/7] Validation ...")
    for h in hypotheses:
        _validate_hypothesis(h)
    n_passed = sum(1 for h in hypotheses if h.validation_status == ValidationStatus.PASSED)
    n_failed = sum(1 for h in hypotheses if h.validation_status == ValidationStatus.FAILED)
    n_warned = sum(1 for h in hypotheses if h.validation_status == ValidationStatus.WARNING)
    logger.info(
        "  -> passed=%d  failed=%d  warnings=%d",
        n_passed,
        n_failed,
        n_warned,
    )

    # ------------------------------------------------------------------
    # Stage 7: Assemble review packets and export
    # ------------------------------------------------------------------
    logger.info("[Stage 7/7] Assembling review packets and exporting ...")
    review_packets = _build_review_packets(hypotheses, review_results)

    # Build a simple validation summary for the report
    validation_summary = {
        "total": len(hypotheses),
        "passed": n_passed,
        "failed": n_failed,
        "warnings": n_warned,
        "pending": sum(
            1 for h in hypotheses if h.validation_status == "pending"
        ),
        "blocking_adversarial_issues": n_blocked,
    }

    # Export JSON
    output_json = output_dir / f"{output_prefix}_mappings.json"
    export_to_json(hypotheses, output_json)
    logger.info("  -> JSON exported: %s", output_json)

    # Export review queue for the interactive HITL CLI.
    output_review_queue = output_dir / f"{output_prefix}_review_queue.json"
    review_queue_document = {
        "metadata": {
            "pipeline_run_id": pipeline_run_id,
            "pipeline_version": _PIPELINE_VERSION,
            "source_filepath": str(source_filepath),
            "ontology_filepath": str(ontology_filepath),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_review_packets": len(review_packets),
            "feedback_policy": (
                "No mapping is final until a human records a ledger decision. "
                "Blocking adversarial or failed validation results cannot be "
                "approved through the chat review mode; they must be rejected, "
                "changed, or sent back for more evidence."
            ),
            "llm_enabled": llm_enabled,
            "llm_model": llm_model if llm_enabled or llm_adversarial_review else None,
            "llm_stage_modes": llm_stage_modes,
            "llm_disabled_reasons": llm_disabled_reasons,
            "llm_call_stats": llm_call_stats,
            "domain_context": domain_context if llm_enabled else None,
            "llm_review_top_k": llm_review_top_k if llm_enabled else None,
            "llm_reviewed_hypotheses": llm_reviewed_hypotheses,
            "llm_budget": llm_budget if llm_enabled else None,
            "llm_candidate_entities_scored": (
                getattr(candidate_agent, "llm_entities_scored", 0)
                if llm_enabled else 0
            ),
        },
        "review_packets": [
            {
                key: value
                for key, value in packet.items()
                if key not in {
                    "source_entity",
                    "top_hypothesis",
                    "all_hypotheses",
                    "adversarial_result",
                }
            }
            for packet in review_packets
        ],
    }
    output_review_queue.write_text(
        json.dumps(review_queue_document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("  -> Review queue exported: %s", output_review_queue)

    # Export SSSOM TSV (only non-NO_MAPPING hypotheses)
    exportable = [
        h for h in hypotheses
        if h.predicate != MappingPredicate.NO_MAPPING and h.target_entity is not None
    ]
    output_tsv = output_dir / f"{output_prefix}_sssom.tsv"
    if exportable:
        export_to_sssom_tsv(exportable, output_tsv)
        logger.info("  -> SSSOM TSV exported: %s", output_tsv)
    else:
        logger.warning("  -> No exportable hypotheses; SSSOM TSV not written.")
        output_tsv = Path()  # empty path sentinel

    # Export Markdown report
    from ontology_mapping_co_scientist.reports.markdown_report import (
        generate_markdown_report,
    )
    output_report = output_dir / f"{output_prefix}_review_report.md"
    generate_markdown_report(
        review_packets=review_packets,
        hypotheses=hypotheses,
        validation_summary=validation_summary,
        output_path=output_report,
        pipeline_run_id=pipeline_run_id,
    )
    logger.info("  -> Markdown report written: %s", output_report)

    logger.info(
        "=== Pipeline complete | run_id=%s | %d entities -> %d hypotheses ===",
        pipeline_run_id,
        len(source_entities),
        len(hypotheses),
    )

    return {
        "pipeline_run_id": pipeline_run_id,
        "source_filepath": str(source_filepath),
        "ontology_filepath": str(ontology_filepath),
        "total_source_entities": len(source_entities),
        "total_ontology_terms": len(ontology_terms),
        "total_hypotheses": len(hypotheses),
        "hypotheses_passed_validation": n_passed,
        "hypotheses_failed_validation": n_failed,
        "hypotheses_with_warnings": n_warned,
        "output_json": str(output_json),
        "output_tsv": str(output_tsv) if output_tsv != Path() else "",
        "output_report": str(output_report),
        "output_review_queue": str(output_review_queue),
        "llm_enabled": llm_enabled,
        "llm_stage_modes": llm_stage_modes,
        "llm_disabled_reasons": llm_disabled_reasons,
        "llm_call_stats": llm_call_stats,
        "llm_review_top_k": llm_review_top_k,
        "llm_reviewed_hypotheses": llm_reviewed_hypotheses,
        "llm_budget": llm_budget,
        "llm_candidate_entities_scored": (
            getattr(candidate_agent, "llm_entities_scored", 0)
            if llm_enabled else 0
        ),
        "review_packets": review_packets,
        "hypotheses": hypotheses,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Command-line entry point for the mapping pipeline.

    Exposed as the ``omcs-run`` console script via ``pyproject.toml``.

    Usage::

        omcs-run --source data/animals.csv \\
                 --ontology examples/ontology_profiles/hcm_mouse_profile.yaml \\
                 --output-dir examples/outputs \\
                 --run-id my-run-001 \\
                 --verbose

    Or via Python::

        python -m ontology_mapping_co_scientist.pipeline.run_mapping_pipeline \\
               --source data/animals.csv ...
    """
    load_dotenv()
    default_llm_model = os.environ.get("OMCS_LLM_MODEL", "claude-haiku-4-5-20251001")
    default_domain_context = os.environ.get("OMCS_DOMAIN_CONTEXT", "biomedical research")
    default_llm_review_top_k = int(os.environ.get("OMCS_LLM_REVIEW_TOP_K", "1"))
    default_llm_candidate_top_k = int(os.environ.get("OMCS_LLM_CANDIDATE_TOP_K", "2"))
    default_llm_max_candidate_entities = int(
        os.environ.get("OMCS_LLM_MAX_CANDIDATE_ENTITIES", "10")
    )
    default_llm_max_review_hypotheses = int(
        os.environ.get("OMCS_LLM_MAX_REVIEW_HYPOTHESES", "10")
    )

    parser = argparse.ArgumentParser(
        prog="omcs-run",
        description=(
            "Ontology Mapping Co-Scientist v" + _PIPELINE_VERSION + "\n\n"
            "Generate lexical-similarity-based ontology mapping hypotheses "
            "from a source schema file (CSV or OpenAPI JSON) against an "
            "ontology profile (YAML).  Outputs a JSON mapping file, an "
            "SSSOM-inspired TSV, and a Markdown review report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help=(
            "Path to the source schema file.  "
            "Supported: CSV (.csv) or OpenAPI JSON (.json)."
        ),
    )
    parser.add_argument(
        "--ontology",
        required=True,
        metavar="PATH",
        help="Path to the ontology profile YAML file.",
    )
    parser.add_argument(
        "--output-dir",
        default="examples/outputs",
        metavar="DIR",
        help=(
            "Directory where output files will be written "
            "(default: examples/outputs)."
        ),
    )
    parser.add_argument(
        "--run-id",
        default=None,
        metavar="ID",
        help=(
            "Optional pipeline run identifier.  "
            "Defaults to a freshly generated UUID4."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable INFO-level logging to stdout.",
    )
    parser.add_argument(
        "--llm-adversarial-review",
        action="store_true",
        default=False,
        help=(
            "Use the LLM-backed adversarial reviewer (requires ANTHROPIC_API_KEY). "
            "When the API key is not set, falls back to the heuristic reviewer."
        ),
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        default=False,
        help=(
            "Activate LLM orchestration for candidate semantic scoring plus "
            "adversarial, ontology-engineer, and domain-scientist review stages. "
            "Requires the llm extra and ANTHROPIC_API_KEY for real LLM calls."
        ),
    )
    parser.add_argument(
        "--require-llm",
        action="store_true",
        default=False,
        help=(
            "Fail instead of falling back when --llm is set but an active LLM "
            "client cannot be created."
        ),
    )
    parser.add_argument(
        "--llm-model",
        default=default_llm_model,
        metavar="MODEL",
        help="Claude model ID used by LLM agents.",
    )
    parser.add_argument(
        "--domain-context",
        default=default_domain_context,
        metavar="TEXT",
        help=(
            "Domain context injected into the LLM domain-scientist reviewer "
            "when --llm is enabled."
        ),
    )
    parser.add_argument(
        "--llm-review-top-k",
        default=default_llm_review_top_k,
        type=int,
        metavar="N",
        help=(
            "Number of ranked hypotheses per source entity sent to each LLM "
            "reviewer when --llm is enabled (default: 1). Heuristic review "
            "still covers every hypothesis."
        ),
    )
    parser.add_argument(
        "--llm-candidate-top-k",
        default=default_llm_candidate_top_k,
        type=int,
        metavar="N",
        help=(
            "Number of lexical candidates per source entity sent to LLM semantic "
            "scoring (default: 2)."
        ),
    )
    parser.add_argument(
        "--llm-max-candidate-entities",
        default=default_llm_max_candidate_entities,
        type=int,
        metavar="N",
        help=(
            "Maximum number of source entities sent to LLM candidate scoring "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--llm-max-review-hypotheses",
        default=default_llm_max_review_hypotheses,
        type=int,
        metavar="N",
        help=(
            "Maximum number of hypotheses sent to each LLM reviewer "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--ledger",
        default=None,
        metavar="PATH",
        help=(
            "Optional path to a review ledger YAML file.  When provided, entities "
            "already approved or rejected in the ledger are skipped during candidate "
            "generation (re-run mode)."
        ),
    )

    args = parser.parse_args()

    result = run_pipeline(
        source_filepath=args.source,
        ontology_filepath=args.ontology,
        output_dir=args.output_dir,
        pipeline_run_id=args.run_id,
        verbose=args.verbose,
        llm_adversarial_review=args.llm_adversarial_review,
        llm_enabled=args.llm,
        require_llm=args.require_llm,
        llm_model=args.llm_model,
        domain_context=args.domain_context,
        llm_review_top_k=args.llm_review_top_k,
        llm_candidate_top_k=args.llm_candidate_top_k,
        llm_max_candidate_entities=args.llm_max_candidate_entities,
        llm_max_review_hypotheses=args.llm_max_review_hypotheses,
        ledger_path=args.ledger,
    )

    # Print summary to stdout regardless of verbose flag
    print()
    print("=" * 60)
    print("  Ontology Mapping Co-Scientist — Pipeline Complete")
    print("=" * 60)
    print(f"  Run ID              : {result['pipeline_run_id']}")
    print(f"  Source entities     : {result['total_source_entities']}")
    print(f"  Ontology terms      : {result['total_ontology_terms']}")
    print(f"  Hypotheses total    : {result['total_hypotheses']}")
    print(f"  Validation passed   : {result['hypotheses_passed_validation']}")
    print(f"  Validation failed   : {result['hypotheses_failed_validation']}")
    print(f"  Validation warnings : {result['hypotheses_with_warnings']}")
    print(f"  LLM orchestration    : {'enabled' if result['llm_enabled'] else 'disabled'}")
    if result["llm_enabled"]:
        print(
            "  LLM review targets   : "
            f"{result['llm_reviewed_hypotheses']} hypotheses "
            f"(top {result['llm_review_top_k']} per source)"
        )
        print(
            "  LLM candidate scoring: "
            f"{result['llm_candidate_entities_scored']} source entities"
        )
        print(f"  LLM budget           : {result['llm_budget']}")
        if result["llm_call_stats"]:
            print(f"  LLM call stats       : {result['llm_call_stats']}")
        if result["llm_disabled_reasons"]:
            print(f"  LLM disabled reasons : {result['llm_disabled_reasons']}")
    if result["llm_stage_modes"]:
        for stage_name, mode in result["llm_stage_modes"].items():
            print(f"    {stage_name:<25}: {mode}")
    print()
    print("  Output files:")
    print(f"    JSON    : {result['output_json']}")
    if result["output_tsv"]:
        print(f"    TSV     : {result['output_tsv']}")
    print(f"    Report  : {result['output_report']}")
    print(f"    Review  : {result['output_review_queue']}")
    print("=" * 60)
    print()
    print(
        "IMPORTANT: All mappings are HYPOTHESES.  They require human expert "
        "review before use in any production or research context."
    )
    print()


if __name__ == "__main__":
    main()
