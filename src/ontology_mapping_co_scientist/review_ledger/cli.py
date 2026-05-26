"""
CLI for recording human review decisions into the mapping review ledger.

Usage:
  omcs-review [--ledger PATH] accept <mapping_id> --source <entity_id> [--reviewer NAME] [--note TEXT]
  omcs-review [--ledger PATH] reject <mapping_id> --source <entity_id> [--reviewer NAME] [--note TEXT]
  omcs-review [--ledger PATH] change-predicate <mapping_id> --source <entity_id> --predicate skos:closeMatch [--note TEXT]
  omcs-review [--ledger PATH] request-evidence <mapping_id> --source <entity_id> [--note TEXT]
  omcs-review [--ledger PATH] chat <review_queue.json> [--reviewer NAME]
  omcs-review [--ledger PATH] status
  omcs-review [--ledger PATH] list [--action approve|reject|...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ontology_mapping_co_scientist.review_ledger.ledger import (
    ReviewLedger,
    add_decision,
    load_ledger,
)

_DEFAULT_LEDGER = "mapping_review_ledger.yaml"

_APPROVE = "approve"
_REJECT = "reject"
_CHANGE_PREDICATE = "change_predicate"
_REQUEST_EVIDENCE = "request_more_evidence"
_CREATE_TERM = "create_new_ontology_term"

_DECISION_MENU = (
    "Decision: [1/a/match] approve  [2/p] change predicate  "
    "[3/e] need evidence  [4/r] reject  [5/n] new term  [6/s] skip  [7/q] quit"
)


# ---------------------------------------------------------------------------
# Interactive review helpers
# ---------------------------------------------------------------------------


def load_review_packets(review_file: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load review packets from a pipeline JSON or review queue JSON file.

    The preferred input is ``*_review_queue.json`` produced by ``omcs-run``.
    For compatibility, this also accepts orchestrator JSON files containing a
    top-level ``review_packets`` key and raw mappings JSON with ``mappings``.
    """
    review_path = Path(review_file)
    data = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Review file must contain a JSON object.")

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    packets = data.get("review_packets")
    if isinstance(packets, list):
        return metadata, [p for p in packets if isinstance(p, dict)]

    mappings = data.get("mappings") or data.get("hypotheses")
    if isinstance(mappings, list):
        return metadata, _packets_from_mappings(mappings)

    raise ValueError(
        "Review file must contain 'review_packets', 'mappings', or 'hypotheses'."
    )


