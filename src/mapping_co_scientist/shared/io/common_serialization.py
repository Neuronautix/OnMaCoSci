from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel


def write_json(data: Any, path: Path, indent: int = 2) -> None:
    if isinstance(data, BaseModel):
        path.write_text(data.model_dump_json(indent=indent), encoding="utf-8")
    elif isinstance(data, list) and data and isinstance(data[0], BaseModel):
        path.write_text(
            json.dumps([item.model_dump(mode="json") for item in data], indent=indent),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(data, indent=indent, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
