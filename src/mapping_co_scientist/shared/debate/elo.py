from __future__ import annotations

from mapping_co_scientist.shared.debate.models import ArgumentSide, EvidenceType

EVIDENCE_WEIGHTS: dict[EvidenceType, float] = {
    EvidenceType.DOMAIN_DEFINITION_MATCH: 0.20,
    EvidenceType.INFORMATION_LOSS_RISK: 0.18,
    EvidenceType.SEMANTIC_OVERREACH: 0.18,
    EvidenceType.TYPE_INCOMPATIBILITY: 0.18,
    EvidenceType.STRUCTURAL_TYPE_MATCH: 0.15,
    EvidenceType.SCOPE_RELATIONSHIP: 0.15,
    EvidenceType.OPERATION_SAFETY: 0.15,
    EvidenceType.AMBIGUITY_UNRESOLVED: 0.12,
    EvidenceType.ADVERSARIAL_FLAG_REBUTTAL: 0.10,
    EvidenceType.MISSING_UNIT_COMPANION: 0.10,
    EvidenceType.PRECEDENT_CONSISTENCY: 0.08,
}

BASE_K = 32.0


def initial_elo(confidence: float) -> float:
    """Map a pipeline confidence score [0,1] to an initial Elo rating."""
    return 1000.0 + round(confidence * 800)


def k_factor(evidence_type: EvidenceType, argument_confidence: float) -> float:
    """Compute the K-factor for an argument given its evidence type and confidence."""
    return BASE_K * EVIDENCE_WEIGHTS[evidence_type] * argument_confidence


def expected_score(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score formula: probability that A beats B."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def apply_argument(
    ratings: dict[str, float],
    argued_id: str,
    side: ArgumentSide,
    evidence_type: EvidenceType,
    argument_confidence: float,
) -> dict[str, float]:
    """Apply a single debate argument to the ratings dict.

    FOR  = argued candidate wins vs all others (each opponent loses).
    AGAINST = argued candidate loses vs all others (each opponent wins).

    Returns a new ratings dict (does not mutate the input).
    """
    updated = dict(ratings)
    k = k_factor(evidence_type, argument_confidence)
    others = [cid for cid in updated if cid != argued_id]

    if not others:
        # Nothing to compare against; ratings unchanged.
        return updated

    argued_elo = updated[argued_id]

    for other_id in others:
        other_elo = updated[other_id]

        if side == ArgumentSide.FOR:
            # argued wins, other loses
            e_argued = expected_score(argued_elo, other_elo)
            e_other = 1.0 - e_argued
            delta_argued = k * (1.0 - e_argued)
            delta_other = k * (0.0 - e_other)
        else:
            # argued loses, other wins
            e_argued = expected_score(argued_elo, other_elo)
            e_other = 1.0 - e_argued
            delta_argued = k * (0.0 - e_argued)
            delta_other = k * (1.0 - e_other)

        updated[argued_id] = updated[argued_id] + delta_argued
        updated[other_id] = updated[other_id] + delta_other
        # Refresh the local read of argued_elo for subsequent iterations
        argued_elo = updated[argued_id]

    return updated


def apply_penalties(
    elo: float,
    overall_severity: str,
    has_exactmatch: bool,
    has_unrebutted_info_loss: bool,
    source_net_negative: bool,
    target_net_negative: bool,
) -> tuple[float, list[str]]:
    """Apply flat Elo penalty deductions and return (final_elo, list_of_reasons).

    Deductions are additive:
    - high adversarial severity  → -150
    - medium adversarial severity → -50
    - exactMatch predicate         → -200
    - unrebutted information loss  → -100
    - source advocate net negative → -50
    - target advocate net negative → -50
    """
    deductions: float = 0.0
    reasons: list[str] = []

    if overall_severity == "high":
        deductions += 150.0
        reasons.append("adversarial_severity:high (-150)")
    elif overall_severity == "medium":
        deductions += 50.0
        reasons.append("adversarial_severity:medium (-50)")

    if has_exactmatch:
        deductions += 200.0
        reasons.append("exactMatch_predicate (-200)")

    if has_unrebutted_info_loss:
        deductions += 100.0
        reasons.append("unrebutted_information_loss (-100)")

    if source_net_negative:
        deductions += 50.0
        reasons.append("source_advocate_net_negative (-50)")

    if target_net_negative:
        deductions += 50.0
        reasons.append("target_advocate_net_negative (-50)")

    final_elo = elo - deductions
    return final_elo, reasons
