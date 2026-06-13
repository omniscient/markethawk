#!/usr/bin/env python3
"""factory_core CLI — thin dispatch layer for shell adapters."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _board_move(args):
    from factory_core.board import set_board_status
    set_board_status(args.issue, args.status)


def _deconflict(args):
    from factory_core.deconflict import resolve_merge_conflicts
    clone_dir = os.environ.get("CLONE_DIR", "/workspace/markethawk")
    artifacts_dir = os.environ.get("ARTIFACTS_DIR", f"/tmp/artifacts/{args.issue}")
    if args.repo:
        owner, _, repo = args.repo.partition("/")
    else:
        owner = os.environ.get("FACTORY_OWNER", "omniscient")
        repo = os.environ.get("FACTORY_REPO", "markethawk")
    rc = resolve_merge_conflicts(
        issue_num=args.issue,
        clone_dir=clone_dir,
        owner=owner,
        repo=repo,
        artifacts_dir=artifacts_dir,
        ai_tier=not args.no_ai_tier,
    )
    sys.exit(rc)


def _breaker_get(args):
    from factory_core.breaker import get_retry_count
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    print(get_retry_count(args.key, state_file))


def _breaker_incr(args):
    from factory_core.breaker import increment_retry
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    print(increment_retry(args.key, state_file))


def _breaker_reset(args):
    from factory_core.breaker import reset_retry
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    reset_retry(args.key, state_file)


def _breaker_trip(args):
    from factory_core.breaker import trip_to_blocked
    state_file = Path(os.environ.get("STATE_FILE",
                                     "/var/lib/dark-factory/scheduler-state.json"))
    trip_to_blocked(
        issue_num=args.issue,
        phase=args.phase,
        reason=args.reason,
        state_file=state_file,
    )


def _run_record(args):
    sys.argv = ["run_record"] + args.run_record_args
    from factory_core import run_record
    run_record.main()


def main():
    parser = argparse.ArgumentParser(prog="factory-core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bm = sub.add_parser("board-move")
    bm.add_argument("--issue", type=int, required=True)
    bm.add_argument("--status", required=True)
    bm.set_defaults(func=_board_move)

    dc = sub.add_parser("deconflict")
    dc.add_argument("--issue", type=int, required=True)
    dc.add_argument("--repo", default="")
    dc.add_argument("--no-ai-tier", action="store_true")
    dc.set_defaults(func=_deconflict)

    bg = sub.add_parser("breaker-get")
    bg.add_argument("--key", required=True)
    bg.set_defaults(func=_breaker_get)

    bi = sub.add_parser("breaker-incr")
    bi.add_argument("--key", required=True)
    bi.set_defaults(func=_breaker_incr)

    br = sub.add_parser("breaker-reset")
    br.add_argument("--key", required=True)
    br.set_defaults(func=_breaker_reset)

    bt = sub.add_parser("breaker-trip")
    bt.add_argument("--issue", type=int, required=True)
    bt.add_argument("--phase", required=True)
    bt.add_argument("--reason", required=True)
    bt.set_defaults(func=_breaker_trip)

    rr = sub.add_parser("run-record")
    rr.add_argument("run_record_args", nargs=argparse.REMAINDER)
    rr.set_defaults(func=_run_record)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
