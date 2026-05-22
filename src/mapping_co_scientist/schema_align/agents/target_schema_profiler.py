from __future__ import annotations
import logging
from pathlib import Path
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.parsers.json_schema_loader import load_json_schema
from mapping_co_scientist.schema_align.parsers.openapi_loader import load_openapi_schema

logger = logging.getLogger(__name__)


class TargetSchemaProfilerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "TargetSchemaProfiler"

    def profile(self, target_path: Path) -> list[SchemaEntity]:
        self.log_step(f"Profiling target schema: {target_path}")
        suffix = target_path.suffix.lower()
        if suffix == ".json":
            # Try JSON Schema first
            import json
            data = json.loads(target_path.read_text(encoding="utf-8"))
            if "openapi" in data or "swagger" in data:
                entities = load_openapi_schema(target_path)
            else:
                entities = load_json_schema(target_path)
        else:
            raise ValueError(f"Unsupported target format: {suffix}")
        self.log_step(f"Extracted {len(entities)} target fields")
        return entities
