"""Tests for CostTracker and ClaudeProvider (import guard only for ClaudeProvider)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from mapping_co_scientist.shared.llm.cost_tracker import CostTracker, UsageRecord


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


def test_cost_tracker_record_accumulates() -> None:
    """CostTracker.record() accumulates UsageRecord entries."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", input_tokens=100, output_tokens=50, description="call-1")
    tracker.record("claude-sonnet-4-6", input_tokens=200, output_tokens=75, description="call-2")
    assert len(tracker._records) == 2


def test_cost_tracker_total_tokens_sums_correctly() -> None:
    """CostTracker.total_tokens() returns the sum of all input and output tokens."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", 1000, 500)
    tracker.record("claude-haiku-4-5-20251001", 2000, 1000)

    total_in, total_out = tracker.total_tokens()
    assert total_in == 3000
    assert total_out == 1500


def test_cost_tracker_total_tokens_empty() -> None:
    """CostTracker.total_tokens() returns (0, 0) when no records exist."""
    tracker = CostTracker()
    assert tracker.total_tokens() == (0, 0)


def test_cost_tracker_estimated_cost_uses_correct_rates() -> None:
    """CostTracker.estimated_cost_usd() uses per-model rates from the class-level dicts."""
    tracker = CostTracker()
    # 1M input tokens at $3.00/M + 1M output tokens at $15.00/M = $18.00
    tracker.record("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    cost = tracker.estimated_cost_usd()
    assert abs(cost - 18.00) < 1e-6


def test_cost_tracker_estimated_cost_uses_default_rate_for_unknown_model() -> None:
    """estimated_cost_usd() falls back to 'default' rates for unknown models."""
    tracker = CostTracker()
    # 1M input at $3.00/M default + 1M output at $15.00/M default = $18.00
    tracker.record("unknown-model-xyz", input_tokens=1_000_000, output_tokens=1_000_000)
    cost = tracker.estimated_cost_usd()
    assert abs(cost - 18.00) < 1e-6


def test_cost_tracker_estimated_cost_haiku_rates() -> None:
    """estimated_cost_usd() uses the correct Haiku rates."""
    tracker = CostTracker()
    # 1M input at $0.80/M + 1M output at $4.00/M = $4.80
    tracker.record("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
    cost = tracker.estimated_cost_usd()
    assert abs(cost - 4.80) < 1e-6


def test_cost_tracker_summary_returns_expected_structure() -> None:
    """CostTracker.summary() returns a dict with required keys and correct values."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", 100, 50, "first")
    tracker.record("claude-sonnet-4-6", 200, 100, "second")
    tracker.record("claude-haiku-4-5-20251001", 400, 200, "third")

    summary = tracker.summary()

    assert "calls" in summary
    assert "input_tokens" in summary
    assert "output_tokens" in summary
    assert "estimated_cost_usd" in summary
    assert "by_model" in summary

    assert summary["calls"] == 3
    assert summary["input_tokens"] == 700
    assert summary["output_tokens"] == 350
    assert isinstance(summary["estimated_cost_usd"], float)

    by_model = summary["by_model"]
    assert "claude-sonnet-4-6" in by_model
    assert "claude-haiku-4-5-20251001" in by_model
    assert by_model["claude-sonnet-4-6"]["calls"] == 2
    assert by_model["claude-sonnet-4-6"]["input_tokens"] == 300
    assert by_model["claude-sonnet-4-6"]["output_tokens"] == 150
    assert by_model["claude-haiku-4-5-20251001"]["calls"] == 1


def test_cost_tracker_reset_clears_records() -> None:
    """CostTracker.reset() clears all recorded usage."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", 1000, 500)
    tracker.record("claude-sonnet-4-6", 2000, 1000)
    assert len(tracker._records) == 2

    tracker.reset()

    assert len(tracker._records) == 0
    assert tracker.total_tokens() == (0, 0)
    assert tracker.estimated_cost_usd() == 0.0


def test_cost_tracker_reset_then_record() -> None:
    """After reset, new records are accumulated from zero."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", 500, 250)
    tracker.reset()
    tracker.record("claude-sonnet-4-6", 100, 50)
    total_in, total_out = tracker.total_tokens()
    assert total_in == 100
    assert total_out == 50


# ---------------------------------------------------------------------------
# ClaudeProvider import-guard test
# ---------------------------------------------------------------------------


def test_claude_provider_raises_import_error_when_anthropic_not_installed() -> None:
    """ClaudeProvider raises ImportError with a clear message if 'anthropic' is missing."""
    # Temporarily hide the anthropic module from the import system
    original_modules = sys.modules.copy()
    sys.modules["anthropic"] = None  # type: ignore[assignment]
    try:
        # Force reimport of the provider module
        if "mapping_co_scientist.shared.llm.claude_provider" in sys.modules:
            del sys.modules["mapping_co_scientist.shared.llm.claude_provider"]

        with pytest.raises(ImportError, match="anthropic"):
            from mapping_co_scientist.shared.llm.claude_provider import ClaudeProvider
            ClaudeProvider()
    finally:
        # Restore original module state
        sys.modules.clear()
        sys.modules.update(original_modules)
        # Ensure the module is reimportable cleanly in subsequent tests
        for key in list(sys.modules.keys()):
            if key.startswith("mapping_co_scientist.shared.llm.claude_provider"):
                del sys.modules[key]


def test_claude_provider_model_name_property() -> None:
    """ClaudeProvider.model_name returns the configured model."""
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = MagicMock()
    mock_anthropic.NOT_GIVEN = None

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        # Remove cached module if present
        if "mapping_co_scientist.shared.llm.claude_provider" in sys.modules:
            del sys.modules["mapping_co_scientist.shared.llm.claude_provider"]

        from mapping_co_scientist.shared.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(model="claude-haiku-4-5-20251001", api_key="test-key")
        assert provider.model_name == "claude-haiku-4-5-20251001"