def _packets_from_mappings(mappings: list[Any]) -> list[dict[str, Any]]:
    """Build minimal review packets from raw mapping dictionaries."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        source = mapping.get("source_entity") or {}
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("entity_id", ""))
        if not source_id:
            continue
        groups.setdefault(source_id, []).append(mapping)

    packets: list[dict[str, Any]] = []
    for source_id in sorted(groups):
        group = sorted(
            groups[source_id],
            key=lambda m: (
                int(m.get("rank") or 9999),
                -float(m.get("confidence") or 0.0),
                str(m.get("mapping_id", "")),
            ),
        )
        top = group[0]
        source = top.get("source_entity") or {}
        packets.append(
            {
                "source_entity_id": source_id,
                "source_entity_label": source.get("label", source_id),
                "top_mapping": top,
                "alternative_mappings": group[1:],
                "suggested_action": None,
                "all_warnings": top.get("warnings", []),
            }
        )
    return packets


def approval_blockers(packet: dict[str, Any]) -> list[str]:
    """Return reasons that prevent approval in strict chat mode."""
    top = packet.get("top_mapping") or {}
    if not isinstance(top, dict):
        return ["No top mapping is available for this source entity."]

    blockers: list[str] = []
    validation_status = str(top.get("validation_status", "")).lower()
    if validation_status == "failed":
        blockers.append("automated validation failed")

    if str(top.get("predicate", "")) == "custom:noMapping":
        blockers.append("the top hypothesis is a no-mapping result")

    for flag in top.get("_adv_flags", []) or []:
        if isinstance(flag, dict) and flag.get("severity") == "high":
            blockers.append(f"high-severity adversarial flag: {flag.get('flag_type')}")

    for warning in packet.get("all_warnings", []) or []:
        warning_text = str(warning)
        if warning_text.startswith("[HIGH]"):
            blockers.append(warning_text)

    return blockers


def action_from_choice(choice: str, packet: dict[str, Any]) -> tuple[str | None, str | None]:
    """Translate a chat menu choice to a ledger action.

    Returns ``(action, error)``.  ``action`` is ``None`` for skip/quit or for
    invalid choices.  Approval is deliberately blocked when the review packet
    contains strict-mode blockers.
    """
    normalized = choice.strip().lower()
    if normalized in {"h", "help", "menu", "?"}:
        return None, _DECISION_MENU
    if normalized in {"1", "a", "approve", "match", "yes", "y"}:
        blockers = approval_blockers(packet)
        if blockers:
            return (
                None,
                "Approval is blocked. Use 2/p to soften the predicate, "
                "3/e to request evidence, or 4/r to reject.",
            )
        return _APPROVE, None
    if normalized in {"4", "r", "reject", "no"}:
        return _REJECT, None
    if normalized in {
        "3",
        "e",
        "evidence",
        "more",
        "unsure",
        "request-evidence",
        "request_more_evidence",
    }:
        return _REQUEST_EVIDENCE, None
    if normalized in {
        "2",
        "p",
        "predicate",
        "close",
        "closematch",
        "change-predicate",
        "change_predicate",
    }:
        return _CHANGE_PREDICATE, None
    if normalized in {"5", "n", "new-term", "new", "create-term"}:
        return _CREATE_TERM, None
    if normalized in {"6", "s", "skip"}:
        return None, None
    if normalized in {"7", "q", "quit", "exit"}:
        return "quit", None
    return None, "Unknown choice. Type 'help' to show valid decisions."


def _top_mapping(packet: dict[str, Any]) -> dict[str, Any]:
    top = packet.get("top_mapping")
    return top if isinstance(top, dict) else {}


def _target_label(mapping: dict[str, Any]) -> str:
    target = mapping.get("target_entity") or {}
    if not isinstance(target, dict):
        return "(no target)"
    term_id = target.get("term_id", "(no term id)")
    label = target.get("label", "")
    return f"{term_id} - {label}".strip()


def _shorten(text: Any, limit: int = 140) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _unique_texts(items: list[Any], limit: int) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in items:
        text = _shorten(item)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
        if len(values) >= limit:
            break
    return values


def _print_packet(packet: dict[str, Any], index: int, total: int) -> None:
    top = _top_mapping(packet)
    source_id = packet.get("source_entity_id", "")
    source_label = packet.get("source_entity_label", source_id)
    suggested = packet.get("suggested_action") or {}
    if not isinstance(suggested, dict):
        suggested = {}

    print()
    print("=" * 72)
    print(f"Review {index}/{total} | {source_label} | {source_id}")
    print("=" * 72)
    print(
        "Top: "
        f"{_target_label(top)} | {top.get('predicate', '(unknown)')} | "
        f"conf={float(top.get('confidence') or 0.0):.3f} | "
        f"validation={top.get('validation_status', '(unknown)')}"
    )
    print(f"ID : {top.get('mapping_id', '(none)')}")
    if suggested:
        print(
            "Suggested: "
            f"{suggested.get('action')} - {_shorten(suggested.get('reason', ''), 150)}"
        )

    blockers = approval_blockers(packet)
    if blockers:
        print("Gate: BLOCKED for approval")
        for blocker in _unique_texts(blockers, 3):
            print(f"  - {blocker}")
    else:
        print("Gate: approval allowed after human check")

    evidence = top.get("evidence") or []
    if evidence:
        print("Evidence:")
        for item in evidence[:3]:
            if isinstance(item, dict):
                score = item.get("score")
                score_text = f" ({float(score):.3f})" if isinstance(score, (int, float)) else ""
                print(
                    f"  - {item.get('evidence_type', 'evidence')}{score_text}: "
                    f"{_shorten(item.get('description', ''))}"
                )

    warnings = packet.get("all_warnings") or []
    if warnings:
        print("Key issues:")
        for warning in _unique_texts(warnings, 4):
            print(f"  - {warning}")

    alternatives = packet.get("alternative_mappings") or []
    if alternatives:
        print("Alternatives:")
        for alt in alternatives[:2]:
            if isinstance(alt, dict):
                print(
                    "  - "
                    f"{_target_label(alt)} "
                    f"({alt.get('predicate')}, conf={float(alt.get('confidence') or 0.0):.3f})"
                )
    print(_DECISION_MENU)


def _cmd_chat(args: argparse.Namespace) -> None:
    """Run an interactive HITL review session over a review queue."""
    metadata, packets = load_review_packets(args.review_file)
    if not packets:
        print("No review packets found.")
        return

    ledger = load_ledger(args.ledger)
    reviewed_sources = {
        d.source_entity_id
        for d in ledger.decisions
        if d.action in {_APPROVE, _REJECT, _CHANGE_PREDICATE, _CREATE_TERM}
    }
    pending_packets = [
        packet for packet in packets
        if str(packet.get("source_entity_id", "")) not in reviewed_sources
    ]

    print("=" * 72)
    print("Ontology Mapping Co-Scientist HITL Review")
    print("=" * 72)
    print(f"Review file : {Path(args.review_file).resolve()}")
    print(f"Ledger      : {Path(args.ledger).resolve()}")
    print(f"Run ID      : {metadata.get('pipeline_run_id', '(unknown)')}")
    print(f"Queue       : {len(pending_packets)} pending / {len(packets)} total")
    print()
    print("Use the numbered decision menu shown under each mapping.")
    print("Approval stays blocked when strict review found high-severity issues.")

    recorded = 0
    for idx, packet in enumerate(pending_packets, start=1):
        _print_packet(packet, idx, len(pending_packets))
        top = _top_mapping(packet)
        mapping_id = str(top.get("mapping_id", ""))
        source_id = str(packet.get("source_entity_id", ""))
        if not mapping_id or not source_id:
            print("Skipping packet with missing mapping_id or source_entity_id.")
            continue

        while True:
            choice = input("Decision [help]> ")
            action, error = action_from_choice(choice, packet)
            if error:
                print(error)
                continue
            if action is None:
                print("Skipped.")
                break
            if action == "quit":
                print(f"Recorded {recorded} decision(s).")
                return

            predicate_override = None
            if action == _CHANGE_PREDICATE:
                predicate_override = input(
                    "Replacement predicate [skos:closeMatch]> "
                ).strip() or "skos:closeMatch"

            note = input("Reviewer note> ").strip()
            add_decision(
                ledger_path=args.ledger,
                mapping_id=mapping_id,
                source_entity_id=source_id,
                action=action,
                reviewer=args.reviewer,
                note=note,
                predicate_override=predicate_override,
                pipeline_run_id=metadata.get("pipeline_run_id"),
            )
            recorded += 1
            print(f"Recorded {action} for {mapping_id}.")
            break

    print(f"Review session complete. Recorded {recorded} decision(s).")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_accept(args: argparse.Namespace) -> None:
    """Record an 'approve' decision."""
    decision = add_decision(
        ledger_path=args.ledger,
        mapping_id=args.mapping_id,
        source_entity_id=args.source,
        action="approve",
        reviewer=args.reviewer,
        note=args.note,
        pipeline_run_id=args.run_id,
    )
    print(f"Recorded APPROVE for mapping '{decision.mapping_id}' "
          f"(source: {decision.source_entity_id}) by {decision.reviewer} "
          f"at {decision.timestamp}")


def _cmd_reject(args: argparse.Namespace) -> None:
    """Record a 'reject' decision."""
    decision = add_decision(
        ledger_path=args.ledger,
        mapping_id=args.mapping_id,
        source_entity_id=args.source,
        action="reject",
        reviewer=args.reviewer,
        note=args.note,
        pipeline_run_id=args.run_id,
    )
    print(f"Recorded REJECT for mapping '{decision.mapping_id}' "
          f"(source: {decision.source_entity_id}) by {decision.reviewer} "
          f"at {decision.timestamp}")


def _cmd_change_predicate(args: argparse.Namespace) -> None:
    """Record a 'change_predicate' decision."""
    decision = add_decision(
        ledger_path=args.ledger,
        mapping_id=args.mapping_id,
        source_entity_id=args.source,
        action="change_predicate",
        reviewer=args.reviewer,
        note=args.note,
        predicate_override=args.predicate,
        pipeline_run_id=args.run_id,
    )
    print(f"Recorded CHANGE_PREDICATE -> '{decision.predicate_override}' "
          f"for mapping '{decision.mapping_id}' "
          f"(source: {decision.source_entity_id}) by {decision.reviewer} "
          f"at {decision.timestamp}")


def _cmd_request_evidence(args: argparse.Namespace) -> None:
    """Record a 'request_more_evidence' decision."""
    decision = add_decision(
        ledger_path=args.ledger,
        mapping_id=args.mapping_id,
        source_entity_id=args.source,
        action="request_more_evidence",
        reviewer=args.reviewer,
        note=args.note,
        pipeline_run_id=args.run_id,
    )
    print(f"Recorded REQUEST_MORE_EVIDENCE for mapping '{decision.mapping_id}' "
          f"(source: {decision.source_entity_id}) by {decision.reviewer} "
          f"at {decision.timestamp}")


def _cmd_status(args: argparse.Namespace) -> None:
    """Print a summary of the ledger."""
    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        print(f"No ledger found at: {ledger_path}")
        return

    ledger: ReviewLedger = load_ledger(ledger_path)

    action_counts: dict[str, int] = {}
    for d in ledger.decisions:
        action_counts[d.action] = action_counts.get(d.action, 0) + 1

    print("=" * 50)
    print("  Mapping Review Ledger Status")
    print("=" * 50)
    print(f"  Ledger file   : {ledger_path.resolve()}")
    print(f"  Version       : {ledger.ledger_version}")
    print(f"  Last updated  : {ledger.last_updated or '(never)'}")
    print(f"  Total decisions: {len(ledger.decisions)}")
    print()
    print("  Decisions by action:")
    if action_counts:
        for action, count in sorted(action_counts.items()):
            print(f"    {action:<30} : {count}")
    else:
        print("    (none)")
    print("=" * 50)


def _cmd_list(args: argparse.Namespace) -> None:
    """Print all decisions as a formatted table."""
    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        print(f"No ledger found at: {ledger_path}")
        return

    ledger: ReviewLedger = load_ledger(ledger_path)
    decisions = ledger.decisions

    # Filter by action if requested
    if args.action:
        decisions = [d for d in decisions if d.action == args.action]

    if not decisions:
        print("No decisions found.")
        return

    # Column widths
    col_widths = {
        "mapping_id": max(10, max(len(d.mapping_id) for d in decisions)),
        "source": max(10, max(len(d.source_entity_id) for d in decisions)),
        "action": max(6, max(len(d.action) for d in decisions)),
        "reviewer": max(8, max(len(d.reviewer) for d in decisions)),
        "timestamp": 24,
        "note": 30,
    }

    header = (
        f"{'mapping_id':<{col_widths['mapping_id']}}  "
        f"{'source':<{col_widths['source']}}  "
        f"{'action':<{col_widths['action']}}  "
        f"{'reviewer':<{col_widths['reviewer']}}  "
        f"{'timestamp':<{col_widths['timestamp']}}  "
        f"{'note':<{col_widths['note']}}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for d in decisions:
        note_display = (d.note[:27] + "...") if len(d.note) > 30 else d.note
        print(
            f"{d.mapping_id:<{col_widths['mapping_id']}}  "
            f"{d.source_entity_id:<{col_widths['source']}}  "
            f"{d.action:<{col_widths['action']}}  "
            f"{d.reviewer:<{col_widths['reviewer']}}  "
            f"{d.timestamp:<{col_widths['timestamp']}}  "
            f"{note_display:<{col_widths['note']}}"
        )
    print(sep)
    print(f"Total: {len(decisions)} decision(s).")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omcs-review",
        description="Record and manage human review decisions for ontology mappings.",
    )

    # Global option
    parser.add_argument(
        "--ledger",
        default=_DEFAULT_LEDGER,
        metavar="PATH",
        help=f"Path to the review ledger YAML file (default: {_DEFAULT_LEDGER}).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared arguments for decision subcommands
    def _add_decision_args(sub: argparse.ArgumentParser, *, require_source: bool = True) -> None:
        sub.add_argument("mapping_id", help="The mapping hypothesis ID to review.")
        sub.add_argument(
            "--source",
            required=require_source,
            metavar="ENTITY_ID",
            help="Source entity ID associated with the mapping.",
        )
        sub.add_argument(
            "--reviewer",
            default="unknown",
            metavar="NAME",
            help="Name or identifier of the reviewer (default: unknown).",
        )
        sub.add_argument(
            "--note",
            default="",
            metavar="TEXT",
            help="Optional free-text justification.",
        )
        sub.add_argument(
            "--run-id",
            default=None,
            metavar="ID",
            help="Optional pipeline run ID that produced the hypothesis.",
        )

    # accept
    sub_accept = subparsers.add_parser(
        "accept",
        help="Approve a mapping hypothesis.",
    )
    _add_decision_args(sub_accept)

    # reject
    sub_reject = subparsers.add_parser(
        "reject",
        help="Reject a mapping hypothesis.",
    )
    _add_decision_args(sub_reject)

    # change-predicate
    sub_change = subparsers.add_parser(
        "change-predicate",
        help="Accept the mapping target but override the predicate.",
    )
    _add_decision_args(sub_change)
    sub_change.add_argument(
        "--predicate",
        required=True,
        metavar="PRED",
        help="The replacement predicate, e.g. 'skos:closeMatch'.",
    )

    # request-evidence
    sub_evidence = subparsers.add_parser(
        "request-evidence",
        help="Request more evidence before deciding on a mapping.",
    )
    _add_decision_args(sub_evidence)

    # status
    sub_status = subparsers.add_parser(
        "status",
        help="Print a summary of the review ledger.",
    )
    # status inherits --ledger from parent

    # list
    sub_list = subparsers.add_parser(
        "list",
        help="List all decisions in the review ledger.",
    )
    sub_list.add_argument(
        "--action",
        default=None,
        metavar="ACTION",
        help="Filter decisions by action (e.g. approve, reject).",
    )

    # chat
    sub_chat = subparsers.add_parser(
        "chat",
        help="Interactively review a pipeline review queue and write ledger decisions.",
    )
    sub_chat.add_argument(
        "review_file",
        metavar="PATH",
        help="Path to *_review_queue.json, hypotheses.json, or mappings JSON.",
    )
    sub_chat.add_argument(
        "--reviewer",
        default="unknown",
        metavar="NAME",
        help="Name or identifier of the reviewer (default: unknown).",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for omcs-review."""
    parser = _build_parser()
    args = parser.parse_args()

    # Route to the appropriate handler
    handlers = {
        "accept": _cmd_accept,
        "reject": _cmd_reject,
        "change-predicate": _cmd_change_predicate,
        "request-evidence": _cmd_request_evidence,
        "status": _cmd_status,
        "list": _cmd_list,
        "chat": _cmd_chat,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
