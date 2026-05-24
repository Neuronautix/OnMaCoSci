from __future__ import annotations

from typing import Any

from mapping_co_scientist.shared.debate.consistency import CrossMappingConsistencyAnalyzer
from mapping_co_scientist.shared.debate.elo import (
    apply_argument,
    apply_penalties,
    initial_elo,
)
from mapping_co_scientist.shared.debate.heuristic_advocates import (
    HeuristicSourceAdvocate,
    HeuristicTargetAdvocate,
)
from mapping_co_scientist.shared.debate.models import (
    ArgumentSide,
    CandidateEloResult,
    DebateArgument,
    DebateReport,
    EntityDebateResult,
    EvidenceType,
)
from mapping_co_scientist.shared.models.review import AdversarialReviewResult

# Elo tier boundaries
_TIER1_MAX_ELO = 1250.0
_TIER2_MAX_ELO = 1500.0


def _get_source_id(hypothesis: Any, run_type: str) -> str:
    if run_type == "ontology_align":
        return hypothesis.source_concept.entity_id
    path = getattr(hypothesis, "source_path", None)
    return path if path is not None else "__constant__"


def _get_source_label(hypothesis: Any, run_type: str) -> str:
    if run_type == "ontology_align":
        return hypothesis.source_concept.label
    path = getattr(hypothesis, "source_path", None)
    return path if path is not None else "__constant__"


def _get_target_label(hypothesis: Any, run_type: str) -> str:
    if run_type == "ontology_align":
        return hypothesis.target_ontology_entity.term_id
    return getattr(hypothesis, "target_path", "unknown")


def _compute_net_advocacy(
    arguments: list[DebateArgument],
    advocate: str,
) -> float:
    """Compute signed net advocacy for an advocate across all its arguments.

    FOR arguments contribute positively, AGAINST negatively.
    Weight is evidence_weight * confidence.
    """
    from mapping_co_scientist.shared.debate.elo import EVIDENCE_WEIGHTS

    total = 0.0
    for arg in arguments:
        if arg.advocate != advocate:
            continue
        weight = EVIDENCE_WEIGHTS.get(arg.evidence_type, 0.10)
        signed = arg.confidence * weight
        if arg.side == ArgumentSide.AGAINST:
            signed = -signed
        total += signed
    return total


def _has_exactmatch(hypothesis: Any, run_type: str) -> bool:
    if run_type == "schema_align":
        return False
    from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
        OntologyRelation,
    )
    return hypothesis.ontology_relation == OntologyRelation.EXACT_MATCH


def _has_unrebutted_info_loss(
    hypothesis: Any,
    run_type: str,
    candidate_arguments: list[DebateArgument],
) -> bool:
    if run_type == "ontology_align":
        return False
    if not getattr(hypothesis, "information_loss", False):
        return False
    # Unrebutted if there is no FOR adversarial_flag_rebuttal argument for this candidate
    has_rebuttal = any(
        arg.side == ArgumentSide.FOR
        and arg.evidence_type == EvidenceType.ADVERSARIAL_FLAG_REBUTTAL
        for arg in candidate_arguments
    )
    return not has_rebuttal


