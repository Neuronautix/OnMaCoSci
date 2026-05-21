"""
CLI for recording human review decisions into the mapping review ledger.

Usage:
  omcs-review accept <mapping_id> --source <entity_id> [--reviewer NAME] [--note TEXT] [--ledger PATH]
  omcs-review reject <mapping_id> --source <entity_id> [--reviewer NAME] [--note TEXT] [--ledger PATH]
  omcs-review change-predicate <mapping_id> --source <entity_id> --predicate skos:closeMatch [--note TEXT]
  omcs-review request-evidence <mapping_id> --source <entity_id> [--note TEXT]
  omcs-review status [--ledger PATH]
  omcs-review list [--ledger PATH] [--action approve|reject|...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ontology_mapping_co_scientist.review_ledger.ledger import (
    ReviewLedger,
    add_decision,
    get_decisions_by_source,
    load_ledger,
)

_DEFAULT_LEDGER = "mapping_review_ledger.yaml"


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
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
