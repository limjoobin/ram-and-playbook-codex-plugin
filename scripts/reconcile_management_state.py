#!/usr/bin/env python3
"""Rebuild management-state projections after RAM MemoryETL extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config" / "redis-shared-memory" / "editor.env",
        help="private editor.env path",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="upsert changed derived projections; omission is a read-only plan",
    )
    parser.add_argument(
        "--quiet-no-changes",
        action="store_true",
        help="print nothing when an applied run finds no projection changes",
    )
    parser.add_argument(
        "--wait-for-candidate",
        help="wait until the promoted candidate's extracted observation is visible",
    )
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.wait_for_candidate and not re.fullmatch(
        r"candidate-[a-f0-9]{48}", args.wait_for_candidate
    ):
        _parser().error("--wait-for-candidate must be an ID returned by the plugin")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(SERVER_ROOT))
    from admin_bootstrap.bundle import Bundle
    from ram_plugin.credentials import load_credential_file
    from ram_plugin.ram import RAMClient
    from reconciliation.job import ReconciliationError, ReconciliationJob

    try:
        config = load_credential_file(args.config)
        bundle = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")
        result = ReconciliationJob(config, RAMClient(config), bundle).run(
            apply=args.apply,
            wait_for_candidate=args.wait_for_candidate,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except ReconciliationError as error:
        result = {"ok": False, "status": "failed", "message": str(error)}
    except Exception:
        result = {
            "ok": False,
            "status": "failed",
            "message": "Reconciliation failed. Check the private configuration and RAM availability.",
        }
    if not args.quiet_no_changes or result.get("status") != "no_changes":
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
