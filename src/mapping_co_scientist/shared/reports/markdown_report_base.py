from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime


class MarkdownReportBase(ABC):
    def __init__(self, pipeline_run_id: str):
        self.pipeline_run_id = pipeline_run_id
        self.generated_at = datetime.utcnow().isoformat()

    @abstractmethod
    def generate(self, **kwargs) -> str: ...

    def write(self, output_path: Path, **kwargs) -> None:
        content = self.generate(**kwargs)
        output_path.write_text(content, encoding="utf-8")

    def _header(self, title: str, level: int = 1) -> str:
        return "#" * level + " " + title + "\n\n"

    def _table_row(self, cells: list[str]) -> str:
        return "| " + " | ".join(str(c) for c in cells) + " |\n"

    def _separator(self, n_cols: int) -> str:
        return "| " + " | ".join(["---"] * n_cols) + " |\n"
