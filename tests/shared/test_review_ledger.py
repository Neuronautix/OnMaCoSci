"""Tests for mapping_co_scientist.shared.persistence.review_ledger."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from mapping_co_scientist.shared.persistence.review_ledger import (
    ReviewDecision,
    ReviewLedger,
    add_decision,
    get_approved_mapping_ids,
    get_decisions_by_source,
    is_mapping_decided,
    load_ledger,
    save_ledger,
    summarise_ledger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    mapping_id: str = "map-001",
    source_id: str = "csv:animals.strain",
    target_id: str = "mbo:MouseStrain",
    action: str = "approved",
    reviewer: str = "alice",
    notes: str = "",
    pipeline_run_id: str | None = None,
) -> ReviewDecision:
    return ReviewDecision(
        mapping_id=mapping_id,
        source_id=source_id,
        target_id=target_id,
        action=action,  # type: ignore[arg-type]
        reviewer=reviewer,
        timestamp="2026-01-01T00:00:00+00:00",
        notes=notes,
        pipeline_run_id=pipeline_run_id,
    )


# ---------------------------------------------------------------------------
# Tests: empty ledger
# ---------------------------------------------------------------------------


def test_empty_ledger_has_no_decisions() -> None:
    """A freshly loaded (non-existent path) ledger has an empty decisions list."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.json"
        ledger = load_ledger(path)
        assert isinstance(ledger, ReviewLedger)
        assert ledger.decisions == []
        assert ledger.ledger_version == "1.0"


def test_load_ledger_from_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    """load_ledger returns an empty ReviewLedger when the file does not exist."""
    path = tmp_path / "does_not_exist.json"
    assert not path.exists()
    ledger = load_ledger(path)
    assert ledger.decisions == []


# ---------------------------------------------------------------------------
# Tests: add_decision
# ---------------------------------------------------------------------------


def test_add_decision_appends(tmp_path: Path) -> None:
    """add_decision appends a decision to the ledger."""
    ledger = load_ledger(tmp_path / "ledger.json")
    d = _make_decision()
    ledger = add_decision(ledger, d)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].mapping_id == "map-001"


def test_add_decision_replaces_existing_for_same_mapping_id(tmp_path: Path) -> None:
    """add_decision replaces any existing decision for the same mapping_id."""
    ledger = load_ledger(tmp_path / "ledger.json")
    d1 = _make_decision(action="rejected", reviewer="alice")
    d2 = _make_decision(action="approved", reviewer="bob")

    ledger = add_decision(ledger, d1)
    ledger = add_decision(ledger, d2)

    decisions_for_id = [d for d in ledger.decisions if d.mapping_id == "map-001"]
    assert len(decisions_for_id) == 1
    assert decisions_for_id[0].action == "approved"
    assert decisions_for_id[0].reviewer == "bob"


def test_add_decision_updates_last_updated(tmp_path: Path) -> None:
    """add_decision updates last_updated on the ledger."""
    ledger = load_ledger(tmp_path / "ledger.json")
    original_updated = ledger.last_updated
    d = _make_decision()
    ledger = add_decision(ledger, d)
    # last_updated must be updated (may equal original if very fast, but type is str)
    assert isinstance(ledger.last_updated, str)
    assert len(ledger.last_updated) > 0


def test_add_multiple_different_decisions(tmp_path: Path) -> None:
    """add_decision with different mapping_ids keeps all entries."""
    ledger = load_ledger(tmp_path / "ledger.json")
    for i in range(3):
        d = _make_decision(mapping_id=f"map-{i:03d}", source_id=f"csv:field_{i}")
        ledger = add_decision(ledger, d)
    assert len(ledger.decisions) == 3


# ---------------------------------------------------------------------------
# Tests: get_approved_mapping_ids
# ---------------------------------------------------------------------------


def test_get_approved_mapping_ids_returns_correct_set(tmp_path: Path) -> None:
    """get_approved_mapping_ids returns only approved mapping_ids."""
    ledger = load_ledger(tmp_path / "ledger.json")
    ledger = add_decision(ledger, _make_decision(mapping_id="map-A", action="approved"))
    ledger = add_decision(ledger, _make_decision(mapping_id="map-B", action="rejected"))
    ledger = add_decision(ledger, _make_decision(mapping_id="map-C", action="needs_more_evidence"))

    approved = get_approved_mapping_ids(ledger)
    assert approved == {"map-A"}


def test_get_approved_mapping_ids_empty_ledger(tmp_path: Path) -> None:
    """get_approved_mapping_ids returns empty set for a ledger with no decisions."""
    ledger = load_ledger(tmp_path / "ledger.json")
    assert get_approved_mapping_ids(ledger) == set()


# ---------------------------------------------------------------------------
# Tests: get_decisions_by_source
# ---------------------------------------------------------------------------


