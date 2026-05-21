"""Core mapping hypothesis model.

This module defines the central data structure of the Ontology Mapping
Co-Scientist system: :class:`MappingHypothesis`.  A mapping hypothesis
represents a *proposed* link between a :class:`~.entities.SourceEntity` and
an :class:`~.entities.OntologyTerm`, together with the evidence, confidence
score, lifecycle status, and provenance required to track it through the
entire pipeline.

Supporting types defined here:

* :class:`MappingPredicate` — SKOS-based predicates that characterise the
  *nature* of the mapping relationship.
* :class:`ValidationStatus` — automated validation lifecycle states.
* :class:`HumanReviewStatus` — human-in-the-loop review lifecycle states.
* :class:`Evidence` — a single piece of supporting (or counter) evidence.
* :class:`Provenance` — how, when, and by whom the hypothesis was created.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MappingPredicate(StrEnum):
    """SKOS-based predicates that describe the relationship between a source
    entity and an ontology term.

    Values follow the SKOS vocabulary (https://www.w3.org/TR/skos-reference/)
    with two custom extensions for pipeline-specific cases.

    Attributes:
        EXACT_MATCH: The source entity and the ontology term can be used
            interchangeably without any loss of meaning
            (``skos:exactMatch``).
        CLOSE_MATCH: The entities are sufficiently similar for most practical
            purposes but not strictly equivalent
            (``skos:closeMatch``).
        BROAD_MATCH: The ontology term is semantically broader (more general)
            than the source entity (``skos:broadMatch``).
        NARROW_MATCH: The ontology term is semantically narrower (more
            specific) than the source entity (``skos:narrowMatch``).
        RELATED_MATCH: The two concepts are related but do not fit any of the
            directional match categories (``skos:relatedMatch``).
        REQUIRES_TRANSFORM: A mapping exists but can only be expressed after
            a value transformation (e.g. unit conversion, string
            normalisation) (``custom:requiresTransform``).
        NO_MAPPING: No suitable ontology term exists; the source entity
            cannot be mapped (``custom:noMapping``).
    """

    EXACT_MATCH = "skos:exactMatch"
    CLOSE_MATCH = "skos:closeMatch"
    BROAD_MATCH = "skos:broadMatch"
    NARROW_MATCH = "skos:narrowMatch"
    RELATED_MATCH = "skos:relatedMatch"
    REQUIRES_TRANSFORM = "custom:requiresTransform"
    NO_MAPPING = "custom:noMapping"


class ValidationStatus(StrEnum):
    """Automated validation lifecycle state for a :class:`MappingHypothesis`.

    Attributes:
        PENDING: The hypothesis has not yet been validated by any automated
            check.
        PASSED: All automated validation checks passed.
        FAILED: One or more automated validation checks failed; the
            hypothesis should not be promoted without remediation.
        WARNING: Automated checks passed but flagged one or more non-fatal
            concerns that require attention.
    """

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class HumanReviewStatus(StrEnum):
    """Human-in-the-loop review lifecycle state for a :class:`MappingHypothesis`.

    Attributes:
        AWAITING_REVIEW: The hypothesis is queued for human review and no
            decision has been made yet.
        APPROVED: A human reviewer has accepted the mapping as-is.
        REJECTED: A human reviewer has rejected the mapping.
        NEEDS_MORE_EVIDENCE: The reviewer requires additional evidence before
            approving or rejecting.
        PREDICATE_CHANGED: The reviewer accepted the mapping target but
            changed the predicate (e.g. from ``closeMatch`` to
            ``exactMatch``).
        NEW_TERM_REQUESTED: The reviewer determined that no existing ontology
            term is appropriate and has requested that a new term be created.
    """

    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    PREDICATE_CHANGED = "predicate_changed"
    NEW_TERM_REQUESTED = "new_term_requested"


# ---------------------------------------------------------------------------
# Supporting value objects
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """A single piece of evidence supporting or contradicting a mapping.

    Evidence items are collected into :attr:`MappingHypothesis.evidence`
    (supporting) and :attr:`MappingHypothesis.counter_evidence` (opposing)
    lists.  Each item records how the evidence was derived, a human-readable
    description, and an optional normalised score.

    Attributes:
        evidence_type: A machine-readable tag identifying the evidence
            strategy, e.g. ``"lexical_similarity"``,
            ``"definition_match"``, ``"synonym_match"``,
            ``"parent_term_overlap"``, ``"example_value_match"``.
        description: A human-readable explanation of what this evidence
            represents and why it supports (or contradicts) the mapping.
        score: An optional normalised confidence score in the range
            ``[0.0, 1.0]`` produced by the evidence strategy.  ``None``
            when the evidence is qualitative.
        source: An optional identifier for the agent or module that
            produced this piece of evidence (e.g.
            ``"LexicalScoringAgent"``, ``"DefinitionEmbeddingAgent"``).
    """

    evidence_type: str = Field(
        ...,
        description=(
            "Machine-readable tag for the evidence strategy, "
            "e.g. 'lexical_similarity', 'definition_match'."
        ),
    )
    description: str = Field(
        ...,
        description="Human-readable explanation of this evidence item.",
    )
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalised confidence score in [0.0, 1.0], or None if qualitative.",
    )
    source: str | None = Field(
        default=None,
        description="Agent or module that produced this evidence item.",
    )

    model_config = {"frozen": False, "extra": "forbid"}


class Provenance(BaseModel):
    """Provenance metadata for a :class:`MappingHypothesis`.

    Provenance records *who* created a hypothesis, *when*, *how*, and
    which pipeline run it belongs to.  This information is essential for
    audit trails, reproducibility, and debugging.

    Attributes:
        created_by: The name of the agent, module, or human that created
            this hypothesis, e.g. ``"LexicalMappingAgent"``,
            ``"human"``.
        created_at: ISO 8601 datetime string recording when the hypothesis
            was first created, e.g. ``"2025-03-15T14:22:00Z"``.
        method: A short identifier for the method or algorithm that
            produced the hypothesis, e.g. ``"lexical_similarity_v1"``,
            ``"embedding_cosine_v2"``.
        pipeline_run_id: An optional identifier tying this hypothesis to a
            specific pipeline execution (e.g. a UUID or a timestamp-based
            run ID).  ``None`` when run tracking is not enabled.
        extra: An open-ended dictionary for any additional provenance
            metadata (e.g. model version, configuration snapshot).
    """

    created_by: str = Field(
        ...,
        description="Name of the agent or 'human' that created the hypothesis.",
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 datetime string of creation time.",
    )
    method: str = Field(
        ...,
        description=(
            "Short identifier for the creation method, "
            "e.g. 'lexical_similarity_v1'."
        ),
    )
    pipeline_run_id: str | None = Field(
        default=None,
        description="Optional run ID tying this hypothesis to a pipeline execution.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional provenance metadata (model version, config, etc.).",
    )

    model_config = {"frozen": False, "extra": "forbid"}


# ---------------------------------------------------------------------------
# Core mapping hypothesis
# ---------------------------------------------------------------------------


class MappingHypothesis(BaseModel):
    """A proposed mapping between a source entity and an ontology term.

    This is the central data structure of the entire Ontology Mapping
    Co-Scientist system.  A hypothesis is created by a mapping agent,
    enriched with evidence by scoring agents, reviewed adversarially by a
    critic agent, and finally validated by a human reviewer before being
    exported as an authoritative mapping.

    Lifecycle overview::

        MappingAgent creates hypothesis
            -> ScoringAgents add Evidence
            -> ValidationAgent sets validation_status
            -> AdversarialAgent flags issues
            -> Human sets human_review_status
            -> ExportAgent serialises approved hypotheses

    Attributes:
        mapping_id: A globally unique identifier for this hypothesis within
            a pipeline run, e.g. ``"map-csv_animal_strain-mbo_0001234"``.
        source_entity: The source entity being mapped.
        target_entity: The candidate ontology term.
        predicate: The SKOS predicate describing the mapping relationship.
        confidence: Aggregate confidence score in the range ``[0.0, 1.0]``
            representing how strongly the pipeline believes this mapping
            is correct.
        evidence: Ordered list of evidence items that support the mapping.
            Agents should append to this list rather than replacing it.
        counter_evidence: Ordered list of evidence items that argue
            *against* the mapping.
        required_conditions: Human-readable conditions that must hold for
            the mapping to be valid, e.g.
            ``["values must be normalised to lowercase before comparison"]``.
        reviewer_notes: Free-text notes added by human reviewers during the
            review process.
        validation_status: Current state of automated validation.
        human_review_status: Current state of human review.
        warnings: Non-fatal warning messages attached by any pipeline stage.
        provenance: Provenance metadata for audit and reproducibility.
        rank: Optional integer rank of this hypothesis relative to other
            candidates for the same source entity (1 = best).  ``None``
            until a ranking agent has scored candidates.
    """

    mapping_id: str = Field(
        ...,
        description="Globally unique identifier for this hypothesis.",
    )
    source_entity: SourceEntity = Field(
        ...,
        description="The source entity being mapped.",
    )
    target_entity: OntologyTerm = Field(
        ...,
        description="The candidate ontology term.",
    )
    predicate: MappingPredicate = Field(
        ...,
        description="SKOS predicate describing the mapping relationship.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence score in [0.0, 1.0].",
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Supporting evidence items, in order of addition.",
    )
    counter_evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence items that argue against the mapping.",
    )
    required_conditions: list[str] = Field(
        default_factory=list,
        description=(
            "Conditions that must hold for the mapping to be valid, "
            "e.g. value normalisation requirements."
        ),
    )
    reviewer_notes: list[str] = Field(
        default_factory=list,
        description="Free-text notes added by human reviewers.",
    )
    validation_status: ValidationStatus = Field(
        default=ValidationStatus.PENDING,
        description="Current automated validation lifecycle state.",
    )
    human_review_status: HumanReviewStatus = Field(
        default=HumanReviewStatus.AWAITING_REVIEW,
        description="Current human review lifecycle state.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warning messages from any pipeline stage.",
    )
    provenance: Provenance = Field(
        ...,
        description="Provenance metadata for audit and reproducibility.",
    )
    rank: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional rank among candidate hypotheses for the same source "
            "entity (1 = best).  None until ranking has been performed."
        ),
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def summary(self) -> str:
        """Return a one-line human-readable summary of this hypothesis.

        The summary format is::

            <source_entity_id> --[<predicate>]--> <target_term_id> (conf=<confidence>)

        For example::

            csv:animal.strain --[skos:closeMatch]--> mbo:GeneticBackground (conf=0.72)

        Returns:
            A single-line string summarising the mapping hypothesis.
        """
        return (
            f"{self.source_entity.entity_id} "
            f"--[{self.predicate}]--> "
            f"{self.target_entity.term_id} "
            f"(conf={self.confidence:.2f})"
        )

    def __str__(self) -> str:
        """Delegate to :meth:`summary`."""
        return self.summary()
