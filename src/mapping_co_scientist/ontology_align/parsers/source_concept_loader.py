from __future__ import annotations
import csv
from pathlib import Path
from mapping_co_scientist.shared.models.source_entity import SourceEntity


def load_source_concepts_from_csv(path: Path, max_examples: int = 5) -> list[SourceEntity]:
    """Load source field concepts from a CSV file.
    Each column header becomes a SourceEntity. Example values are collected from rows.
    """
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return []
        headers = list(rows[0].keys())

    entities = []
    for header in headers:
        examples = []
        for row in rows[:max_examples]:
            val = row.get(header, "").strip()
            if val and val not in examples:
                examples.append(val)

        entity = SourceEntity(
            entity_id=f"csv:{header}",
            label=header,
            datatype=_infer_datatype(examples),
            examples=examples,
            source_file=str(path),
            source_type="csv",
        )
        entities.append(entity)
    return entities


def _infer_datatype(examples: list[str]) -> str:
    if not examples:
        return "string"
    try:
        [int(v) for v in examples if v]
        return "integer"
    except ValueError:
        pass
    try:
        [float(v) for v in examples if v]
        return "number"
    except ValueError:
        pass
    return "string"
