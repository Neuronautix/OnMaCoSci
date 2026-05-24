from __future__ import annotations
import yaml
from pathlib import Path
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm


def load_ontology_profile(path: Path) -> list[OntologyTerm]:
    """Load an ontology profile from YAML or JSON."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        import json
        data = json.loads(text)

    terms = []
    raw_terms = data.get("terms", data) if isinstance(data, dict) else data
    if isinstance(raw_terms, dict):
        raw_terms = list(raw_terms.values())

    for raw in raw_terms:
        if not isinstance(raw, dict):
            continue
        term = OntologyTerm(
            term_id=raw.get("term_id", raw.get("id", "")),
            label=raw.get("label", ""),
            definition=raw.get("definition"),
            synonyms=raw.get("synonyms", []),
            parent_terms=raw.get("parent_terms", []),
            term_type=raw.get("term_type", "class"),
            ontology_id=raw.get("ontology_id", data.get("ontology_id", "unknown") if isinstance(data, dict) else "unknown"),
            ontology_source=str(path),
        )
        terms.append(term)
    return terms
