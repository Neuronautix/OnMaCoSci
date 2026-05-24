"""Export transformation rules as a JSON specification."""
from __future__ import annotations
import json
from pathlib import Path
from mapping_co_scientist.schema_align.models.transformation_rule import TransformationRule


def export_transformation_rules(rules: list[TransformationRule], output_path: Path) -> None:
    data = [r.model_dump(mode="json") for r in rules]
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
