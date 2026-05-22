from __future__ import annotations
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.shared.models.evidence import Evidence, Provenance
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation, SemanticWarning
)

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz as _fuzz
    def _sim(a: str, b: str) -> float:
        return _fuzz.WRatio(a, b) / 100.0
except ImportError:
    import difflib
    def _sim(a: str, b: str) -> float:  # type: ignore[misc]
        return difflib.SequenceMatcher(None, a, b).ratio()


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFC", s).strip().lower()
    s = s.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def _score_to_relation(score: float) -> OntologyRelation:
    if score >= 0.90:
        return OntologyRelation.CLOSE_MATCH
    if score >= 0.75:
        return OntologyRelation.CLOSE_MATCH
    if score >= 0.55:
        return OntologyRelation.BROAD_MATCH
    if score >= 0.40:
        return OntologyRelation.RELATED_MATCH
    return OntologyRelation.NO_SUITABLE_MAPPING


class SemanticCandidateGeneratorAgent(BaseAgent):
    """Generates OntologyMappingHypothesis candidates using lexical similarity.

    Note: lexical similarity alone cannot establish exactMatch. The agent
    uses closeMatch at most for high-scoring pairs and flags them for review.
    LLM-backed semantic comparison is a future extension point.
    """

    def __init__(self, top_k: int = 3, pipeline_run_id: str | None = None):
        self.top_k = top_k
        self.pipeline_run_id = pipeline_run_id

    @property
    def agent_name(self) -> str:
        return "SemanticCandidateGenerator"

    def generate(
        self,
        source_entities: list[SourceEntity],
        ontology_terms: list[OntologyTerm],
    ) -> list[OntologyMappingHypothesis]:
        index = self._build_index(ontology_terms)
        term_map = {t.term_id: t for t in ontology_terms}

        all_hyps: list[OntologyMappingHypothesis] = []
        for entity in source_entities:
            hyps = self._generate_for_entity(entity, index, term_map)
            all_hyps.extend(hyps)

        self.log_step(f"Generated {len(all_hyps)} hypotheses for {len(source_entities)} entities")
        return all_hyps

    def _build_index(self, terms: list[OntologyTerm]) -> list[tuple[str, str, str]]:
        """(term_id, label, normalized_label) triples including synonyms."""
        idx = []
        for t in terms:
            idx.append((t.term_id, t.label, _normalize(t.label)))
            for syn in t.synonyms:
                idx.append((t.term_id, syn, _normalize(syn)))
        return idx

    def _generate_for_entity(
        self,
        entity: SourceEntity,
        index: list[tuple[str, str, str]],
        term_map: dict[str, OntologyTerm],
    ) -> list[OntologyMappingHypothesis]:
        norm_label = _normalize(entity.label)

        scored: list[tuple[str, str, float]] = []
        for term_id, label, norm in index:
            score = _sim(norm_label, norm)
            scored.append((term_id, label, score))

        best: dict[str, tuple[str, float]] = {}
        for term_id, label, score in scored:
            if term_id not in best or score > best[term_id][1]:
                best[term_id] = (label, score)

        top = sorted(best.items(), key=lambda x: x[1][1], reverse=True)[: self.top_k]

        hypotheses = []
        for i, (term_id, (matched_label, score)) in enumerate(top):
            if score < 0.30:
                continue
            term = term_map[term_id]
            relation = _score_to_relation(score)
            hyp = self._build_hypothesis(entity, term, relation, score, matched_label, rank=i + 1)
            hypotheses.append(hyp)

        return hypotheses

    def _build_hypothesis(
        self,
        entity: SourceEntity,
        term: OntologyTerm,
        relation: OntologyRelation,
        score: float,
        matched_label: str,
        rank: int,
    ) -> OntologyMappingHypothesis:
        mapping_id = f"oa-{entity.entity_id}-{term.term_id}".replace(":", "_").replace("/", "_")

        evidence = [Evidence(
            evidence_type="lexical_similarity",
            description=f"Label '{entity.label}' matched '{matched_label}' with score {score:.3f}",
            score=score,
            source="SemanticCandidateGenerator",
        )]

        counter_evidence = []
        warnings_list = []
        semantic_warnings = []

        if score >= 0.90:
            semantic_warnings.append(SemanticWarning(
                warning_type="lexical_only_high_score",
                description=(
                    f"Score {score:.2f} is high enough for exactMatch by lexical metrics, "
                    "but lexical similarity alone is insufficient to establish skos:exactMatch. "
                    "Semantic review required before upgrading to exactMatch."
                ),
                severity="warning",
            ))
            counter_evidence.append(Evidence(
                evidence_type="auto_exactmatch_prevention",
                description="Lexical score ≥0.90 but exactMatch requires semantic validation",
                source="SemanticCandidateGenerator",
            ))

        if entity.label.lower() == "strain" and "geneticbackground" in term.term_id.lower().replace("_", "").replace("-", ""):
            semantic_warnings.append(SemanticWarning(
                warning_type="scope_mismatch",
                description=(
                    "'strain' is typically narrower than 'GeneticBackground'. "
                    "GeneticBackground includes genotype, strain, and breeding history. "
                    "Consider skos:narrowMatch instead of closeMatch."
                ),
                severity="warning",
            ))
            if relation == OntologyRelation.CLOSE_MATCH:
                relation = OntologyRelation.NARROW_MATCH

        source_entity_type = self._infer_source_type(entity)

        return OntologyMappingHypothesis(
            mapping_id=mapping_id,
            source_concept=entity,
            target_ontology_entity=term,
            ontology_relation=relation,
            confidence=score,
            evidence=evidence,
            counter_evidence=counter_evidence,
            semantic_warnings=semantic_warnings,
            warnings=warnings_list,
            source_entity_type=source_entity_type,
            target_entity_type=term.term_type,
            semantic_scope_analysis=f"Lexical similarity: {score:.3f}. Requires semantic validation.",
            hierarchy_compatibility="unknown",
            domain_range_compatibility="unknown",
            rank=rank,
            provenance=Provenance(
                created_by="SemanticCandidateGenerator",
                created_at=datetime.utcnow().isoformat(),
                method="lexical_similarity_v1",
                pipeline_run_id=self.pipeline_run_id,
            ),
        )

    def _infer_source_type(self, entity: SourceEntity) -> str:
        label_lower = entity.label.lower()
        if any(w in label_lower for w in ["id", "identifier", "code", "key"]):
            return "identifier"
        if any(w in label_lower for w in ["weight", "count", "index", "score", "level", "value"]):
            return "measurement"
        if any(w in label_lower for w in ["date", "time", "day", "week"]):
            return "event"
        if any(w in label_lower for w in ["strain", "sex", "genotype", "species"]):
            return "attribute"
        return "field"
