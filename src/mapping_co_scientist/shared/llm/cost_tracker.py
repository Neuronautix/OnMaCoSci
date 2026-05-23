from __future__ import annotations
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    call_description: str = ""


class CostTracker:
    """Thread-safe token usage tracker."""

    # Approximate costs per 1M tokens (USD) — update as models change
    COST_PER_M_INPUT: dict[str, float] = {
        "claude-sonnet-4-6": 3.00,
        "claude-haiku-4-5-20251001": 0.80,
        "claude-opus-4-7": 15.00,
        "default": 3.00,
    }
    COST_PER_M_OUTPUT: dict[str, float] = {
        "claude-sonnet-4-6": 15.00,
        "claude-haiku-4-5-20251001": 4.00,
        "claude-opus-4-7": 75.00,
        "default": 15.00,
    }

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = Lock()

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        description: str = "",
    ) -> None:
        """Thread-safe append of a usage record."""
        with self._lock:
            self._records.append(
                UsageRecord(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    call_description=description,
                )
            )

    def total_tokens(self) -> tuple[int, int]:
        """Return (total_input_tokens, total_output_tokens)."""
        with self._lock:
            total_in = sum(r.input_tokens for r in self._records)
            total_out = sum(r.output_tokens for r in self._records)
        return total_in, total_out

    def estimated_cost_usd(self) -> float:
        """Estimate total cost in USD using per-model rates (falls back to 'default')."""
        with self._lock:
            records = list(self._records)
        total = 0.0
        for r in records:
            in_rate = self.COST_PER_M_INPUT.get(r.model, self.COST_PER_M_INPUT["default"])
            out_rate = self.COST_PER_M_OUTPUT.get(r.model, self.COST_PER_M_OUTPUT["default"])
            total += (r.input_tokens / 1_000_000) * in_rate
            total += (r.output_tokens / 1_000_000) * out_rate
        return total

    def summary(self) -> dict:
        """Return a summary dict with call counts, token totals, cost, and per-model breakdown."""
        with self._lock:
            records = list(self._records)

        total_in = sum(r.input_tokens for r in records)
        total_out = sum(r.output_tokens for r in records)

        by_model: dict[str, dict] = {}
        for r in records:
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["input_tokens"] += r.input_tokens
            by_model[r.model]["output_tokens"] += r.output_tokens

        return {
            "calls": len(records),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "estimated_cost_usd": self.estimated_cost_usd(),
            "by_model": by_model,
        }

    def reset(self) -> None:
        """Clear all recorded usage."""
        with self._lock:
            self._records.clear()
