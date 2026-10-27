#!/usr/bin/env python3
"""Thin Codex hook adapter for private RAM capture and lifecycle-update guidance."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "server"))

from ram_plugin.credentials import load_credential_file
from ram_plugin.promotion import HookCapture, PromotionLedger
from ram_plugin.ram import RAMClient


def _config_path(environment: Mapping[str, str]) -> Path:
    configured = (environment.get("REDIS_SHARED_MEMORY_CONFIG") or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".config" / "redis-shared-memory" / "editor.env"
    )


def _safe_output(event_name: str, *, unavailable: bool = False) -> dict[str, Any]:
    if event_name == "UserPromptSubmit":
        result: dict[str, Any] = {"continue": True}
        if unavailable:
            result["systemMessage"] = "Private RAM capture is unavailable; review the plugin configuration."
        return result
    if event_name == "Stop":
        result = {"continue": True}
        if unavailable:
            result["systemMessage"] = "Private RAM capture is unavailable; no shared memory was written."
        return result
    if event_name == "PostToolUse" and unavailable:
        return {"systemMessage": "Private RAM capture is unavailable; no shared memory was written."}
    return {}


def handle(payload: Any, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if environment is None else environment
    event_name = payload.get("hook_event_name") if isinstance(payload, dict) else ""
    if not isinstance(payload, dict):
        return _safe_output(str(event_name), unavailable=True)
    try:
        config = load_credential_file(_config_path(values))
        ledger = PromotionLedger.from_environment(values)
        timeout_ms = 800 if event_name == "SessionEnd" else 1_500
        return HookCapture(config, RAMClient(config, timeout_ms=timeout_ms), ledger, timeout_ms).process(
            payload
        )
    except Exception:
        return _safe_output(str(event_name), unavailable=True)


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(262_145)
        if len(raw) > 262_144:
            payload: Any = None
        else:
            payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        payload = None
    event_name = payload.get("hook_event_name") if isinstance(payload, dict) else ""
    result = handle(payload)
    if event_name in {"UserPromptSubmit", "PostToolUse", "Stop"} or result:
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()

