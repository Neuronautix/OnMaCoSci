"""Validation agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`ValidationAgent`, which runs automated consistency
and quality checks on mapping hypotheses and sets their
:attr:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingHypothesis.validation_status`
accordingly.  Future versions will support SHACL and SPARQL validation.
"""

from __future__ import annotations

import logging

from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    MappingHypothesis,
    MappingPredicate,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

# Confidence tolerance used when checking NO_MAPPING hypotheses
_NO_MAPPING_CONFIDENCE_THRESHOLD = 0.1


class ValidationAgent:
    """Runs consistency and quality checks on mapping hypotheses.

    Future versions will support SHACL and SPARQL validation.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate_hypothesis(self, hypothesis: MappingHypothesis) -> MappingHypothesis:
        """Run all automated validation checks on a single hypothesis.

        Checks performed (in order):

        1. **Confidence bounds** — confidence must be in ``[0.0, 1.0]``.
           (Pydantic enforces this at construction; this check is an extra
           defensive guard.)  Failure → :attr:`~.ValidationStatus.FAILED`.
        2. **EXACT_MATCH completeness** — if predicate is ``EXACT_MATCH``,
           both the source and target must have non-empty labels and the
           target should have a definition.  Missing definition → warning.
        3. **NO_MAPPING confidence** — if predicate is ``NO_MAPPING``, the
           confidence must be at or below ``0.1``.  Higher confidence on a
           NO_MAPPING hypothesis is contradictory → ``FAILED``.
        4. **Evidence presence** — if the hypothesis has no evidence at all
           (and is not a NO_MAPPING), the status is set to ``WARNING``.
        5. If all checks pass, status is set to ``PASSED``.

        Args:
            hypothesis: The hypothesis to validate.

        Returns:
            The same hypothesis (mutated in place) with an updated
            :attr:`~.MappingHypothesis.validation_status` and any new
            entries appended to :attr:`~.MappingHypothesis.warnings`.
        """
        issues: list[str] = []
        fatal: bool = False

        # --- Check 1: confidence bounds ---
        if not (0.0 <= hypothesis.confidence <= 1.0):
            issues.append(
                f"Confidence {hypothesis.confidence:.4f} is outside valid range [0.0, 1.0]."
            )
            fatal = True

        # --- Check 2: EXACT_MATCH completeness ---
        if hypothesis.predicate == MappingPredicate.EXACT_MATCH:
            if not hypothesis.source_entity.label:
                issues.append(
                    "EXACT_MATCH hypothesis has a source entity with an empty label."
                )
                fatal = True
            if not hypothesis.target_entity.label:
                issues.append(
                    "EXACT_MATCH hypothesis has a target entity with an empty label."
                )
                fatal = True
            if not hypothesis.target_entity.definition:
                issues.append(
                    f"EXACT_MATCH target '{hypothesis.target_entity.label}' has no "
                    "formal definition — semantic equivalence cannot be fully verified."
                )
                # This is a warning, not a failure

        # --- Check 3: NO_MAPPING confidence ---
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            if hypothesis.confidence > _NO_MAPPING_CONFIDENCE_THRESHOLD:
                issues.append(
                    f"NO_MAPPING hypothesis has confidence {hypothesis.confidence:.4f} "
                    f"which exceeds the allowed maximum of {_NO_MAPPING_CONFIDENCE_THRESHOLD}. "
                    "This is contradictory — a NO_MAPPING should have confidence ≈ 0.0."
                )
                fatal = True

        # --- Check 4: evidence presence ---
        if (
            hypothesis.predicate != MappingPredicate.NO_MAPPING
            and not hypothesis.evidence
        ):
            issues.append(
                "Hypothesis has no supporting evidence items. "
                "At least one evidence item is expected for a non-NO_MAPPING hypothesis."
            )
            # Not fatal but worth flagging

        # Apply issues to the hypothesis
        for issue in issues:
            if issue not in hypothesis.warnings:
                hypothesis.warnings.append(issue)

        # Set validation status
        if fatal:
            hypothesis.validation_status = ValidationStatus.FAILED
            logger.debug(
                "Hypothesis %s FAILED validation: %s",
                hypothesis.mapping_id,
                "; ".join(issues),
            )
        elif issues:
            hypothesis.validation_status = ValidationStatus.WARNING
            logger.debug(
                "Hypothesis %s has validation WARNING: %s",
                hypothesis.mapping_id,
                "; ".join(issues),
            )
        else:
            hypothesis.validation_status = ValidationStatus.PASSED
            logger.debug("Hypothesis %s PASSED validation.", hypothesis.mapping_id)

        return hypothesis

    def validate_all(
        self, hypotheses: list[MappingHypothesis]
    ) -> list[MappingHypothesis]:
        """Validate all hypotheses in *hypotheses*.

        Calls :meth:`validate_hypothesis` for each hypothesis and returns the
        full list with updated validation statuses.

        Args:
            hypotheses: The list of mapping hypotheses to validate.

        Returns:
            The same list (mutated in place) with updated
            :attr:`~.MappingHypothesis.validation_status` values.
        """
        for hypothesis in hypotheses:
            self.validate_hypothesis(hypothesis)

        summary = self.generate_validation_summary(hypotheses)
        logger.info(
            "Validation complete: total=%d, passed=%d, warnings=%d, failed=%d.",
            summary["total"],
            summary["passed"],
            summary["warnings"],
            summary["failed"],
        )
        return hypotheses

    def generate_validation_summary(
        self, hypotheses: list[MappingHypothesis]
    ) -> dict:
        """Compute a statistical summary of validation results.

        Args:
            hypotheses: The list of (already validated) mapping hypotheses.

        Returns:
            A dict with the following keys:

            * ``total`` (*int*) — total number of hypotheses.
            * ``passed`` (*int*) — count with status ``PASSED``.
            * ``warnings`` (*int*) — count with status ``WARNING``.
            * ``failed`` (*int*) — count with status ``FAILED``.
            * ``no_mapping_count`` (*int*) — count with predicate ``NO_MAPPING``.
            * ``exact_match_count`` (*int*) — count with predicate ``EXACT_MATCH``.
            * ``high_confidence_count`` (*int*) — count with confidence ≥ 0.8.
        """
        total = len(hypotheses)
        passed = sum(
            1 for h in hypotheses if h.validation_status == ValidationStatus.PASSED
        )
        warnings = sum(
            1 for h in hypotheses if h.validation_status == ValidationStatus.WARNING
        )
        failed = sum(
            1 for h in hypotheses if h.validation_status == ValidationStatus.FAILED
        )
        no_mapping_count = sum(
            1 for h in hypotheses if h.predicate == MappingPredicate.NO_MAPPING
        )
        exact_match_count = sum(
            1 for h in hypotheses if h.predicate == MappingPredicate.EXACT_MATCH
        )
        high_confidence_count = sum(
            1 for h in hypotheses if h.confidence >= 0.8
        )

        return {
            "total": total,
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
            "no_mapping_count": no_mapping_count,
            "exact_match_count": exact_match_count,
            "high_confidence_count": high_confidence_count,
        }
