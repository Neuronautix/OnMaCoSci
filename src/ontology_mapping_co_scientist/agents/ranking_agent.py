"""Ranking agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`RankingAgent`, which ranks competing mapping
hypotheses for the same source entity by combining confidence scores with
adversarial review penalties.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis
from ontology_mapping_co_scientist.models.review import AdversarialReviewResult

logger = logging.getLogger(__name__)


class RankingAgent:
    """Ranks competing mapping hypotheses for the same source entity."""

    def __init__(
        self,
        confidence_weight: float = 0.7,
        adversarial_penalty_weight: float = 0.3,
    ) -> None:
        """Initialise the ranking agent.

        Args:
            confidence_weight: Weight applied to the hypothesis confidence score
                when computing the final ranking score (default 0.7).
            adversarial_penalty_weight: Weight applied to the adversarial penalty
                when computing the final ranking score (default 0.3).
        """
        self.confidence_weight = confidence_weight
        self.adversarial_penalty_weight = adversarial_penalty_weight

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def rank_hypotheses(
        self,
        hypotheses: list[MappingHypothesis],
        adversarial_results: dict[str, AdversarialReviewResult],
    ) -> list[MappingHypothesis]:
        """Assign ranks to all hypotheses, grouped by source entity.

        For each group of hypotheses sharing the same source entity:

        1. Compute an *adversarial penalty* from the flags in the corresponding
           :class:`~ontology_mapping_co_scientist.models.review.AdversarialReviewResult`:
           ``0.1`` per medium-severity flag and ``0.2`` per high-severity flag.
        2. Compute a *final score*:
           ``confidence * confidence_weight - penalty * adversarial_penalty_weight``.
        3. Sort by final score descending and assign integer ranks (1 = best).

        Hypotheses without an adversarial result receive a penalty of ``0.0``.

        Args:
            hypotheses: All mapping hypotheses to rank.
            adversarial_results: Mapping from ``mapping_id`` to the
                corresponding :class:`~ontology_mapping_co_scientist.models.review.AdversarialReviewResult`.

        Returns:
            The same list of hypotheses (mutated in place) with :attr:`~.MappingHypothesis.rank`
            set.
        """
        # Group hypotheses by source entity id
        groups: dict[str, list[MappingHypothesis]] = defaultdict(list)
        for hypothesis in hypotheses:
            groups[hypothesis.source_entity.entity_id].append(hypothesis)

        for entity_id, group in groups.items():
            scored: list[tuple[MappingHypothesis, float]] = []

            for hypothesis in group:
                penalty = self._compute_adversarial_penalty(
                    hypothesis.mapping_id, adversarial_results
                )
                final_score = (
                    hypothesis.confidence * self.confidence_weight
                    - penalty * self.adversarial_penalty_weight
                )
                scored.append((hypothesis, final_score))

            # Sort descending by final_score
            scored.sort(key=lambda x: x[1], reverse=True)

            for rank, (hypothesis, final_score) in enumerate(scored, start=1):
                hypothesis.rank = rank
                logger.debug(
                    "Entity %s | rank=%d | mapping_id=%s | conf=%.3f | final_score=%.3f",
                    entity_id,
                    rank,
                    hypothesis.mapping_id,
                    hypothesis.confidence,
                    final_score,
                )

        logger.info(
            "Ranking complete for %d hypotheses across %d source entities.",
            len(hypotheses),
            len(groups),
        )
        return hypotheses

    def get_top_mapping(
        self, hypotheses: list[MappingHypothesis]
    ) -> dict[str, MappingHypothesis]:
        """Return the best-ranked hypothesis for each source entity.

        Iterates over all hypotheses and selects the one with ``rank == 1`` for
        each source entity.  If no hypothesis in a group has been ranked yet
        (all have ``rank is None``), the first hypothesis in the list is used as
        a fallback.

        Args:
            hypotheses: A list of (possibly already ranked) mapping hypotheses.

        Returns:
            A dict mapping source ``entity_id`` to the top-ranked
            :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingHypothesis`.
        """
        top: dict[str, MappingHypothesis] = {}

        # Collect all hypotheses per entity
        groups: dict[str, list[MappingHypothesis]] = defaultdict(list)
        for hypothesis in hypotheses:
            groups[hypothesis.source_entity.entity_id].append(hypothesis)

        for entity_id, group in groups.items():
            # Prefer rank=1 hypothesis; fall back to first in list
            best: MappingHypothesis | None = None
            for hypothesis in group:
                if hypothesis.rank == 1:
                    best = hypothesis
                    break
            if best is None:
                best = group[0]
            top[entity_id] = best

        return top

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_adversarial_penalty(
        self,
        mapping_id: str,
        adversarial_results: dict[str, AdversarialReviewResult],
    ) -> float:
        """Compute the adversarial penalty for a single hypothesis.

        The penalty is the sum of per-flag contributions:
        * ``0.1`` for each medium-severity flag.
        * ``0.2`` for each high-severity flag.
        * ``0.0`` for low-severity flags (informational only).

        Args:
            mapping_id: The mapping ID to look up in *adversarial_results*.
            adversarial_results: Dict mapping mapping_id to review result.

        Returns:
            A non-negative float penalty value.
        """
        result = adversarial_results.get(mapping_id)
        if result is None:
            return 0.0

        penalty = 0.0
        for flag in result.flags:
            if flag.severity == "medium":
                penalty += 0.1
            elif flag.severity == "high":
                penalty += 0.2
        return penalty
