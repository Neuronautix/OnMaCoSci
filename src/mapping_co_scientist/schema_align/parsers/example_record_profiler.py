"""Profile example records to extract per-field statistics."""
from __future__ import annotations

import csv
from pathlib import Path


def profile_csv_examples(path: Path, max_rows: int = 100) -> dict[str, list[str]]:
    """Return {field_name: [example_values]} from CSV."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)[:max_rows]
    if not rows:
        return {}
    result: dict[str, list[str]] = {}
    for header in rows[0]:
        seen: list[str] = []
        for row in rows:
            v = row.get(header, "").strip()
            if v and v not in seen:
                seen.append(v)
            if len(seen) >= 5:
                break
        result[header] = seen
    return result
