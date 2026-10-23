#!/usr/bin/env python3
"""Entry point for the local Redis Shared Memory MCP server."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ram_plugin.mcp_server import run


if __name__ == "__main__":
    try:
        run()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    except Exception:
        sys.stderr.write("Redis Shared Memory could not start. Check the local plugin installation.\n")
        raise SystemExit(1)
