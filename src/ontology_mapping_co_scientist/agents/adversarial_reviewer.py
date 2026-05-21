"""Adversarial reviewer agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`AdversarialReviewerAgent`, which inspects mapping
hypotheses and raises structured :class:`~ontology_mapping_co_scientist.models.review.AdversarialFlag`
objects for any identified weaknesses, ambiguities, or quality concerns.
"""

from __future__ import annotations

import logging
import re

from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
    MappingPredicate,
)
from ontology_mapping_co_scientist.models.review import (
    AdversarialFlag,
    AdversarialReviewResult,
)
from ontology_mapping_co_scientist.scoring.datatype_validator import build_datatype_flag
from ontology_mapping_co_scientist.scoring.lexical_similarity import normalize_label
from ontology_mapping_co_scientist.scoring.unit_extractor import build_unit_mismatch_flag

logger = logging.getLogger(__name__)

# Units-related keywords used to detect possible unit ambiguity
_UNIT_PATTERN = re.compile(
    r"\b(g|kg|mg|ml|dl|mmol|umol|nmol|cm|mm|m|km|"
    r"mg/dl|mg/l|mmol/l|umol/l|ng/ml|ug/ml|"
    r"celsius|fahrenheit|kelvin|hz|khz|mhz|"
    r"percent|%|bpm|rpm|pa|kpa|mpa|bar|psi|"
    r"seconds|minutes|hours|days|weeks|months|years)\b",
    re.IGNORECASE,
)

# Identifier-related keywords
_IDENTIFIER_PATTERN = re.compile(
    r"\b(id|identifier|code|key|uuid|guid|ref|reference|num|number)\b",
    re.IGNORECASE,
)

# Measurement class types in ontologies
_MEASUREMENT_TERM_TYPES = {"class", "property", "annotation_property"}


