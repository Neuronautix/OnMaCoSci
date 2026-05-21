"""Candidate generator agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`CandidateGeneratorAgent`, which uses lexical
similarity scoring to propose initial :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingHypothesis`
candidates for each source entity.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    HumanReviewStatus,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
    ValidationStatus,
)
from ontology_mapping_co_scientist.scoring.evidence_scoring import (
    build_lexical_evidence,
    build_synonym_evidence,
    compute_aggregate_confidence,
)
from ontology_mapping_co_scientist.scoring.lexical_similarity import (
    compute_similarity,
    find_best_matches,
    label_to_predicate,
    normalize_label,
)

logger = logging.getLogger(__name__)

_AGENT_NAME = "CandidateGeneratorAgent"
_METHOD = "lexical_similarity_v1"


class CandidateGeneratorAgent:
    """Generates mapping hypotheses between source entities and ontology terms using lexical similarity."""

    def __init__(self, top_k: int = 5, min_confidence: float = 0.0) -> None:
        """Initialise the candidate generator.

        Args:
            top_k: Maximum number of candidate ontology terms to propose per
                source entity (default 5).
            min_confidence: Minimum aggregate confidence score required for a
                hypothesis to be included.  Candidates below this threshold are
                omitted; if *all* candidates fall below it a single
                ``NO_MAPPING`` hypothesis is created instead (default 0.0).
        """
        self.top_k = top_k
        self.min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        source_entities: list[SourceEntity],
        ontology_terms: list[OntologyTerm],
        pipeline_run_id: str | None = None,
    ) -> list[MappingHypothesis]:
        """Generate mapping hypothesis candidates for all source entities.

        For each source entity the method:

        1. Runs :func:`~ontology_mapping_co_scientist.scoring.lexical_similarity.find_best_matches`
           against the preferred labels of all ontology terms to obtain the
           top-k candidates.
        2. For each candidate builds lexical and (when applicable) synonym
           evidence objects.
        3. Determines a :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingPredicate`
           via :func:`~ontology_mapping_co_scientist.scoring.lexical_similarity.label_to_predicate`.
        4. Computes an aggregate confidence score via
           :func:`~ontology_mapping_co_scientist.scoring.evidence_scoring.compute_aggregate_confidence`.
        5. Packages everything into a
           :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingHypothesis`.

        If no candidates meet *min_confidence* a single ``NO_MAPPING``
        hypothesis is appended for that source entity.

        Args:
            source_entities: Source entities to map.
            ontology_terms: The complete pool of candidate ontology terms.
            pipeline_run_id: Optional identifier for the current pipeline run,
                included in :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.Provenance`.

        Returns:
            A flat list of all generated
            :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.MappingHypothesis`
            objects.
        """
        if not ontology_terms:
            logger.warning("No ontology terms provided — all hypotheses will be NO_MAPPING.")

        term_label_pairs = [(t.term_id, t.label) for t in ontology_terms]

        # Build fast lookup: normalised label -> OntologyTerm
        label_to_term: dict[str, OntologyTerm] = {}
        for term in ontology_terms:
            label_to_term[normalize_label(term.label)] = term

        # Build synonym lookup: normalised synonym -> list[OntologyTerm]
        synonym_to_terms: dict[str, list[OntologyTerm]] = {}
        for term in ontology_terms:
            for syn in term.synonyms:
                key = normalize_label(syn)
                synonym_to_terms.setdefault(key, []).append(term)

        all_hypotheses: list[MappingHypothesis] = []

        for entity in source_entities:
            logger.debug("Generating candidates for entity: %s", entity.entity_id)
            hypotheses = self._generate_for_entity(
                entity=entity,
                ontology_terms=ontology_terms,
                term_label_pairs=term_label_pairs,
                label_to_term=label_to_term,
                synonym_to_terms=synonym_to_terms,
                pipeline_run_id=pipeline_run_id,
            )
            all_hypotheses.extend(hypotheses)

        logger.info(
            "Generated %d hypotheses for %d source entities.",
            len(all_hypotheses),
            len(source_entities),
        )
        return all_hypotheses

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_for_entity(
        self,
        entity: SourceEntity,
        ontology_terms: list[OntologyTerm],
        term_label_pairs: list[tuple[str, str]],
        label_to_term: dict[str, OntologyTerm],
        synonym_to_terms: dict[str, list[OntologyTerm]],
        pipeline_run_id: str | None,
    ) -> list[MappingHypothesis]:
        """Generate hypotheses for a single source entity.

        Args:
            entity: The source entity to map.
            ontology_terms: Full list of available ontology terms.
            term_label_pairs: List of (term_id, label) pairs for find_best_matches.
            label_to_term: Normalised-label-to-term lookup dict.
            synonym_to_terms: Normalised-synonym-to-terms lookup dict.
            pipeline_run_id: Optional pipeline run identifier for provenance.

        Returns:
            A list of :class:`MappingHypothesis` objects for this entity.
        """
        now = datetime.now(tz=timezone.utc).isoformat()

        # Lexical matches on preferred labels
        label_matches = find_best_matches(entity.label, term_label_pairs, top_k=self.top_k)

        # Synonym matches — collect unique additional terms
        syn_matches: list[tuple[str, float, OntologyTerm]] = []
        norm_entity_label = normalize_label(entity.label)
        seen_from_syn: set[str] = set()
        for syn_key, terms_for_syn in synonym_to_terms.items():
            score = compute_similarity(norm_entity_label, syn_key)
            if score > 0:
                for term in terms_for_syn:
                    if term.term_id not in seen_from_syn:
                        seen_from_syn.add(term.term_id)
                        syn_matches.append((syn_key, score, term))
        syn_matches.sort(key=lambda x: x[1], reverse=True)

        # Merge into unified candidate list: (OntologyTerm, lex_score, syn_score)
        seen_term_ids: set[str] = set()
        candidates: list[tuple[OntologyTerm, float, float]] = []

        for _tid, matched_label, lex_score in label_matches:
            term = label_to_term.get(normalize_label(matched_label))
            if term is None:
                continue
            if term.term_id in seen_term_ids:
                continue
            seen_term_ids.add(term.term_id)
            best_syn_score = 0.0
            for _, s_score, s_term in syn_matches:
                if s_term.term_id == term.term_id:
                    best_syn_score = max(best_syn_score, s_score)
            candidates.append((term, lex_score, best_syn_score))

        # Add synonym-only candidates not covered by label matches
        for _, s_score, s_term in syn_matches:
            if s_term.term_id not in seen_term_ids and len(candidates) < self.top_k:
                seen_term_ids.add(s_term.term_id)
                candidates.append((s_term, 0.0, s_score))

        # Trim to top_k by best-of (lex, syn) score
        candidates = sorted(
            candidates, key=lambda x: max(x[1], x[2]), reverse=True
        )[: self.top_k]

        hypotheses: list[MappingHypothesis] = []
        accepted_count = 0

        for i, (term, lex_score, syn_score) in enumerate(candidates):
            evidence_list: list[Evidence] = []

            if lex_score > 0:
                lex_ev = build_lexical_evidence(
                    source_label=entity.label,
                    target_label=term.label,
                    score=lex_score,
                )
                evidence_list.append(lex_ev)

            if syn_score > 0:
                # Find the best matching synonym string for this term
                best_syn_label = ""
                best_syn_score_val = 0.0
                for _, s_score, s_term in syn_matches:
                    if s_term.term_id == term.term_id and s_score > best_syn_score_val:
                        best_syn_score_val = s_score
                        for syn in term.synonyms:
                            if (
                                abs(
                                    compute_similarity(
                                        normalize_label(entity.label),
                                        normalize_label(syn),
                                    )
                                    - s_score
                                )
                                < 1e-6
                            ):
                                best_syn_label = syn
                                break
                matched_synonym = (
                    best_syn_label
                    or (term.synonyms[0] if term.synonyms else term.label)
                )
                syn_ev = build_synonym_evidence(
                    source_label=entity.label,
                    matched_synonym=matched_synonym,
                    term_id=term.term_id,
                    score=syn_score,
                )
                evidence_list.append(syn_ev)

            confidence = compute_aggregate_confidence(evidence_list, [])
            best_score = max(lex_score, syn_score)
            predicate = label_to_predicate(best_score)

            if confidence < self.min_confidence:
                continue

            safe_entity = self._sanitize_id(entity.entity_id)
            safe_term = self._sanitize_id(term.term_id)
            mapping_id = f"map_{safe_entity}_{safe_term}_{i}"

            provenance = Provenance(
                created_by=_AGENT_NAME,
                method=_METHOD,
                pipeline_run_id=pipeline_run_id,
                created_at=now,
            )

            hypothesis = MappingHypothesis(
                mapping_id=mapping_id,
                source_entity=entity,
                target_entity=term,
                predicate=predicate,
                confidence=confidence,
                evidence=evidence_list,
                provenance=provenance,
                validation_status=ValidationStatus.PENDING,
                human_review_status=HumanReviewStatus.AWAITING_REVIEW,
            )
            hypotheses.append(hypothesis)
            accepted_count += 1

        # If no candidates met min_confidence threshold, emit a NO_MAPPING hypothesis
        if accepted_count == 0:
            logger.debug(
                "No candidates met min_confidence=%.3f for entity %s; creating NO_MAPPING.",
                self.min_confidence,
                entity.entity_id,
            )
            hypotheses.append(
                self._make_no_mapping_hypothesis(entity, pipeline_run_id, now)
            )

        return hypotheses

    def _make_no_mapping_hypothesis(
        self,
        entity: SourceEntity,
        pipeline_run_id: str | None,
        created_at: str,
    ) -> MappingHypothesis:
        """Build a NO_MAPPING placeholder hypothesis for *entity*.

        Args:
            entity: The source entity that could not be mapped.
            pipeline_run_id: Optional pipeline run identifier for provenance.
            created_at: ISO 8601 timestamp string for provenance.

        Returns:
            A :class:`MappingHypothesis` with predicate ``NO_MAPPING`` and
            confidence ``0.0``.
        """
        safe_entity = self._sanitize_id(entity.entity_id)
        mapping_id = f"map_{safe_entity}_NO_MAPPING_0"

        # Create a sentinel OntologyTerm to satisfy the non-optional field
        sentinel_term = OntologyTerm(
            term_id="custom:no_mapping",
            label="No Mapping",
            definition="Sentinel term indicating no suitable ontology term was found.",
            term_type="sentinel",
            ontology_id="custom",
        )

        provenance = Provenance(
            created_by=_AGENT_NAME,
            method=_METHOD,
            pipeline_run_id=pipeline_run_id,
            created_at=created_at,
        )

        return MappingHypothesis(
            mapping_id=mapping_id,
            source_entity=entity,
            target_entity=sentinel_term,
            predicate=MappingPredicate.NO_MAPPING,
            confidence=0.0,
            evidence=[],
            provenance=provenance,
            validation_status=ValidationStatus.PENDING,
            human_review_status=HumanReviewStatus.AWAITING_REVIEW,
        )

    def _sanitize_id(self, s: str) -> str:
        """Replace non-alphanumeric characters in *s* with underscores.

        Args:
            s: The raw identifier string to sanitise.

        Returns:
            A string safe to embed in a mapping ID.
        """
        return re.sub(r"[^A-Za-z0-9]", "_", s)