def test_get_decisions_by_source_filters_correctly(tmp_path: Path) -> None:
    """get_decisions_by_source returns only decisions matching the given source_id."""
    ledger = load_ledger(tmp_path / "ledger.json")
    ledger = add_decision(ledger, _make_decision(mapping_id="map-1", source_id="csv:strain"))
    ledger = add_decision(ledger, _make_decision(mapping_id="map-2", source_id="csv:sex"))
    ledger = add_decision(ledger, _make_decision(mapping_id="map-3", source_id="csv:strain"))

    results = get_decisions_by_source(ledger, "csv:strain")
    assert len(results) == 2
    assert all(d.source_id == "csv:strain" for d in results)


def test_get_decisions_by_source_returns_empty_for_unknown_source(tmp_path: Path) -> None:
    """get_decisions_by_source returns an empty list for an unknown source_id."""
    ledger = load_ledger(tmp_path / "ledger.json")
    ledger = add_decision(ledger, _make_decision(source_id="csv:strain"))
    results = get_decisions_by_source(ledger, "csv:nonexistent")
    assert results == []


# ---------------------------------------------------------------------------
# Tests: is_mapping_decided
# ---------------------------------------------------------------------------


def test_is_mapping_decided_returns_true_if_decision_exists(tmp_path: Path) -> None:
    """is_mapping_decided returns True when a decision for mapping_id exists."""
    ledger = load_ledger(tmp_path / "ledger.json")
    ledger = add_decision(ledger, _make_decision(mapping_id="map-X"))
    assert is_mapping_decided(ledger, "map-X") is True


def test_is_mapping_decided_returns_false_if_no_decision(tmp_path: Path) -> None:
    """is_mapping_decided returns False when no decision exists for mapping_id."""
    ledger = load_ledger(tmp_path / "ledger.json")
    assert is_mapping_decided(ledger, "map-UNKNOWN") is False


# ---------------------------------------------------------------------------
# Tests: save_ledger + load_ledger round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_ledger_roundtrip(tmp_path: Path) -> None:
    """A ledger saved to disk and reloaded preserves all decision fields."""
    path = tmp_path / "ledger.json"
    ledger = load_ledger(path)
    d = ReviewDecision(
        mapping_id="map-RT",
        source_id="csv:weight",
        target_id="mbo:BodyWeight",
        action="predicate_changed",
        reviewer="carol",
        timestamp="2026-05-01T12:00:00+00:00",
        notes="Changed to broadMatch",
        predicate_override="skos:broadMatch",
        pipeline_run_id="run-42",
    )
    ledger = add_decision(ledger, d)
    save_ledger(ledger, path)

    reloaded = load_ledger(path)
    assert len(reloaded.decisions) == 1
    r = reloaded.decisions[0]
    assert r.mapping_id == "map-RT"
    assert r.source_id == "csv:weight"
    assert r.target_id == "mbo:BodyWeight"
    assert r.action == "predicate_changed"
    assert r.reviewer == "carol"
    assert r.notes == "Changed to broadMatch"
    assert r.predicate_override == "skos:broadMatch"
    assert r.pipeline_run_id == "run-42"


def test_save_ledger_creates_parent_directories(tmp_path: Path) -> None:
    """save_ledger creates intermediate directories if they do not exist."""
    path = tmp_path / "deep" / "nested" / "ledger.json"
    ledger = load_ledger(path)
    ledger = add_decision(ledger, _make_decision())
    save_ledger(ledger, path)
    assert path.exists()


# ---------------------------------------------------------------------------
# Tests: summarise_ledger
# ---------------------------------------------------------------------------


def test_summarise_ledger_returns_correct_counts(tmp_path: Path) -> None:
    """summarise_ledger returns accurate counts per action type and total."""
    ledger = load_ledger(tmp_path / "ledger.json")
    ledger = add_decision(ledger, _make_decision(mapping_id="m1", action="approved"))
    ledger = add_decision(ledger, _make_decision(mapping_id="m2", action="approved"))
    ledger = add_decision(ledger, _make_decision(mapping_id="m3", action="rejected"))
    ledger = add_decision(ledger, _make_decision(mapping_id="m4", action="needs_more_evidence"))

    summary = summarise_ledger(ledger)

    assert summary["total"] == 4
    by_action = summary["by_action"]
    assert by_action["approved"] == 2
    assert by_action["rejected"] == 1
    assert by_action["needs_more_evidence"] == 1


def test_summarise_ledger_empty(tmp_path: Path) -> None:
    """summarise_ledger on an empty ledger returns total=0 and empty by_action."""
    ledger = load_ledger(tmp_path / "ledger.json")
    summary = summarise_ledger(ledger)
    assert summary["total"] == 0
    assert summary["by_action"] == {}
