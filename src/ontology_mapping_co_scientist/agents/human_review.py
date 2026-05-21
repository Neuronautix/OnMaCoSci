"""Human review agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`HumanReviewAgent`, which prepares structured
review packets to guide human experts through the final approval step of the
ontology mapping pipeline.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    MappingHypothesis,
    MappingPredicate,
)
from ontology_mapping_co_scientist.models.review import (
    AdversarialReviewResult,
    HumanReviewAction,
    SuggestedAction,
)

logger = logging.getLogger(__name__)

# Maximum number of alternative mappings included in a review packet
_MAX_ALTERNATIVES = 3


class HumanReviewAgent:
    """Prepares structured review packets for human expert review."""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def suggest_action(
        self,
        hypothesis: MappingHypothesis,
        adv_result: AdversarialReviewResult | None = None,
    ) -> SuggestedAction:
        """Recommend a :class:`~ontology_mapping_co_scientist.models.review.HumanReviewAction` for a hypothesis.

        Decision logic (evaluated in order):

        1. If predicate is ``NO_MAPPING`` → suggest
           :attr:`~HumanReviewAction.CREATE_NEW_TERM` (with a note to
           :attr:`~HumanReviewAction.REJECT` if the field simply does not
           warrant ontology coverage).
        2. If the adversarial result has blocking (high-severity) issues →
           suggest :attr:`~HumanReviewAction.REQUEST_MORE_EVIDENCE`.
        3. If confidence ≥ 0.85 and no high-severity flags → suggest
           :attr:`~HumanReviewAction.APPROVE`.
        4. If confidence ≥ 0.65 → suggest :attr:`~HumanReviewAction.APPROVE`
           with a cautionary note.
        5. If predicate is ``BROAD_MATCH`` or ``NARROW_MATCH`` → suggest
           :attr:`~HumanReviewAction.CHANGE_PREDICATE`.
        6. Otherwise → suggest :attr:`~HumanReviewAction.REQUEST_MORE_EVIDENCE`.

        Args:
            hypothesis: The mapping hypothesis to evaluate.
            adv_result: Optional adversarial review result for this hypothesis.

        Returns:
            A :class:`~ontology_mapping_co_scientist.models.review.SuggestedAction`
            with a recommended action and reasoning.
        """
        # 1. No mapping found
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return SuggestedAction(
                action=HumanReviewAction.CREATE_NEW_TERM,
                reason=(
                    f"No suitable ontology term was found for "
                    f"'{hypothesis.source_entity.label}'. Consider requesting a new "
                    "ontology term, or use REJECT if this field does not require "
                    "formal ontology coverage."
                ),
            )

        has_blocking = adv_result is not None and adv_result.has_blocking_issues()

        # 2. Blocking adversarial issues present
        if has_blocking:
            flag_summaries = "; ".join(
                f"{f.flag_type} ({f.severity})"
                for f in adv_result.flags  # type: ignore[union-attr]
                if f.severity == "high"
            )
            return SuggestedAction(
                action=HumanReviewAction.REQUEST_MORE_EVIDENCE,
                reason=(
                    f"The adversarial review raised blocking issues that prevent "
                    f"automatic promotion: {flag_summaries}. Additional evidence or "
                    "expert validation is required before this mapping can be approved."
                ),
            )

        # Count high-severity flags (non-blocking should not exist here, but guard anyway)
        high_flag_count = (
            sum(1 for f in adv_result.flags if f.severity == "high")
            if adv_result is not None
            else 0
        )

        # 3. High confidence, no blocking flags
        if hypothesis.confidence >= 0.85 and high_flag_count == 0:
            return SuggestedAction(
                action=HumanReviewAction.APPROVE,
                reason=(
                    f"Confidence is {hypothesis.confidence:.3f} (≥ 0.85) and the "
                    "adversarial review found no blocking issues. This mapping is a "
                    "strong candidate for approval."
                ),
            )

        # 4. Moderate confidence
        if hypothesis.confidence >= 0.65:
            medium_count = (
                sum(1 for f in adv_result.flags if f.severity == "medium")
                if adv_result is not None
                else 0
            )
            note = (
                f" Note: {medium_count} medium-severity flag(s) were raised."
                if medium_count > 0
                else ""
            )
            return SuggestedAction(
                action=HumanReviewAction.APPROVE,
                reason=(
                    f"Confidence is {hypothesis.confidence:.3f} (≥ 0.65), indicating "
                    f"a reasonable match between '{hypothesis.source_entity.label}' "
                    f"and '{hypothesis.target_entity.label}'.{note} Please verify "
                    "before approving."
                ),
            )

        # 5. Directional predicates need human expertise
        if hypothesis.predicate in (
            MappingPredicate.BROAD_MATCH,
            MappingPredicate.NARROW_MATCH,
        ):
            direction = (
                "broader" if hypothesis.predicate == MappingPredicate.BROAD_MATCH
                else "narrower"
            )
            return SuggestedAction(
                action=HumanReviewAction.CHANGE_PREDICATE,
                reason=(
                    f"The proposed predicate ({hypothesis.predicate.value}) implies "
                    f"the target term is semantically {direction} than the source. "
                    "This directional relationship is difficult to determine "
                    "automatically — a domain expert should confirm or adjust the "
                    "predicate."
                ),
                suggested_predicate=MappingPredicate.CLOSE_MATCH,
            )

        # 6. Default: request more evidence
        return SuggestedAction(
            action=HumanReviewAction.REQUEST_MORE_EVIDENCE,
            reason=(
                f"Confidence is {hypothesis.confidence:.3f}, which is below the "
                "threshold for automatic approval. Additional evidence (e.g. "
                "definition matching, example value analysis) is needed to improve "
                "confidence before this mapping can be promoted."
            ),
        )

    def prepare_review_packet(
        self,
        source_entity_id: str,
        hypotheses: list[MappingHypothesis],
        adv_results: dict[str, AdversarialReviewResult],
    ) -> dict:
        """Build a structured review packet for a single source entity.

        The packet contains:

        * ``source_entity_id`` — the entity being mapped.
        * ``source_entity_label`` — human-readable label of the entity.
        * ``top_mapping`` — serialised :class:`MappingHypothesis` with rank 1.
        * ``alternative_mappings`` — up to three lower-ranked hypotheses.
        * ``suggested_action`` — a :class:`~ontology_mapping_co_scientist.models.review.SuggestedAction`
          for the top mapping.
        * ``all_warnings`` — aggregated warnings from all hypotheses.

        Args:
            source_entity_id: The entity ID being reviewed.
            hypotheses: All hypotheses for this source entity, sorted by rank
                ascending (rank 1 first).
            adv_results: Mapping from ``mapping_id`` to adversarial review result.

        Returns:
            A dict ready for serialisation into a review interface or report.
        """
        if not hypotheses:
            logger.warning(
                "prepare_review_packet called with empty hypotheses for entity %s",
                source_entity_id,
            )
            return {
                "source_entity_id": source_entity_id,
                "source_entity_label": source_entity_id,
                "top_mapping": None,
                "alternative_mappings": [],
                "suggested_action": None,
                "all_warnings": [],
            }

        # Sort by rank (treat None as infinity)
        sorted_hyps = sorted(
            hypotheses, key=lambda h: h.rank if h.rank is not None else 9999
        )
        top = sorted_hyps[0]
        alternatives = sorted_hyps[1: 1 + _MAX_ALTERNATIVES]

        adv_result_for_top = adv_results.get(top.mapping_id)
        suggested_action = self.suggest_action(top, adv_result_for_top)

        # Aggregate all warnings
        all_warnings: list[str] = []
        for hyp in sorted_hyps:
            all_warnings.extend(hyp.warnings)
        # Deduplicate while preserving order
        seen_warnings: set[str] = set()
        deduped_warnings: list[str] = []
        for w in all_warnings:
            if w not in seen_warnings:
                seen_warnings.add(w)
                deduped_warnings.append(w)

        return {
            "source_entity_id": source_entity_id,
            "source_entity_label": top.source_entity.label,
            "top_mapping": top.model_dump(),
            "alternative_mappings": [h.model_dump() for h in alternatives],
            "suggested_action": suggested_action.model_dump(),
            "all_warnings": deduped_warnings,
        }

    def prepare_all_packets(
        self,
        hypotheses: list[MappingHypothesis],
        adv_results: dict[str, AdversarialReviewResult],
    ) -> list[dict]:
        """Prepare review packets for all source entities in *hypotheses*.

        Groups hypotheses by source entity and calls
        :meth:`prepare_review_packet` for each group.

        Args:
            hypotheses: The full list of ranked mapping hypotheses.
            adv_results: Mapping from ``mapping_id`` to adversarial review result.

        Returns:
            A list of review packet dicts, one per unique source entity.
        """
        groups: dict[str, list[MappingHypothesis]] = defaultdict(list)
        for hyp in hypotheses:
            groups[hyp.source_entity.entity_id].append(hyp)

        packets: list[dict] = []
        for entity_id, group in groups.items():
            packet = self.prepare_review_packet(entity_id, group, adv_results)
            packets.append(packet)

        logger.info(
            "Prepared %d review packets for %d source entities.",
            len(packets),
            len(groups),
        )
        return packets
