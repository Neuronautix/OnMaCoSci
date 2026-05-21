"""CSV loader for the Ontology Mapping Co-Scientist system.

Reads a CSV file and infers a list of SourceEntity objects, one per column,
by examining the column header and sample values.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ontology_mapping_co_scientist.models import SourceEntity


def _infer_datatype(values: list[str]) -> str:
    """Infer a simple datatype string from a list of non-empty cell values.

    Returns one of: "number", "boolean", or "string".

    Args:
        values: A list of non-empty string values sampled from one CSV column.

    Returns:
        A string representing the inferred datatype.
    """
    if not values:
        return "string"

    boolean_tokens = {"true", "false", "yes", "no", "1", "0", "t", "f", "y", "n"}

    def _is_numeric(v: str) -> bool:
        try:
            float(v)
            return True
        except ValueError:
            return False

    def _is_boolean(v: str) -> bool:
        return v.strip().lower() in boolean_tokens

    if all(_is_numeric(v) for v in values):
        return "number"
    if all(_is_boolean(v) for v in values):
        return "boolean"
    return "string"


def load_csv_entities(filepath: str | Path) -> list[SourceEntity]:
    """Load a CSV file and return one :class:`SourceEntity` per column.

    The function reads the CSV with :class:`csv.DictReader` (first row treated
    as headers).  For every column it collects up to three non-empty sample
    values, infers a datatype, and constructs a :class:`SourceEntity`.

    Special handling:
    * A column named ``description`` is **not** turned into its own entity;
      instead, its value for the first data row is used as the ``description``
      field of all other entities produced from that file.
    * Missing / empty cells are silently skipped when collecting examples.

    Args:
        filepath: Path to the CSV file (``str`` or :class:`pathlib.Path`).

    Returns:
        A list of :class:`SourceEntity` objects, one per non-description column.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        ValueError: If the CSV file has no header row or no data rows.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    stem = filepath.stem
    source_file = str(filepath)

    with filepath.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no headers: {filepath}")

        fieldnames: list[str] = list(reader.fieldnames)
        rows: list[dict[str, str]] = list(reader)

    if not rows:
        raise ValueError(f"CSV file has no data rows: {filepath}")

    # Collect per-column values (strip whitespace, drop empty strings)
    column_values: dict[str, list[str]] = {col: [] for col in fieldnames}
    for row in rows:
        for col in fieldnames:
            raw = row.get(col, "") or ""
            stripped = raw.strip()
            if stripped:
                column_values[col].append(stripped)

    # Check for a "description" column – use its first value as a file-level hint
    description_col_key: str | None = None
    for col in fieldnames:
        if col.strip().lower() == "description":
            description_col_key = col
            break

    file_description: str | None = None
    if description_col_key is not None:
        vals = column_values.get(description_col_key, [])
        file_description = vals[0] if vals else None

    entities: list[SourceEntity] = []

    for col in fieldnames:
        if col == description_col_key:
            # Don't emit the description column itself as a SourceEntity
            continue

        col_values = column_values.get(col, [])
        examples = col_values[:3]
        datatype = _infer_datatype(col_values)

        safe_col = col.lower().replace(" ", "_")
        entity_id = f"csv:{stem}.{safe_col}"

        entity = SourceEntity(
            entity_id=entity_id,
            label=col,
            description=file_description,
            datatype=datatype,
            examples=examples,
            source_file=source_file,
            source_type="csv",
            extra_context={"column_name": col, "total_rows": len(rows)},
        )
        entities.append(entity)

    return entities