class MappingMediatorEngine:
    """Orchestrates the three-agent Elo debate for all source entities."""

    def __init__(self) -> None:
        self._source_advocate = HeuristicSourceAdvocate()
        self._target_advocate = HeuristicTargetAdvocate()
        self._consistency_analyzer = CrossMappingConsistencyAnalyzer()

    def run_debate(
        self,
        hypotheses_by_source: dict[str, list[Any]],
        run_type: str,
        adversarial_results: dict[str, AdversarialReviewResult],
        run_id: str,
    ) -> DebateReport:
        entity_results: list[EntityDebateResult] = []

        for source_id, hyps in hypotheses_by_source.items():
            # Skip constant-assignment entries
            if source_id == "__constant__":
                continue
            if not hyps:
                continue

            result = self._debate_one_source(
                source_id=source_id,
                hypotheses=hyps,
                run_type=run_type,
                adversarial_results=adversarial_results,
            )
            entity_results.append(result)

        consistency = self._consistency_analyzer.analyze(
            entity_results=entity_results,
            run_type=run_type,
            run_id=run_id,
        )

        return DebateReport(
            run_id=run_id,
            run_type=run_type,  # type: ignore[arg-type]
            entity_results=entity_results,
            consistency=consistency,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _debate_one_source(
        self,
        source_id: str,
        hypotheses: list[Any],
        run_type: str,
        adversarial_results: dict[str, AdversarialReviewResult],
    ) -> EntityDebateResult:
        source_label = _get_source_label(hypotheses[0], run_type)

        # Sort by pipeline confidence descending to establish pipeline rank
        pipeline_ranked = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
        pipeline_top1_id: str = pipeline_ranked[0].mapping_id

        # Assign pipeline ranks
        pipeline_rank_map: dict[str, int] = {
            h.mapping_id: idx + 1 for idx, h in enumerate(pipeline_ranked)
        }

        # ------ Round 1: generate advocate arguments per hypothesis ------
        all_arguments: list[DebateArgument] = []
        source_args_by_id: dict[str, list[DebateArgument]] = {}
        target_args_by_id: dict[str, list[DebateArgument]] = {}

        for hyp in hypotheses:
            src_args = self._source_advocate.generate_arguments(
                hypothesis=hyp,
                run_type=run_type,
                all_hypotheses_for_source=hypotheses,
            )
            tgt_args = self._target_advocate.generate_arguments(
                hypothesis=hyp,
                run_type=run_type,
                all_hypotheses_for_source=hypotheses,
            )
            source_args_by_id[hyp.mapping_id] = src_args
            target_args_by_id[hyp.mapping_id] = tgt_args
            all_arguments.extend(src_args)
            all_arguments.extend(tgt_args)

        # ------ Compute per-hypothesis Elo ratings ------
        ratings: dict[str, float] = {
            hyp.mapping_id: initial_elo(hyp.confidence) for hyp in hypotheses
        }

        # Apply source advocate Round 1 arguments
        for hyp in hypotheses:
            for arg in source_args_by_id[hyp.mapping_id]:
                ratings = apply_argument(
                    ratings=ratings,
                    argued_id=hyp.mapping_id,
                    side=arg.side,
                    evidence_type=arg.evidence_type,
                    argument_confidence=arg.confidence,
                )

        # Apply target advocate Round 1 arguments
        for hyp in hypotheses:
            for arg in target_args_by_id[hyp.mapping_id]:
                ratings = apply_argument(
                    ratings=ratings,
                    argued_id=hyp.mapping_id,
                    side=arg.side,
                    evidence_type=arg.evidence_type,
                    argument_confidence=arg.confidence,
                )

        elo_after_debate: dict[str, float] = dict(ratings)

        # ------ Penalties ------
        blocking_concerns: list[str] = []
        candidate_results_map: dict[str, CandidateEloResult] = {}

        for hyp in hypotheses:
            mid = hyp.mapping_id
            hyp_args = source_args_by_id[mid] + target_args_by_id[mid]

            # Get adversarial result for this hypothesis (or use the pipeline top-1's result)
            adv_result = adversarial_results.get(mid)
            overall_severity = adv_result.overall_severity if adv_result else "clean"

            has_em = _has_exactmatch(hyp, run_type)
            has_uil = _has_unrebutted_info_loss(hyp, run_type, hyp_args)

            # Net source / target advocacy for this candidate's arguments
            src_net = _compute_net_advocacy(hyp_args, "source")
            tgt_net = _compute_net_advocacy(hyp_args, "target")

            elo_before_penalty = elo_after_debate[mid]
            final_elo, penalty_reasons = apply_penalties(
                elo=elo_before_penalty,
                overall_severity=overall_severity,
                has_exactmatch=has_em,
                has_unrebutted_info_loss=has_uil,
                source_net_negative=(src_net < 0),
                target_net_negative=(tgt_net < 0),
            )

            total_penalty = elo_before_penalty - final_elo

            # Collect blocking concerns from adversarial flags
            if adv_result and adv_result.has_blocking_issues():
                blocking_concerns.append(
                    f"{mid}: adversarial severity=high ({adv_result.recommendation})"
                )

            candidate_results_map[mid] = CandidateEloResult(
                mapping_id=mid,
                target_label=_get_target_label(hyp, run_type),
                pipeline_confidence=hyp.confidence,
                pipeline_rank=pipeline_rank_map[mid],
                initial_elo=initial_elo(hyp.confidence),
                elo_after_debate=elo_after_debate[mid],
                elo_penalties=total_penalty,
                final_elo=final_elo,
                debate_rank=0,  # placeholder, assigned below
                rank_inverted=False,  # placeholder
                penalty_reasons=penalty_reasons,
            )

        # ------ Assign debate ranks ------
        debate_ranked = sorted(
            candidate_results_map.values(),
            key=lambda c: c.final_elo,
            reverse=True,
        )

        final_candidates: list[CandidateEloResult] = []
        for debate_rank_idx, cand in enumerate(debate_ranked, start=1):
            rank_inverted = debate_rank_idx != cand.pipeline_rank
            final_candidates.append(
                CandidateEloResult(
                    mapping_id=cand.mapping_id,
                    target_label=cand.target_label,
                    pipeline_confidence=cand.pipeline_confidence,
                    pipeline_rank=cand.pipeline_rank,
                    initial_elo=cand.initial_elo,
                    elo_after_debate=cand.elo_after_debate,
                    elo_penalties=cand.elo_penalties,
                    final_elo=cand.final_elo,
                    debate_rank=debate_rank_idx,
                    rank_inverted=rank_inverted,
                    penalty_reasons=cand.penalty_reasons,
                )
            )

        debate_top1 = final_candidates[0]
        debate_top1_id = debate_top1.mapping_id
        entity_rank_inverted = debate_top1_id != pipeline_top1_id

        # ------ Tier assignment ------
        top_elo = debate_top1.final_elo
        has_blocking = bool(blocking_concerns)

        if top_elo < _TIER1_MAX_ELO or entity_rank_inverted or has_blocking:
            tier = 1
            tier_reason = (
                "final_elo < 1250" if top_elo < _TIER1_MAX_ELO
                else ("rank_inverted" if entity_rank_inverted else "blocking_concerns")
            )
        elif top_elo < _TIER2_MAX_ELO:
            tier = 2
            tier_reason = f"final_elo {top_elo:.0f} in [1250, 1500)"
        else:
            tier = 3
            tier_reason = f"final_elo {top_elo:.0f} ≥ 1500 with no blocking concerns"

        # ------ Recommended action ------
        if tier == 1 and has_blocking:
            recommended_action = "escalate_to_human_review: blocking adversarial flags present"
        elif tier == 1 and entity_rank_inverted:
            recommended_action = (
                f"review_rank_inversion: debate prefers '{debate_top1_id}' over "
                f"pipeline top1 '{pipeline_top1_id}'"
            )
        elif tier == 1:
            recommended_action = "request_additional_evidence: low Elo after debate"
        elif tier == 2:
            recommended_action = "proceed_with_caution: moderate confidence, human spot-check advised"
        else:
            recommended_action = "approved_for_release_pending_human_sign_off"

        return EntityDebateResult(
            source_id=source_id,
            source_label=source_label,
            pipeline_top1_id=pipeline_top1_id,
            debate_top1_id=debate_top1_id,
            rank_inverted=entity_rank_inverted,
            tier=tier,  # type: ignore[arg-type]
            tier_reason=tier_reason,
            arguments=all_arguments,
            candidates=final_candidates,
            blocking_concerns=blocking_concerns,
            recommended_action=recommended_action,
        )


def run_debate(
    hypotheses_by_source: dict[str, list[Any]],
    run_type: str,
    adversarial_results: dict[str, AdversarialReviewResult],
    run_id: str,
) -> DebateReport:
    """Convenience function: create a MappingMediatorEngine and run the debate."""
    engine = MappingMediatorEngine()
    return engine.run_debate(
        hypotheses_by_source=hypotheses_by_source,
        run_type=run_type,
        adversarial_results=adversarial_results,
        run_id=run_id,
    )
