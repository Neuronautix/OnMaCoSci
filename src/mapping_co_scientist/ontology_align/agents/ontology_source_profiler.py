from __future__ import annotations
import logging
from pathlib import Path
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.source_entity import SourceEntity
from mapping_co_scientist.ontology_align.parsers.source_concept_loader import load_source_concepts_from_csv

logger = logging.getLogger(__name__)


class OntologySourceProfilerAgent(BaseAgent):
    """Loads and profiles source concepts for ontology alignment."""

    @property
    def agent_name(self) -> str:
        return "OntologySourceProfiler"

    def profile(self, source_path: Path) -> list[SourceEntity]:
        self.log_step(f"Profiling source: {source_path}")
        suffix = source_path.suffix.lower()
        if suffix == ".csv":
            entities = load_source_concepts_from_csv(source_path)
        else:
            raise ValueError(f"Unsupported source format: {suffix}")
        self.log_step(f"Extracted {len(entities)} source concepts")
        return entities
