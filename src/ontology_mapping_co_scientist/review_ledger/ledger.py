"""
Persistent human review decision store. Decisions are written to a YAML file
(mapping_review_ledger.yaml by default) and read back on subsequent pipeline runs.

Each decision records:
- mapping_id: the hypothesis being reviewed
- source_entity_id: for quick lookup
- action: approve | reject | change_predicate | request_more_evidence | create_new_ontology_term
- reviewer: name or identifier of the human reviewer
- timestamp: ISO datetime
- note: free text justification
- predicate_override: optional new predicate if action is change_predicate
- pipeline_run_id: which pipeline run produced the hypothesis
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel


class ReviewDecision(BaseModel):
    """A single human review decision recorded in the ledger."""

    mapping_id: str
    source_entity_id: str
    action: str  # matches HumanReviewAction values
    reviewer: str
    timestamp: str  # ISO datetime
    note: str = ""
    predicate_override: str | None = None  # e.g. "skos:closeMatch"
    pipeline_run_id: str | None = None

    model_config = {"frozen": False, "extra": "forbid"}


class ReviewLedger(BaseModel):
    """Container for all human review decisions."""

    ledger_version: str = "1.0"
    last_updated: str = ""
    decisions: list[ReviewDecision] = []

    model_config = {"frozen": False, "extra": "forbid"}


def load_ledger(ledger_path: str | Path) -> ReviewLedger:
    """Load a ReviewLedger from a YAML file.

    If the file does not exist, returns an empty ReviewLedger with a blank
    last_updated timestamp.

    Args:
        ledger_path: Path to the YAML ledger file.

    Returns:
        A :class:`ReviewLedger` populated from the file, or a fresh empty
        instance if the file does not exist.
    """
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return ReviewLedger(last_updated="")
    with ledger_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return ReviewLedger(last_updated="")
    return ReviewLedger.model_validate(data)


def save_ledger(ledger: ReviewLedger, ledger_path: str | Path) -> None:
    """Serialize a ReviewLedger to a YAML file.

    Args:
        ledger: The :class:`ReviewLedger` to serialize.
        ledger_path: Destination path for the YAML file.  Parent directories
            are created automatically if they do not exist.
    """
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w", encoding="utf-8") as fh:
        yaml.dump(ledger.model_dump(), fh, allow_unicode=True, sort_keys=False)


def add_decision(
    ledger_path: str | Path,
    mapping_id: str,
    source_entity_id: str,
    action: str,
    reviewer: str,
    note: str = "",
    predicate_override: str | None = None,
    pipeline_run_id: str | None = None,
) -> ReviewDecision:
    """Add or replace a review decision in the ledger.

    Loads the existing ledger, appends (or replaces) the decision for the
    given *mapping_id*, updates the ``last_updated`` timestamp, saves the
    ledger back to disk, and returns the new :class:`ReviewDecision`.

    If *mapping_id* already has an entry, the existing entry is **replaced**
    (most-recent-wins semantics).

    Args:
        ledger_path: Path to the YAML ledger file.
        mapping_id: Unique identifier of the hypothesis being reviewed.
        source_entity_id: Identifier of the source entity this decision covers.
        action: One of the :class:`~.models.review.HumanReviewAction` string
            values, e.g. ``"approve"``, ``"reject"``.
        reviewer: Name or identifier of the human reviewer.
        note: Optional free-text justification.
        predicate_override: Optional replacement predicate string when
            *action* is ``"change_predicate"``.
        pipeline_run_id: Optional identifier of the pipeline run that
            produced the hypothesis.

    Returns:
        The newly created :class:`ReviewDecision`.
    """
    ledger = load_ledger(ledger_path)
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    decision = ReviewDecision(
        mapping_id=mapping_id,
        source_entity_id=source_entity_id,
        action=action,
        reviewer=reviewer,
        timestamp=now_iso,
        note=note,
        predicate_override=predicate_override,
        pipeline_run_id=pipeline_run_id,
    )

    # Replace existing decision for this mapping_id, or append new one
    existing_indices = [
        i for i, d in enumerate(ledger.decisions) if d.mapping_id == mapping_id
    ]
    if existing_indices:
        ledger.decisions[existing_indices[0]] = decision
        # Remove any duplicates (keep only the first slot, now updated)
        for extra_idx in reversed(existing_indices[1:]):
            ledger.decisions.pop(extra_idx)
    else:
        ledger.decisions.append(decision)

    ledger.last_updated = now_iso
    save_ledger(ledger, ledger_path)
    return decision


def get_decisions_by_source(ledger: ReviewLedger) -> dict[str, ReviewDecision]:
    """Return a mapping from source_entity_id to the most recent ReviewDecision.

    When multiple decisions exist for the same source entity, the one with
    the latest timestamp is returned.

    Args:
        ledger: The :class:`ReviewLedger` to inspect.

    Returns:
        A dict keyed by *source_entity_id* whose values are the most recent
        :class:`ReviewDecision` for that entity.
    """
    result: dict[str, ReviewDecision] = {}
    for decision in ledger.decisions:
        existing = result.get(decision.source_entity_id)
        if existing is None or decision.timestamp >= existing.timestamp:
            result[decision.source_entity_id] = decision
    return result


def get_approved_source_ids(ledger: ReviewLedger) -> set[str]:
    """Return source_entity_ids whose most recent decision is 'approve'.

    Args:
        ledger: The :class:`ReviewLedger` to inspect.

    Returns:
        A set of *source_entity_id* strings where the latest decision action
        is ``"approve"``.
    """
    by_source = get_decisions_by_source(ledger)
    return {sid for sid, d in by_source.items() if d.action == "approve"}


def get_rejected_source_ids(ledger: ReviewLedger) -> set[str]:
    """Return source_entity_ids whose most recent decision is 'reject'.

    Args:
        ledger: The :class:`ReviewLedger` to inspect.

    Returns:
        A set of *source_entity_id* strings where the latest decision action
        is ``"reject"``.
    """
    by_source = get_decisions_by_source(ledger)
    return {sid for sid, d in by_source.items() if d.action == "reject"}
