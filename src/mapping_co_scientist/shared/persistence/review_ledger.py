from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field


class ReviewDecision(BaseModel):
    mapping_id: str
    source_id: str  # entity_id or source_path
    target_id: str  # term_id or target_path
    action: Literal[
        "approved", "rejected", "needs_more_evidence",
        "predicate_changed", "new_term_requested",
        "change_operation", "change_target",
    ]
    reviewer: str
    timestamp: str  # ISO 8601
    notes: str = ""
    predicate_override: str | None = None  # for predicate_changed
    target_override: str | None = None     # for change_target
    operation_override: str | None = None  # for change_operation
    pipeline_run_id: str | None = None
    model_config = {"frozen": False, "extra": "forbid"}


class ReviewLedger(BaseModel):
    ledger_version: str = "1.0"
    created_at: str
    last_updated: str
    decisions: list[ReviewDecision] = Field(default_factory=list)
    model_config = {"frozen": False, "extra": "forbid"}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_ledger(path: Path) -> ReviewLedger:
    """Read a ReviewLedger from JSON. Returns an empty ledger if path does not exist."""
    if not path.exists():
        now = _now_iso()
        return ReviewLedger(created_at=now, last_updated=now)
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReviewLedger.model_validate(data)


def save_ledger(ledger: ReviewLedger, path: Path) -> None:
    """Write a ReviewLedger to JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")


def add_decision(
    ledger: ReviewLedger,
    decision: ReviewDecision,
) -> ReviewLedger:
    """Append decision to the ledger, replacing any existing entry with the same mapping_id.

    Updates last_updated and returns the mutated ledger.
    """
    # Remove any existing decision for this mapping_id
    ledger.decisions = [d for d in ledger.decisions if d.mapping_id != decision.mapping_id]
    ledger.decisions.append(decision)
    ledger.last_updated = _now_iso()
    return ledger


def get_approved_mapping_ids(ledger: ReviewLedger) -> set[str]:
    """Return the set of mapping_ids whose action is 'approved'."""
    return {d.mapping_id for d in ledger.decisions if d.action == "approved"}


def get_decisions_by_source(ledger: ReviewLedger, source_id: str) -> list[ReviewDecision]:
    """Return all decisions whose source_id matches the given value."""
    return [d for d in ledger.decisions if d.source_id == source_id]


def is_mapping_decided(ledger: ReviewLedger, mapping_id: str) -> bool:
    """Return True if any decision exists for this mapping_id."""
    return any(d.mapping_id == mapping_id for d in ledger.decisions)


def summarise_ledger(ledger: ReviewLedger) -> dict:
    """Return counts per action type plus total."""
    counts: dict[str, int] = {}
    for d in ledger.decisions:
        counts[d.action] = counts.get(d.action, 0) + 1
    return {"total": len(ledger.decisions), "by_action": counts}
