from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ArgumentSide(StrEnum):
    FOR = "for"
    AGAINST = "against"


class EvidenceType(StrEnum):
    DOMAIN_DEFINITION_MATCH = "domain_definition_match"
    STRUCTURAL_TYPE_MATCH = "structural_type_match"
    SCOPE_RELATIONSHIP = "scope_relationship"
    OPERATION_SAFETY = "operation_safety"
    ADVERSARIAL_FLAG_REBUTTAL = "adversarial_flag_rebuttal"
    INFORMATION_LOSS_RISK = "information_loss_risk"
    SEMANTIC_OVERREACH = "semantic_overreach"
    TYPE_INCOMPATIBILITY = "type_incompatibility"
    AMBIGUITY_UNRESOLVED = "ambiguity_unresolved"
    MISSING_UNIT_COMPANION = "missing_unit_companion"
    PRECEDENT_CONSISTENCY = "precedent_consistency"


class DebateArgument(BaseModel):
    round: int  # 1 or 2
    advocate: Literal["source", "target"]
    side: ArgumentSide
    evidence_type: EvidenceType
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)
    counterpoint_weakness: str | None = None
    rebuts_argument_index: int | None = None  # round-2 only

    model_config = {"frozen": True}


class CandidateEloResult(BaseModel):
    mapping_id: str
    target_label: str  # target_id or target_path for display
    pipeline_confidence: float
    pipeline_rank: int
    initial_elo: float
    elo_after_debate: float
    elo_penalties: float  # total deducted
    final_elo: float
    debate_rank: int
    rank_inverted: bool  # debate_rank != pipeline_rank
    penalty_reasons: list[str]

    model_config = {"frozen": True}


class EntityDebateResult(BaseModel):
    source_id: str  # entity_id or source_path
    source_label: str
    pipeline_top1_id: str
    debate_top1_id: str
    rank_inverted: bool
    tier: Literal[1, 2, 3]
    tier_reason: str
    arguments: list[DebateArgument]
    candidates: list[CandidateEloResult]
    blocking_concerns: list[str]
    recommended_action: str

    model_config = {"frozen": True}


class CollisionEntry(BaseModel):
    target: str
    source_1: str
    source_2: str
    elo_1: float
    elo_2: float
    recommendation: str
    model_config = {"frozen": True}


class RankInversionEntry(BaseModel):
    source: str
    pipeline_top1: str
    debate_top1: str
    reason: str
    model_config = {"frozen": True}


class AmbiguousEntry(BaseModel):
    source: str
    candidate_a: str
    elo_a: float
    candidate_b: str
    elo_b: float
    model_config = {"frozen": True}


class CoverageRow(BaseModel):
    entity_type: str
    count: int
    debate_mapped: int  # final_elo > 1150
    unmapped: int
    model_config = {"frozen": True}


class ConsistencyReport(BaseModel):
    run_id: str
    total_entities: int
    rank_inversions: int
    collisions: int
    ambiguous_top1: int
    strong_isolations: int
    collision_entries: list[CollisionEntry]
    rank_inversion_entries: list[RankInversionEntry]
    ambiguous_entries: list[AmbiguousEntry]
    coverage_by_type: list[CoverageRow]
    model_config = {"frozen": True}


class DebateReport(BaseModel):
    run_id: str
    run_type: Literal["ontology_align", "schema_align"]
    entity_results: list[EntityDebateResult]
    consistency: ConsistencyReport
    model_config = {"frozen": True}
