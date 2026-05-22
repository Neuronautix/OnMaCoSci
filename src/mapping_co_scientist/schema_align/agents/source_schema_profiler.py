from __future__ import annotations
import logging
from pathlib import Path
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.parsers.csv_schema_loader import load_csv_schema

logger = logging.getLogger(__name__)


class SourceSchemaProfilerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "SourceSchemaProfiler"

    def profile(self, source_path: Path) -> list[SchemaEntity]:
        self.log_step(f"Profiling source schema: {source_path}")
        suffix = source_path.suffix.lower()
        if suffix == ".csv":
            entities = load_csv_schema(source_path)
        else:
            raise ValueError(f"Unsupported source format: {suffix}")
        self.log_step(f"Extracted {len(entities)} source fields")
        return entities
