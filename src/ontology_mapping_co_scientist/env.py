"""Environment loading helpers for local CLI usage."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(env_path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """Load simple KEY=VALUE pairs from a .env file into ``os.environ``.

    The parser intentionally supports the common subset needed by this project:
    blank lines, comments, optional ``export`` prefixes, and quoted or unquoted
    values. Existing process environment variables win unless ``override`` is
    true.
    """
    if os.environ.get("OMCS_DISABLE_DOTENV") == "1":
        return None

    path = Path(env_path) if env_path is not None else _find_dotenv()
    if path is None or not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_inline_comment(value.strip())
        if not key:
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = _unquote(value)

    return path


def _find_dotenv() -> Path | None:
    """Find ``.env`` in the current directory or one of its parents."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _strip_inline_comment(value: str) -> str:
    if not value or value[0] in {"'", '"'}:
        return value
    hash_index = value.find(" #")
    if hash_index == -1:
        return value
    return value[:hash_index].rstrip()
