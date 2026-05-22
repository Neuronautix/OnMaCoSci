"""JSON-LD ontology loader. Stub implementation."""
from __future__ import annotations
from pathlib import Path
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm


def load_jsonld_ontology(path: Path) -> list[OntologyTerm]:
    """Load ontology terms from a JSON-LD file. Stub implementation."""
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    import warnings
    warnings.warn(f"JSON-LD loader is a stub. Cannot parse {path}.", UserWarning, stacklevel=2)
    return []
