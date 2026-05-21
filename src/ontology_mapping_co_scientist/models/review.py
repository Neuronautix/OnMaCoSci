"""Review-related models for the Ontology Mapping Co-Scientist system.

This module defines the data structures used during the adversarial review
and human review phases of the mapping pipeline.

The adversarial review phase is performed by a critic agent that inspects
each :class:`~.mapping_hypothesis.MappingHypothesis` for potential problems
and records them as :class:`AdversarialFlag` objects aggregated in an
:class:`AdversarialReviewResult`.

The human review phase is guided by :class:`SuggestedAction` recommendations
produced by pipeline agents, together with the :class:`HumanReviewAction`
enumeration that encodes the set of decisions a human reviewer can make.

Typical flow::

    AdversarialAgent inspects hypothesis
        -> produces AdversarialReviewResult (with zero or more AdversarialFlag items)
        -> if has_blocking_issues(), hypothesis is flagged for mandatory human review
        -> ReviewAgent generates SuggestedAction recommendations
        -> Human reviewer selects an action and updates hypothesis.human_review_status
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingPredicate


# ---------------------------------------------------------------------------
# Adversarial review models
# ---------------------------------------------------------------------------


class AdversarialFlag(BaseModel):
    """A single issue identified by an adversarial critic agent.

    An adversarial flag records one concrete problem found when scrutinising
    a :class:`~.mapping_hypothesis.MappingHypothesis`.  Multiple flags may
    be raised for the same hypothesis.

    Attributes:
        flag_type: A machine-readable tag categorising the type of issue.
            Well-known values include:

            * ``"weak_lexical_similarity"`` — the label match score is
              below an acceptable threshold.
            * ``"broad_narrow_ambiguity"`` — it is unclear whether the
              correct predicate is ``broadMatch`` or ``narrowMatch``.
            * ``"datatype_mismatch"`` — the source entity's datatype is
              incompatible with the ontology term's expected range.
            * ``"missing_definition"`` — the ontology term lacks a formal
              definition, making the mapping hard to validate.
            * ``"low_confidence"`` — the aggregate confidence score falls
              below the configured minimum threshold.
            * ``"synonym_only_match"`` — the match relies solely on a
              synonym rather than the preferred label.
            * ``"deprecated_term"`` — the target ontology term has been
              deprecated.
            * ``"multiple_equally_good_candidates"`` — two or more terms
              score identically, making the choice ambiguous.

        description: A human-readable explanation of what was found and why
            it is a concern.
        severity: How serious the issue is.  One of:

            * ``"low"`` — informational; the mapping is probably still
              usable but should be noted.
            * ``"medium"`` — the mapping may be acceptable but warrants
              human review before promotion.
            * ``"high"`` — the mapping should not be promoted without
              explicit human override; treated as a blocking issue.
    """

    flag_type: str = Field(
        ...,
        description=(
            "Machine-readable tag categorising the issue type, "
            "e.g. 'weak_lexical_similarity', 'datatype_mismatch'."
        ),
    )
    description: str = Field(
        ...,
        description="Human-readable explanation of the identified issue.",
    )
    severity: Literal["low", "medium", "high"] = Field(
        ...,
        description="Severity level: 'low', 'medium', or 'high'.",
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        """Return a concise string representation."""
        return (
            f"AdversarialFlag(type={self.flag_type!r}, "
            f"severity={self.severity!r})"
        )


class AdversarialReviewResult(BaseModel):
    """The aggregated result of an adversarial review for one mapping hypothesis.

    An :class:`AdversarialReviewResult` is produced by the adversarial critic
    agent for a single :class:`~.mapping_hypothesis.MappingHypothesis`.  It
    collects all :class:`AdversarialFlag` items found, computes an overall
    severity, and provides a high-level recommendation for downstream agents
    and human reviewers.

    Attributes:
        mapping_id: The :attr:`~.mapping_hypothesis.MappingHypothesis.mapping_id`
            of the hypothesis that was reviewed.  Used to correlate results
            back to the hypothesis without embedding the full object.
        flags: Zero or more flags raised during the adversarial review.  An
            empty list indicates a clean review.
        overall_severity: The highest severity level across all flags, or
            ``"clean"`` when no flags were raised.  One of
            ``"clean"``, ``"low"``, ``"medium"``, ``"high"``.
        recommendation: A high-level action recommendation for the next
            pipeline stage.  Typical values:

            * ``"proceed"`` — no significant issues; the hypothesis may be
              promoted to the human review queue as-is.
            * ``"review"`` — one or more medium-severity issues were found;
              human review is recommended before promotion.
            * ``"reject"`` — one or more high-severity (blocking) issues
              were found; the hypothesis should not be promoted without
              explicit remediation or human override.
    """

    mapping_id: str = Field(
        ...,
        description="ID of the MappingHypothesis that was reviewed.",
    )
    flags: list[AdversarialFlag] = Field(
        default_factory=list,
        description="All flags raised during adversarial review (empty = clean).",
    )
    overall_severity: Literal["clean", "low", "medium", "high"] = Field(
        ...,
        description=(
            "Highest severity across all flags, or 'clean' when no flags exist."
        ),
    )
    recommendation: str = Field(
        ...,
        description=(
            "High-level action recommendation, e.g. 'proceed', 'review', 'reject'."
        ),
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def has_blocking_issues(self) -> bool:
        """Return ``True`` if any flag has severity ``"high"``.

        A blocking issue means the mapping hypothesis must not be promoted to
        an approved state without explicit human intervention.  Downstream
        pipeline stages should check this method before auto-approving any
        hypothesis.

        Returns:
            ``True`` when at least one :class:`AdversarialFlag` in
            :attr:`flags` has ``severity == "high"``; ``False`` otherwise.

        Example::

            result = AdversarialReviewResult(
                mapping_id="map-001",
                flags=[AdversarialFlag(
                    flag_type="deprecated_term",
                    description="Target term is deprecated.",
                    severity="high",
                )],
                overall_severity="high",
                recommendation="reject",
            )
            assert result.has_blocking_issues() is True
        """
        return any(flag.severity == "high" for flag in self.flags)

    def __str__(self) -> str:
        """Return a concise string representation."""
        return (
            f"AdversarialReviewResult("
            f"mapping_id={self.mapping_id!r}, "
            f"overall_severity={self.overall_severity!r}, "
            f"recommendation={self.recommendation!r}, "
            f"flags={len(self.flags)})"
        )


# ---------------------------------------------------------------------------
# Human review action models
# ---------------------------------------------------------------------------


class HumanReviewAction(StrEnum):
    """The set of decisions a human reviewer can make about a mapping hypothesis.

    Each action maps to a corresponding update of
    :attr:`~.mapping_hypothesis.MappingHypothesis.human_review_status`.

    Attributes:
        APPROVE: The reviewer accepts the mapping exactly as proposed.
            Sets ``human_review_status`` to
            :attr:`~.mapping_hypothesis.HumanReviewStatus.APPROVED`.
        REJECT: The reviewer rejects the mapping entirely.
            Sets ``human_review_status`` to
            :attr:`~.mapping_hypothesis.HumanReviewStatus.REJECTED`.
        CHANGE_PREDICATE: The reviewer accepts the mapping target but wants
            to change the predicate (e.g. from ``closeMatch`` to
            ``exactMatch``).
            Sets ``human_review_status`` to
            :attr:`~.mapping_hypothesis.HumanReviewStatus.PREDICATE_CHANGED`.
        REQUEST_MORE_EVIDENCE: The reviewer cannot decide yet and requests
            that additional evidence be gathered.
            Sets ``human_review_status`` to
            :attr:`~.mapping_hypothesis.HumanReviewStatus.NEEDS_MORE_EVIDENCE`.
        CREATE_NEW_TERM: The reviewer determines that no existing ontology
            term is suitable and requests that a new term be created in the
            ontology.
            Sets ``human_review_status`` to
            :attr:`~.mapping_hypothesis.HumanReviewStatus.NEW_TERM_REQUESTED`.
    """

    APPROVE = "approve"
    REJECT = "reject"
    CHANGE_PREDICATE = "change_predicate"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    CREATE_NEW_TERM = "create_new_ontology_term"


class SuggestedAction(BaseModel):
    """A structured action recommendation produced by an agent for a human reviewer.

    Pipeline agents (e.g. the :class:`ReviewAgent`) may produce one or more
    :class:`SuggestedAction` objects alongside an
    :class:`AdversarialReviewResult` to guide the human reviewer towards the
    most appropriate decision.

    A :class:`SuggestedAction` is advisory only — the human reviewer is free
    to choose any :class:`HumanReviewAction` regardless of what is suggested.

    Attributes:
        action: The recommended :class:`HumanReviewAction`.
        reason: A human-readable explanation of *why* this action is
            recommended, citing specific evidence or flags where relevant.
        suggested_predicate: When :attr:`action` is
            :attr:`HumanReviewAction.CHANGE_PREDICATE`, this field carries
            the agent's recommended replacement predicate.  ``None`` for all
            other actions.
    """

    action: HumanReviewAction = Field(
        ...,
        description="The recommended human review action.",
    )
    reason: str = Field(
        ...,
        description=(
            "Human-readable explanation of why this action is recommended."
        ),
    )
    suggested_predicate: MappingPredicate | None = Field(
        default=None,
        description=(
            "Replacement predicate recommended when action is "
            "CHANGE_PREDICATE; None otherwise."
        ),
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        """Return a concise string representation."""
        base = f"SuggestedAction(action={self.action!r}, reason={self.reason!r}"
        if self.suggested_predicate is not None:
            base += f", suggested_predicate={self.suggested_predicate!r}"
        return base + ")"
