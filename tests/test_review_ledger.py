"""Tests for the human review ledger and re-run mode in the orchestrator.

Covers:
- Loading a non-existent ledger returns an empty ReviewLedger.
- add_decision creates the YAML file.
- add_decision persists decisions that survive a reload.
- Adding a duplicate mapping_id replaces the existing entry.
- get_approved_source_ids / get_rejected_source_ids return the correct sets.
- get_decisions_by_source returns a dict keyed by source_entity_id.
- Full ledger round-trip (save then reload).
- Pipeline orchestrator skips approved entities and creates synthetic hypotheses.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest
import yaml

# Ensure src is on the path when running without an editable install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.review_ledger.ledger import (
    ReviewDecision,
    ReviewLedger,
    add_decision,
    get_approved_source_ids,
    get_decisions_by_source,
    get_rejected_source_ids,
    load_ledger,
    save_ledger,
)
from ontology_mapping_co_scientist.review_ledger.cli import (
    action_from_choice,
    approval_blockers,
    load_review_packets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "test_ledger.yaml"


# ---------------------------------------------------------------------------
# Tests: ledger I/O
# ---------------------------------------------------------------------------


def test_empty_ledger_returns_empty(tmp_path: Path) -> None:
    """Loading a non-existent ledger file returns an empty ReviewLedger."""
    path = _ledger_path(tmp_path)
    assert not path.exists()

    ledger = load_ledger(path)

    assert isinstance(ledger, ReviewLedger)
    assert ledger.decisions == []
    assert ledger.ledger_version == "1.0"


def test_add_decision_creates_file(tmp_path: Path) -> None:
    """add_decision creates the YAML file when it does not exist."""
    path = _ledger_path(tmp_path)
    assert not path.exists()

    add_decision(
        ledger_path=path,
        mapping_id="map-001",
        source_entity_id="csv:col.strain",
        action="approve",
        reviewer="alice",
    )

    assert path.exists()


def test_add_decision_persist(tmp_path: Path) -> None:
    """A decision added via add_decision survives a reload."""
    path = _ledger_path(tmp_path)

    add_decision(
        ledger_path=path,
        mapping_id="map-001",
        source_entity_id="csv:col.strain",
        action="approve",
        reviewer="alice",
        note="Looks good",
    )

    reloaded = load_ledger(path)
    assert len(reloaded.decisions) == 1
    d = reloaded.decisions[0]
    assert d.mapping_id == "map-001"
    assert d.source_entity_id == "csv:col.strain"
    assert d.action == "approve"
    assert d.reviewer == "alice"
    assert d.note == "Looks good"


def test_add_duplicate_replaces(tmp_path: Path) -> None:
    """Adding two decisions for the same mapping_id keeps only the latest."""
    path = _ledger_path(tmp_path)

    add_decision(
        ledger_path=path,
        mapping_id="map-001",
        source_entity_id="csv:col.strain",
        action="reject",
        reviewer="alice",
        note="First decision",
    )
    add_decision(
        ledger_path=path,
        mapping_id="map-001",
        source_entity_id="csv:col.strain",
        action="approve",
        reviewer="bob",
        note="Changed my mind",
    )

    reloaded = load_ledger(path)
    # Only one entry should remain for map-001
    decisions_for_map_001 = [d for d in reloaded.decisions if d.mapping_id == "map-001"]
    assert len(decisions_for_map_001) == 1
    assert decisions_for_map_001[0].action == "approve"
    assert decisions_for_map_001[0].reviewer == "bob"


def test_get_approved_source_ids(tmp_path: Path) -> None:
    """get_approved_source_ids returns only IDs with action='approve'."""
    path = _ledger_path(tmp_path)

    add_decision(path, "map-001", "csv:strain", "approve", "alice")
    add_decision(path, "map-002", "csv:sex", "reject", "bob")
    add_decision(path, "map-003", "csv:age", "request_more_evidence", "carol")

    ledger = load_ledger(path)
    approved = get_approved_source_ids(ledger)
    rejected = get_rejected_source_ids(ledger)

    assert approved == {"csv:strain"}
    assert rejected == {"csv:sex"}
    assert "csv:age" not in approved
    assert "csv:age" not in rejected


def test_get_rejected_source_ids(tmp_path: Path) -> None:
    """get_rejected_source_ids returns only IDs with action='reject'."""
    path = _ledger_path(tmp_path)

    add_decision(path, "map-A", "csv:weight", "reject", "dave")
    add_decision(path, "map-B", "csv:colour", "approve", "eve")

    ledger = load_ledger(path)
    assert get_rejected_source_ids(ledger) == {"csv:weight"}
    assert get_approved_source_ids(ledger) == {"csv:colour"}


def test_get_decisions_by_source(tmp_path: Path) -> None:
    """get_decisions_by_source returns a dict keyed by source_entity_id."""
    path = _ledger_path(tmp_path)

    add_decision(path, "map-001", "csv:strain", "approve", "alice", note="first")
    add_decision(path, "map-002", "csv:sex", "reject", "bob", note="second")

    ledger = load_ledger(path)
    by_source = get_decisions_by_source(ledger)

    assert set(by_source.keys()) == {"csv:strain", "csv:sex"}
    assert by_source["csv:strain"].action == "approve"
    assert by_source["csv:sex"].action == "reject"


def test_get_decisions_by_source_latest_wins(tmp_path: Path) -> None:
    """When multiple decisions exist for the same source entity, the latest wins."""
    path = _ledger_path(tmp_path)

    # Two different mapping_ids for the same source entity
    add_decision(path, "map-001", "csv:strain", "reject", "alice")
    add_decision(path, "map-002", "csv:strain", "approve", "bob")

    ledger = load_ledger(path)
    by_source = get_decisions_by_source(ledger)

    # The second (later) decision should win
    assert by_source["csv:strain"].action == "approve"


def test_ledger_roundtrip(tmp_path: Path) -> None:
    """A ReviewLedger saved and reloaded from YAML is identical."""
    path = _ledger_path(tmp_path)

    original = ReviewLedger(
        ledger_version="1.0",
        last_updated="2026-01-01T00:00:00+00:00",
        decisions=[
            ReviewDecision(
                mapping_id="map-X",
                source_entity_id="csv:x",
                action="approve",
                reviewer="tester",
                timestamp="2026-01-01T00:00:00+00:00",
                note="round-trip test",
                predicate_override="skos:closeMatch",
                pipeline_run_id="run-42",
            )
        ],
    )

    save_ledger(original, path)
    reloaded = load_ledger(path)

    assert reloaded.ledger_version == original.ledger_version
    assert reloaded.last_updated == original.last_updated
    assert len(reloaded.decisions) == 1
    d = reloaded.decisions[0]
    assert d.mapping_id == "map-X"
    assert d.source_entity_id == "csv:x"
    assert d.action == "approve"
    assert d.reviewer == "tester"
    assert d.note == "round-trip test"
    assert d.predicate_override == "skos:closeMatch"
    assert d.pipeline_run_id == "run-42"


# ---------------------------------------------------------------------------
# Tests: interactive review helpers
# ---------------------------------------------------------------------------


def test_load_review_packets_from_review_queue(tmp_path: Path) -> None:
    """The chat CLI can load the dedicated pipeline review queue format."""
    review_path = tmp_path / "review_queue.json"
    review_path.write_text(
        json.dumps(
            {
                "metadata": {"pipeline_run_id": "run-queue-001"},
                "review_packets": [
                    {
                        "source_entity_id": "csv:animals.strain",
                        "source_entity_label": "strain",
                        "top_mapping": {
                            "mapping_id": "map-001",
                            "predicate": "skos:exactMatch",
                            "confidence": 0.91,
                            "validation_status": "passed",
                            "target_entity": {
                                "term_id": "mbo:MouseStrain",
                                "label": "mouse strain",
                            },
                        },
                        "alternative_mappings": [],
                        "all_warnings": [],
                    }
                ],
            },
        ),
        encoding="utf-8",
    )

    metadata, packets = load_review_packets(review_path)

    assert metadata["pipeline_run_id"] == "run-queue-001"
    assert len(packets) == 1
    assert packets[0]["source_entity_id"] == "csv:animals.strain"


def test_load_review_packets_from_mappings_json(tmp_path: Path) -> None:
    """The chat CLI can synthesize packets from raw mappings JSON."""
    review_path = tmp_path / "mappings.json"
    review_path.write_text(
        json.dumps(
            {
                "metadata": {"pipeline_run_id": "run-mappings-001"},
                "mappings": [
                    {
                        "mapping_id": "map-001",
                        "source_entity": {
                            "entity_id": "csv:animals.strain",
                            "label": "strain",
                        },
                        "target_entity": {
                            "term_id": "mbo:MouseStrain",
                            "label": "mouse strain",
                        },
                        "predicate": "skos:exactMatch",
                        "confidence": 0.91,
                        "rank": 1,
                        "validation_status": "passed",
                        "warnings": [],
                    }
                ],
            },
        ),
        encoding="utf-8",
    )

    metadata, packets = load_review_packets(review_path)

    assert metadata["pipeline_run_id"] == "run-mappings-001"
    assert len(packets) == 1
    assert packets[0]["top_mapping"]["mapping_id"] == "map-001"


def test_action_from_choice_blocks_approval_for_high_severity() -> None:
    """Strict chat mode prevents approval when adversarial review blocks it."""
    packet = {
        "top_mapping": {
            "mapping_id": "map-001",
            "predicate": "skos:exactMatch",
            "validation_status": "passed",
            "_adv_flags": [
                {
                    "flag_type": "strong_exactmatch_claim",
                    "severity": "high",
                    "description": "Exact match is too strong.",
                }
            ],
        },
        "all_warnings": [],
    }

    blockers = approval_blockers(packet)
    action, error = action_from_choice("a", packet)

    assert blockers
    assert action is None
    assert error is not None
    assert "Approval is blocked" in error


def test_action_from_choice_accepts_match_alias_for_approval() -> None:
    """The chat CLI accepts natural reviewer language for an unblocked match."""
    packet = {
        "top_mapping": {
            "mapping_id": "map-001",
            "predicate": "skos:closeMatch",
            "validation_status": "passed",
            "_adv_flags": [],
        },
        "all_warnings": [],
    }

    action, error = action_from_choice("match", packet)

    assert error is None
    assert action == "approve"


def test_action_from_choice_accepts_numbered_decisions() -> None:
    """The chat CLI supports compact numbered choices."""
    packet = {
        "top_mapping": {
            "mapping_id": "map-001",
            "predicate": "skos:exactMatch",
            "validation_status": "passed",
        },
        "all_warnings": [],
    }

    assert action_from_choice("2", packet) == ("change_predicate", None)
    assert action_from_choice("3", packet) == ("request_more_evidence", None)
    assert action_from_choice("4", packet) == ("reject", None)


def test_action_from_choice_allows_request_evidence_when_blocked() -> None:
    """Blocked hypotheses remain in the negative feedback loop."""
    packet = {
        "top_mapping": {
            "mapping_id": "map-001",
            "predicate": "skos:exactMatch",
            "validation_status": "failed",
        },
        "all_warnings": [],
    }

    action, error = action_from_choice("e", packet)

    assert error is None
    assert action == "request_more_evidence"


# ---------------------------------------------------------------------------
# Tests: orchestrator re-run mode
# ---------------------------------------------------------------------------


def test_pipeline_with_ledger_skips_approved(tmp_path: Path) -> None:
    """Orchestrator re-run mode: approved entities get a synthetic APPROVED hypothesis."""
    import yaml as _yaml

    from ontology_mapping_co_scientist.agents.orchestrator import OrchestratorAgent
    from ontology_mapping_co_scientist.models.mapping_hypothesis import HumanReviewStatus

    # Build a minimal CSV with two columns: strain and sex
    csv_path = tmp_path / "animals.csv"
    csv_path.write_text(
        "animal_id,strain,sex\n"
        "A001,C57BL/6J,M\n"
        "A002,BALB/c,F\n",
        encoding="utf-8",
    )

    # Build a minimal ontology profile
    profile = {
        "ontology_id": "mbo",
        "ontology_source": "test",
        "terms": [
            {
                "term_id": "mbo:MouseStrain",
                "label": "mouse strain",
                "definition": "A genetically distinct mouse lineage.",
                "synonyms": ["strain"],
                "parent_terms": [],
                "term_type": "class",
                "extra_context": {},
            },
            {
                "term_id": "mbo:BiologicalSex",
                "label": "biological sex",
                "definition": "The biological sex classification.",
                "synonyms": ["sex", "gender"],
                "parent_terms": [],
                "term_type": "class",
                "extra_context": {},
            },
        ],
    }
    onto_path = tmp_path / "ontology.yaml"
    onto_path.write_text(_yaml.dump(profile), encoding="utf-8")

    # Create a ledger that approves the 'strain' entity
    # The SourceProfilerAgent creates entity_id like "csv:<stem>.<column>"
    # For animals.csv the stem is "animals", column is "strain"
    ledger_path = tmp_path / "ledger.yaml"
    add_decision(
        ledger_path=ledger_path,
        mapping_id="map-pre-approved-strain",
        source_entity_id="csv:animals.strain",
        action="approve",
        reviewer="test-reviewer",
        note="Previously approved",
    )

    output_dir = tmp_path / "output"
    orchestrator = OrchestratorAgent()
    result = orchestrator.run(
        source_filepath=csv_path,
        ontology_filepath=onto_path,
        output_dir=output_dir,
        pipeline_run_id="test-rerun-001",
        ledger_path=ledger_path,
    )

    # Verify summary keys exist
    assert "skipped_approved" in result
    assert "skipped_rejected" in result
    assert "new_candidates" in result

    assert result["skipped_approved"] == 1
    assert result["skipped_rejected"] == 0

    # Find the synthetic hypothesis for the approved entity
    hypotheses = result.get("total_hypotheses", 0)
    assert hypotheses > 0

    # We can't directly access the hypothesis list from the summary dict,
    # but we can inspect the JSON export
    json_path = output_dir / "hypotheses.json"
    assert json_path.exists()

    import json as _json
    data = _json.loads(json_path.read_text(encoding="utf-8"))
    # The export format wraps in {"hypotheses": [...]}
    hyps_data = data.get("hypotheses", data) if isinstance(data, dict) else data
    if isinstance(hyps_data, dict):
        hyps_data = hyps_data.get("hypotheses", [])

    # Find the synthetic hypothesis
    approved_hyps = [
        h for h in hyps_data
        if isinstance(h, dict)
        and h.get("human_review_status") == "approved"
        and h.get("source_entity", {}).get("entity_id") == "csv:animals.strain"
    ]
    assert len(approved_hyps) >= 1, (
        f"Expected at least one approved hypothesis for csv:animals.strain; "
        f"got: {[h.get('source_entity', {}).get('entity_id') for h in hyps_data]}"
    )
    synth = approved_hyps[0]
    assert synth["confidence"] == 1.0
    assert synth["predicate"] == "skos:exactMatch"
    assert "Previously approved" in synth.get("reviewer_notes", [])
