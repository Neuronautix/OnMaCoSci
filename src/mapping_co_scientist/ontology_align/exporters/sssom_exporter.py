from __future__ import annotations
import csv
import io
from datetime import datetime
from pathlib import Path
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation
)

_RELATION_TO_SSSOM: dict[OntologyRelation, str] = {
    OntologyRelation.EXACT_MATCH: "skos:exactMatch",
    OntologyRelation.CLOSE_MATCH: "skos:closeMatch",
    OntologyRelation.BROAD_MATCH: "skos:broadMatch",
    OntologyRelation.NARROW_MATCH: "skos:narrowMatch",
    OntologyRelation.RELATED_MATCH: "skos:relatedMatch",
    OntologyRelation.SUBCLASS_OF: "rdfs:subClassOf",
    OntologyRelation.EQUIVALENT_CLASS: "owl:equivalentClass",
    OntologyRelation.EQUIVALENT_PROPERTY: "owl:equivalentProperty",
    OntologyRelation.REQUIRES_ONTOLOGY_EXTENSION: "custom:requiresOntologyExtension",
    OntologyRelation.NO_SUITABLE_MAPPING: "custom:noSuitableMapping",
    OntologyRelation.REQUIRES_HUMAN_DECISION: "custom:requiresHumanDecision",
}

SSSOM_COLUMNS = [
    "subject_id", "subject_label", "predicate_id", "object_id", "object_label",
    "mapping_justification", "confidence", "comment", "mapping_tool",
    "mapping_tool_version", "mapping_date", "reviewer_id",
]


def export_sssom(
    hypotheses: list[OntologyMappingHypothesis],
    output_path: Path,
    pipeline_run_id: str | None = None,
    curator_name: str = "mapping_co_scientist",
) -> None:
    """Export approved/reviewed ontology mapping hypotheses as SSSOM-compliant TSV."""
    now = datetime.utcnow().strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# mapping_set_id: https://example.org/mappings/{pipeline_run_id or 'run'}")
    lines.append(f"# mapping_set_version: {now}")
    lines.append(f"# creator_id: {curator_name}")
    lines.append(f"# license: https://creativecommons.org/licenses/by/4.0/")
    lines.append(f"# mapping_date: {now}")
    lines.append("")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SSSOM_COLUMNS, delimiter="\t", extrasaction="ignore")
    writer.writeheader()

    for h in hypotheses:
        predicate = _RELATION_TO_SSSOM.get(h.ontology_relation, str(h.ontology_relation))
        comments = []
        for w in h.semantic_warnings:
            comments.append(f"[{w.warning_type}] {w.description}")
        for w in h.warnings:
            comments.append(w)

        writer.writerow({
            "subject_id": h.source_concept.entity_id,
            "subject_label": h.source_concept.label,
            "predicate_id": predicate,
            "object_id": h.target_ontology_entity.term_id,
            "object_label": h.target_ontology_entity.label,
            "mapping_justification": h.provenance.method,
            "confidence": f"{h.confidence:.4f}",
            "comment": " | ".join(comments),
            "mapping_tool": h.provenance.created_by,
            "mapping_tool_version": "0.2.0",
            "mapping_date": now,
            "reviewer_id": "",
        })

    full_content = "\n".join(lines) + buf.getvalue()
    output_path.write_text(full_content, encoding="utf-8")