class AdversarialReviewerAgent:
    """Reviews mapping hypotheses to identify potential problems, ambiguities, and weaknesses."""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def review_hypothesis(self, hypothesis: MappingHypothesis) -> AdversarialReviewResult:
        """Run all adversarial checks against a single mapping hypothesis.

        Executes each private ``_check_*`` method in sequence and collects
        any :class:`~ontology_mapping_co_scientist.models.review.AdversarialFlag`
        objects returned.  The :attr:`~.AdversarialReviewResult.overall_severity`
        is set to the highest severity found, and a ``recommendation`` is
        derived accordingly.

        Args:
            hypothesis: The mapping hypothesis to review.

        Returns:
            An :class:`~ontology_mapping_co_scientist.models.review.AdversarialReviewResult`
            summarising all findings.
        """
        flags: list[AdversarialFlag] = []

        for checker in (
            self._check_weak_similarity,
            self._check_exactmatch,
            self._check_broad_narrow_ambiguity,
            self._check_datatype_mismatch,
            self._check_datatype_compatibility,
            self._check_missing_examples,
            self._check_unit_ambiguity,
            self._check_identifier_confusion,
            self._check_overly_broad_match,
            self._check_no_definition,
        ):
            result = checker(hypothesis)
            if result is not None:
                flags.append(result)

        # Unit-mismatch check via unit_extractor (structural, not keyword-based)
        if hypothesis.predicate != MappingPredicate.NO_MAPPING:
            unit_flag = build_unit_mismatch_flag(
                hypothesis.source_entity, hypothesis.target_entity
            )
            if unit_flag is not None:
                flags.append(unit_flag)

        overall_severity = _compute_overall_severity(flags)
        recommendation = _derive_recommendation(overall_severity)

        logger.debug(
            "Reviewed hypothesis %s: %d flags, severity=%s, recommendation=%s",
            hypothesis.mapping_id,
            len(flags),
            overall_severity,
            recommendation,
        )

        return AdversarialReviewResult(
            mapping_id=hypothesis.mapping_id,
            flags=flags,
            overall_severity=overall_severity,
            recommendation=recommendation,
        )

    def review_all(
        self, hypotheses: list[MappingHypothesis]
    ) -> list[AdversarialReviewResult]:
        """Review all hypotheses and return one result per hypothesis.

        Args:
            hypotheses: The full list of mapping hypotheses to review.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.review.AdversarialReviewResult`
            objects in the same order as *hypotheses*.
        """
        results = [self.review_hypothesis(h) for h in hypotheses]
        high_count = sum(1 for r in results if r.overall_severity == "high")
        logger.info(
            "Adversarial review complete: %d hypotheses reviewed, %d with high severity.",
            len(hypotheses),
            high_count,
        )
        return results

    def apply_flags_to_hypotheses(
        self,
        hypotheses: list[MappingHypothesis],
        results: list[AdversarialReviewResult],
    ) -> list[MappingHypothesis]:
        """Merge adversarial flags back into the corresponding hypotheses.

        For each :class:`~ontology_mapping_co_scientist.models.review.AdversarialReviewResult`
        in *results*:

        * High-severity flags are appended as counter-evidence items to the
          matched hypothesis.
        * All flag descriptions are appended to the hypothesis ``warnings``
          list.

        Hypotheses without a matching result are left unchanged.

        Args:
            hypotheses: The original list of mapping hypotheses.
            results: The adversarial review results (one per hypothesis).

        Returns:
            The same list of hypotheses (mutated in place) with counter-evidence
            and warnings applied.
        """
        result_index: dict[str, AdversarialReviewResult] = {
            r.mapping_id: r for r in results
        }

        for hypothesis in hypotheses:
            adv_result = result_index.get(hypothesis.mapping_id)
            if adv_result is None:
                continue

            for flag in adv_result.flags:
                # Add all flags as warnings
                warning_msg = f"[{flag.severity.upper()}] {flag.flag_type}: {flag.description}"
                if warning_msg not in hypothesis.warnings:
                    hypothesis.warnings.append(warning_msg)

                # High-severity flags are also recorded as counter-evidence
                if flag.severity == "high":
                    counter_ev = Evidence(
                        evidence_type=f"adversarial_{flag.flag_type}",
                        description=flag.description,
                        score=None,
                        source="AdversarialReviewerAgent",
                    )
                    hypothesis.counter_evidence.append(counter_ev)

        return hypotheses

    # ------------------------------------------------------------------
    # Private flag checkers
    # ------------------------------------------------------------------

    def _check_weak_similarity(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when aggregate confidence is below 0.5.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        if hypothesis.confidence < 0.5:
            return AdversarialFlag(
                flag_type="weak_lexical_similarity",
                description=(
                    f"Confidence is {hypothesis.confidence:.3f}, which is below the "
                    "recommended threshold of 0.5. The lexical similarity between "
                    f"'{hypothesis.source_entity.label}' and "
                    f"'{hypothesis.target_entity.label}' may be insufficient."
                ),
                severity="medium",
            )
        return None

    def _check_exactmatch(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when predicate is EXACT_MATCH but confidence is below 0.85.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if (
            hypothesis.predicate == MappingPredicate.EXACT_MATCH
            and hypothesis.confidence < 0.85
        ):
            return AdversarialFlag(
                flag_type="strong_exactmatch_claim",
                description=(
                    f"Predicate is EXACT_MATCH but confidence is only "
                    f"{hypothesis.confidence:.3f} (threshold: 0.85). "
                    "An exact match claim requires high confidence to be credible."
                ),
                severity="high",
            )
        return None

    def _check_broad_narrow_ambiguity(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when predicate is BROAD_MATCH or NARROW_MATCH.

        These directional predicates are difficult to determine automatically
        and should always be reviewed by a human expert.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate in (
            MappingPredicate.BROAD_MATCH,
            MappingPredicate.NARROW_MATCH,
        ):
            direction = (
                "broader" if hypothesis.predicate == MappingPredicate.BROAD_MATCH
                else "narrower"
            )
            return AdversarialFlag(
                flag_type="broad_narrow_ambiguity",
                description=(
                    f"Predicate is {hypothesis.predicate.value}, claiming the ontology "
                    f"term is semantically {direction} than the source entity. This "
                    "directional relationship cannot be reliably determined by lexical "
                    "methods alone — human expert review is strongly recommended."
                ),
                severity="medium",
            )
        return None

    def _check_datatype_mismatch(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when source datatype is 'number' but target term_type is 'class'.

        A numeric source entity is unlikely to map cleanly to an ontology class
        (which typically represents a category, not a measurement value).

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        source_dt = (hypothesis.source_entity.datatype or "").lower()
        target_type = (hypothesis.target_entity.term_type or "").lower()
        if source_dt == "number" and target_type == "class":
            return AdversarialFlag(
                flag_type="datatype_mismatch",
                description=(
                    f"Source entity '{hypothesis.source_entity.label}' has datatype "
                    f"'number', but target term '{hypothesis.target_entity.label}' is "
                    "an ontology 'class'. Numeric fields typically map to data "
                    "properties or annotation properties, not classes."
                ),
                severity="medium",
            )
        return None

    def _check_datatype_compatibility(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Check datatype compatibility using the datatype_validator module.

        Delegates to :func:`~ontology_mapping_co_scientist.scoring.datatype_validator.build_datatype_flag`
        which validates source datatype against target term_type and rdfs:range.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        return build_datatype_flag(hypothesis.source_entity, hypothesis.target_entity)

    def _check_missing_examples(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when the source entity has no example values.

        Without examples, there is limited evidence to validate the mapping
        beyond label similarity.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if not hypothesis.source_entity.examples:
            return AdversarialFlag(
                flag_type="missing_examples",
                description=(
                    f"Source entity '{hypothesis.source_entity.label}' has no example "
                    "values. Examples help disambiguate mappings when labels are "
                    "ambiguous; their absence reduces mapping confidence."
                ),
                severity="low",
            )
        return None

    def _check_unit_ambiguity(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when the source mentions units but the target definition does not.

        If the source label or description contains unit keywords (e.g. 'kg',
        'mg/dL') but the target term has no matching unit context, the
        mapping may be semantically incomplete.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None

        source_text = " ".join(
            filter(
                None,
                [hypothesis.source_entity.label, hypothesis.source_entity.description],
            )
        )
        if not _UNIT_PATTERN.search(source_text):
            return None

        target_text = " ".join(
            filter(
                None,
                [
                    hypothesis.target_entity.label,
                    hypothesis.target_entity.definition,
                    *hypothesis.target_entity.synonyms,
                ],
            )
        )
        if not _UNIT_PATTERN.search(target_text):
            return AdversarialFlag(
                flag_type="possible_unit_ambiguity",
                description=(
                    f"Source entity '{hypothesis.source_entity.label}' appears to "
                    "reference units (e.g. g, kg, mg/dL), but the target term "
                    f"'{hypothesis.target_entity.label}' does not mention units in "
                    "its label, definition, or synonyms. The mapping may miss "
                    "unit-specific semantics."
                ),
                severity="medium",
            )
        return None

    def _check_identifier_confusion(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when source label suggests an identifier but target is a measurement class.

        Source entities named with identifier-like terms (e.g. 'animal_id',
        'sample_code') should not normally map to measurement or phenotype classes.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        if not _IDENTIFIER_PATTERN.search(hypothesis.source_entity.label):
            return None

        target_type = (hypothesis.target_entity.term_type or "").lower()
        if target_type in _MEASUREMENT_TERM_TYPES:
            return AdversarialFlag(
                flag_type="possible_identifier_confusion",
                description=(
                    f"Source entity '{hypothesis.source_entity.label}' appears to be "
                    f"an identifier field, but the proposed target "
                    f"'{hypothesis.target_entity.label}' (term_type={target_type!r}) "
                    "is likely a measurement or concept class. Identifier fields "
                    "rarely require ontology class mappings."
                ),
                severity="medium",
            )
        return None

    def _check_overly_broad_match(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when source and target normalised labels differ greatly in length.

        A length ratio greater than 3 between normalised labels suggests that
        one concept is a much broader expression of the other.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        norm_source = normalize_label(hypothesis.source_entity.label)
        norm_target = normalize_label(hypothesis.target_entity.label)

        len_source = max(len(norm_source), 1)
        len_target = max(len(norm_target), 1)
        ratio = max(len_source, len_target) / min(len_source, len_target)

        if ratio > 3.0:
            longer = (
                "source" if len_source > len_target else "target"
            )
            return AdversarialFlag(
                flag_type="overly_broad_match",
                description=(
                    f"Normalised label length ratio between source "
                    f"'{hypothesis.source_entity.label}' (len={len_source}) and "
                    f"target '{hypothesis.target_entity.label}' (len={len_target}) "
                    f"is {ratio:.1f}x — the {longer} label is much longer, "
                    "suggesting the mapping may be too broad or too narrow."
                ),
                severity="low",
            )
        return None

    def _check_no_definition(
        self, hypothesis: MappingHypothesis
    ) -> AdversarialFlag | None:
        """Flag when the target ontology term has no formal definition.

        Without a definition it is impossible to fully verify semantic
        equivalence between source and target.

        Args:
            hypothesis: The hypothesis to inspect.

        Returns:
            An :class:`AdversarialFlag` or ``None``.
        """
        if hypothesis.predicate == MappingPredicate.NO_MAPPING:
            return None
        if not hypothesis.target_entity.definition:
            return AdversarialFlag(
                flag_type="no_definition",
                description=(
                    f"Target term '{hypothesis.target_entity.label}' "
                    f"({hypothesis.target_entity.term_id}) has no formal definition. "
                    "Without a definition it is difficult to verify semantic equivalence "
                    "and the mapping cannot be fully validated."
                ),
                severity="low",
            )
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _compute_overall_severity(
    flags: list[AdversarialFlag],
) -> str:
    """Compute the highest severity level across all flags.

    Args:
        flags: List of adversarial flags to inspect.

    Returns:
        One of ``"clean"``, ``"low"``, ``"medium"``, ``"high"``.
    """
    if not flags:
        return "clean"
    severity_rank = {"low": 1, "medium": 2, "high": 3}
    highest = max(flags, key=lambda f: severity_rank.get(f.severity, 0))
    return highest.severity


def _derive_recommendation(overall_severity: str) -> str:
    """Derive a recommendation string from the overall severity level.

    Args:
        overall_severity: One of ``"clean"``, ``"low"``, ``"medium"``, ``"high"``.

    Returns:
        One of ``"proceed"``, ``"review"``, ``"reject"``.
    """
    if overall_severity == "clean" or overall_severity == "low":
        return "proceed"
    if overall_severity == "medium":
        return "review"
    return "reject"
