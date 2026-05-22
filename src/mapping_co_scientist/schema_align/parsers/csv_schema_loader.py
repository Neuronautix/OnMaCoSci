"""Load a CSV file schema into SchemaEntity objects.

For schema alignment, we treat each CSV column as a SchemaEntity.
We collect example values and infer datatypes.
"""
from __future__ import annotations
import csv
import re
from pathlib import Path
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity

_UNIT_PATTERN = re.compile(r"[_\s]([a-zA-Z]+)$")
_KNOWN_UNITS = {"g", "kg", "mg", "ml", "dl", "l", "mm", "cm", "m", "hz", "rpm", "pct", "percent"}


def load_csv_schema(path: Path, max_examples: int = 5) -> list[SchemaEntity]:
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
            v = row.get(header, "").strip()
            if v and v not in examples:
                examples.append(v)

        dt = _infer_datatype(examples)
        unit = _infer_unit(header)

        entity = SchemaEntity(
            entity_id=f"csv:{header}",
            path=header,
            label=header.replace("_", " "),
            datatype=dt,
            unit=unit,
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


def _infer_unit(header: str) -> str | None:
    m = _UNIT_PATTERN.search(header)
    if m and m.group(1).lower() in _KNOWN_UNITS:
        return m.group(1).lower()
    return None
