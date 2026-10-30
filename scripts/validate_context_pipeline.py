#!/usr/bin/env python3
"""Validate the complete context model without connecting to RAM or Playbook."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from admin_bootstrap.bundle import Bundle, BundleError
    from admin_bootstrap.context_pipeline import verify_context_pipeline

    try:
        bundle = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")
        result = verify_context_pipeline(bundle)
    except BundleError as error:
        result = {"status": "failed", "passed": False, "message": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
