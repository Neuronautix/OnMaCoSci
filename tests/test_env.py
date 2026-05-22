"""Tests for local .env loading."""

from __future__ import annotations

import os
from pathlib import Path

from ontology_mapping_co_scientist.env import load_dotenv


def test_load_dotenv_reads_key_value_pairs(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# local secrets",
                "ANTHROPIC_API_KEY=sk-test-value",
                'OMCS_DOMAIN_CONTEXT="preclinical mouse metadata"',
                "export OMCS_LLM_MODEL=claude-test-model # inline comment",
                "OMCS_LLM_CALL_DELAY_SECONDS=1.0",
                "OMCS_LLM_MAX_REVIEW_HYPOTHESES=10",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OMCS_DOMAIN_CONTEXT", raising=False)
    monkeypatch.delenv("OMCS_LLM_MODEL", raising=False)
    monkeypatch.delenv("OMCS_LLM_CALL_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("OMCS_LLM_MAX_REVIEW_HYPOTHESES", raising=False)

    loaded = load_dotenv(env_path)

    assert loaded == env_path
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-value"
    assert os.environ["OMCS_DOMAIN_CONTEXT"] == "preclinical mouse metadata"
    assert os.environ["OMCS_LLM_MODEL"] == "claude-test-model"
    assert os.environ["OMCS_LLM_CALL_DELAY_SECONDS"] == "1.0"
    assert os.environ["OMCS_LLM_MAX_REVIEW_HYPOTHESES"] == "10"


def test_load_dotenv_does_not_override_existing_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")

    load_dotenv(env_path)

    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_load_dotenv_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OMCS_DISABLE_DOTENV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    loaded = load_dotenv(env_path)

    assert loaded is None
    assert "ANTHROPIC_API_KEY" not in os.environ
