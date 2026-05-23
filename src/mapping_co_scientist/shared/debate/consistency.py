from __future__ import annotations

from collections import defaultdict

from mapping_co_scientist.shared.debate.models import (
    AmbiguousEntry,
    CollisionEntry,
    ConsistencyReport,
    CoverageRow,
    EntityDebateResult,
    RankInversionEntry,
)

# Threshold below which two candidates are considered ambiguous
_AMBIGUITY_ELO_DELTA = 50.0

# Threshold above which the top candidate is considered strongly isolated
_STRONG_ISOLATION_ELO_DELTA = 200.0

# Threshold above which a candidate is considered "debate_mapped"
_MAPPED_ELO_THRESHOLD = 1150.0


def _infer_entity_type(source_label: str, run_type: str) -> str:
    """Infer a rough entity type from the source label for coverage grouping."""
    if run_type == "schema_align":
        return "field"
    label_lower = source_label.lower()
    if "id" in label_lower or "identifier" in label_lower:
        return "identifier"
    if any(kw in label_lower for kw in ("weight", "length", "height", "age", "count", "score")):
        return "measurement"
    return "concept"


class CrossMappingConsistencyAnalyzer:
    """Produces cross-mapping consistency metrics from per-entity debate results."""

    def analyze(
        self,
        entity_results: list[EntityDebateResult],
        run_type: str,
        run_id: str = "unknown",
    ) -> ConsistencyReport:
        total_entities = len(entity_results)

        # ---- Rank inversions ----
        rank_inversion_entries: list[RankInversionEntry] = []
        for er in entity_results:
            if er.rank_inverted:
                rank_inversion_entries.append(
                    RankInversionEntry(
                        source=er.source_id,
                        pipeline_top1=er.pipeline_top1_id,
                        debate_top1=er.debate_top1_id,
                        reason=(
                            f"Debate re-ranked: pipeline top1={er.pipeline_top1_id!r}, "
                            f"debate top1={er.debate_top1_id!r}"
                        ),
                    )
                )

        # ---- Collision detection ----
        # A collision is when two different sources share the same debate_top1_id
        debate_top1_to_sources: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for er in entity_results:
            top_candidate = None
            for cand in er.candidates:
                if cand.debate_rank == 1:
                    top_candidate = cand
                    break
            if top_candidate is not None:
                debate_top1_to_sources[er.debate_top1_id].append(
                    (er.source_id, top_candidate.final_elo)
                )

        collision_entries: list[CollisionEntry] = []
        for target, sources in debate_top1_to_sources.items():
            if len(sources) >= 2:
                # Emit a collision entry for each pair
                for i in range(len(sources)):
                    for j in range(i + 1, len(sources)):
                        src1, elo1 = sources[i]
                        src2, elo2 = sources[j]
                        collision_entries.append(
                            CollisionEntry(
                                target=target,
                                source_1=src1,
                                source_2=src2,
                                elo_1=elo1,
                                elo_2=elo2,
                                recommendation=(
                                    f"Review both '{src1}' and '{src2}' — they compete "
                                    f"for the same target '{target}'; consider alternative "
                                    f"targets or merge strategy."
                                ),
                            )
                        )

        # ---- Ambiguous top1 / strong isolations ----
        ambiguous_entries: list[AmbiguousEntry] = []
        strong_isolations = 0

        for er in entity_results:
            if len(er.candidates) < 2:
                continue
            # Sort candidates by debate_rank to find top-2
            sorted_cands = sorted(er.candidates, key=lambda c: c.debate_rank)
            top1 = sorted_cands[0]
            top2 = sorted_cands[1]
            delta = top1.final_elo - top2.final_elo

            if abs(delta) < _AMBIGUITY_ELO_DELTA:
                ambiguous_entries.append(
                    AmbiguousEntry(
                        source=er.source_id,
                        candidate_a=top1.mapping_id,
                        elo_a=top1.final_elo,
                        candidate_b=top2.mapping_id,
                        elo_b=top2.final_elo,
                    )
                )
            elif delta > _STRONG_ISOLATION_ELO_DELTA:
                strong_isolations += 1

        # ---- Coverage by entity type ----
        type_buckets: dict[str, list[EntityDebateResult]] = defaultdict(list)
        for er in entity_results:
            entity_type = _infer_entity_type(er.source_label, run_type)
            type_buckets[entity_type].append(er)

        coverage_rows: list[CoverageRow] = []
        for entity_type, results in sorted(type_buckets.items()):
            debate_mapped = 0
            for er in results:
                top_cand = next(
                    (c for c in er.candidates if c.debate_rank == 1), None
                )
                if top_cand is not None and top_cand.final_elo > _MAPPED_ELO_THRESHOLD:
                    debate_mapped += 1
            unmapped = len(results) - debate_mapped
            coverage_rows.append(
                CoverageRow(
                    entity_type=entity_type,
                    count=len(results),
                    debate_mapped=debate_mapped,
                    unmapped=unmapped,
                )
            )

        return ConsistencyReport(
            run_id=run_id,
            total_entities=total_entities,
            rank_inversions=len(rank_inversion_entries),
            collisions=len(collision_entries),
            ambiguous_top1=len(ambiguous_entries),
            strong_isolations=strong_isolations,
            collision_entries=collision_entries,
            rank_inversion_entries=rank_inversion_entries,
            ambiguous_entries=ambiguous_entries,
            coverage_by_type=coverage_rows,
        )
