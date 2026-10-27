#!/usr/bin/env python3
"""Run the explicit administrator context bootstrap harness."""

from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from admin_bootstrap.harness import main

    raise SystemExit(main())
