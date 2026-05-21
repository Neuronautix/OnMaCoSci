"""
LLM cost tracker for the Ontology Mapping Co-Scientist pipeline.

Tracks token usage and estimated cost across all LLM calls in a pipeline run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LLMCostTracker:
    """Tracks token usage and estimated cost across all LLM calls in a pipeline run.

    Pricing: claude-haiku-4-5-20251001 at $0.80/M input, $4.00/M output (2025 rates).

    Attributes:
        PRICING: Class-level pricing table mapping model IDs to per-million-token costs.
        calls: List of recorded call dicts (agent, model, input_tokens, output_tokens, timestamp).
    """

    # Class-level pricing table (USD per million tokens)
    PRICING: dict[str, dict[str, float]] = {
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    }

    def __init__(self) -> None:
        """Initialise the tracker with an empty calls list."""
        self.calls: list[dict] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def record(
        self,
        agent_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record a single LLM call.

        Args:
            agent_name: Name of the agent that made the call.
            model: The model ID used.
            input_tokens: Number of input tokens consumed.
            output_tokens: Number of output tokens generated.
        """
        self.calls.append(
            {
                "agent": agent_name,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        logger.debug(
            "LLMCostTracker.record: agent=%s model=%s in=%d out=%d",
            agent_name,
            model,
            input_tokens,
            output_tokens,
        )

    def total_tokens(self) -> dict:
        """Return total input, output, and combined token counts.

        Returns:
            Dict with keys ``"input"``, ``"output"``, and ``"total"``.
        """
        total_in = sum(c["input_tokens"] for c in self.calls)
        total_out = sum(c["output_tokens"] for c in self.calls)
        return {"input": total_in, "output": total_out, "total": total_in + total_out}

    def estimated_cost_usd(self) -> float:
        """Return the estimated total cost across all recorded calls in USD.

        Models not present in :attr:`PRICING` contribute zero cost and trigger
        a debug log message.

        Returns:
            Estimated cost in USD as a float.
        """
        total_cost = 0.0
        for call in self.calls:
            model = call["model"]
            pricing = self.PRICING.get(model)
            if pricing is None:
                logger.debug(
                    "LLMCostTracker: no pricing found for model '%s'; "
                    "contributing $0.00 for this call.",
                    model,
                )
                continue
            total_cost += (call["input_tokens"] / 1_000_000) * pricing["input"]
            total_cost += (call["output_tokens"] / 1_000_000) * pricing["output"]
        return total_cost

    def summary(self) -> dict:
        """Return a structured usage and cost summary.

        Returns:
            Dict with keys:

            * ``total_calls`` — number of LLM calls recorded.
            * ``total_input_tokens`` — total input tokens across all calls.
            * ``total_output_tokens`` — total output tokens across all calls.
            * ``estimated_cost_usd`` — estimated cost in USD.
            * ``by_agent`` — dict mapping agent name to sub-summary dict with
              ``calls``, ``input_tokens``, ``output_tokens``, and ``cost_usd``.
        """
        totals = self.total_tokens()
        by_agent: dict[str, dict] = {}

        for call in self.calls:
            agent = call["agent"]
            model = call["model"]
            if agent not in by_agent:
                by_agent[agent] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_agent[agent]["calls"] += 1
            by_agent[agent]["input_tokens"] += call["input_tokens"]
            by_agent[agent]["output_tokens"] += call["output_tokens"]

            pricing = self.PRICING.get(model)
            if pricing is not None:
                by_agent[agent]["cost_usd"] += (
                    call["input_tokens"] / 1_000_000
                ) * pricing["input"]
                by_agent[agent]["cost_usd"] += (
                    call["output_tokens"] / 1_000_000
                ) * pricing["output"]

        return {
            "total_calls": len(self.calls),
            "total_input_tokens": totals["input"],
            "total_output_tokens": totals["output"],
            "estimated_cost_usd": self.estimated_cost_usd(),
            "by_agent": by_agent,
        }

    def print_summary(self) -> None:
        """Print a formatted cost/usage table to stdout."""
        s = self.summary()
        print("=" * 60)
        print("LLM Cost Tracker Summary")
        print("=" * 60)
        print(f"  Total calls         : {s['total_calls']}")
        print(f"  Total input tokens  : {s['total_input_tokens']:,}")
        print(f"  Total output tokens : {s['total_output_tokens']:,}")
        print(f"  Estimated cost (USD): ${s['estimated_cost_usd']:.6f}")
        print("")
        if s["by_agent"]:
            print(f"  {'Agent':<40} {'Calls':>6} {'Input':>10} {'Output':>10} {'Cost ($)':>10}")
            print("  " + "-" * 80)
            for agent_name, data in sorted(s["by_agent"].items()):
                print(
                    f"  {agent_name:<40} {data['calls']:>6} "
                    f"{data['input_tokens']:>10,} {data['output_tokens']:>10,} "
                    f"{data['cost_usd']:>10.6f}"
                )
        print("=" * 60)
