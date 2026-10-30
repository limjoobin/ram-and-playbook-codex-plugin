#!/usr/bin/env python3
"""Plan or empty all entries from the exact RAM test store in editor.env."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
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
        help="delete all long-term memories and sessions; omission is read-only",
    )
    parser.add_argument(
        "--confirm-empty-store",
        action="store_true",
        help="required with --apply after reviewing the plan target hash and counts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.apply and not args.confirm_empty_store:
        _parser().error("--apply requires --confirm-empty-store")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(SERVER_ROOT))
    from admin_bootstrap.reset_store import StoreResetError, apply_reset, plan_reset
    from ram_plugin.credentials import load_credential_file
    from ram_plugin.ram import RAMClient

    try:
        config = load_credential_file(args.config)
        ram = RAMClient(config)
        result = apply_reset(config, ram) if args.apply else plan_reset(config, ram)
    except StoreResetError as error:
        result = {"ok": False, "status": "failed", "message": str(error)}
    except Exception:
        result = {
            "ok": False,
            "status": "failed",
            "message": "RAM reset failed. Check the private configuration and service availability before retrying.",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
