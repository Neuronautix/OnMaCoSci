from __future__ import annotations
import logging
from pathlib import Path
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.ontology_align.models.ontology_entity import OntologyTerm
from mapping_co_scientist.ontology_align.parsers.ontology_loader import load_ontology_profile

logger = logging.getLogger(__name__)


class OntologyTargetProfilerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "OntologyTargetProfiler"

    def profile(self, ontology_path: Path) -> list[OntologyTerm]:
        self.log_step(f"Loading ontology: {ontology_path}")
        terms = load_ontology_profile(ontology_path)
        self.log_step(f"Loaded {len(terms)} ontology terms")
        return terms

    def build_label_index(self, terms: list[OntologyTerm]) -> list[tuple[str, str]]:
        """Return list of (term_id, label) pairs including synonyms."""
        index = []
        for term in terms:
            index.append((term.term_id, term.label))
            for syn in term.synonyms:
                index.append((term.term_id, syn))
        return index
