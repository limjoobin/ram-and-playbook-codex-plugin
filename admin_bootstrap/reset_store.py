"""Plan and verify an explicit RAM test-store entry reset."""

from __future__ import annotations

import hashlib
from typing import Any


class StoreResetError(RuntimeError):
    """A sanitized destructive reset failure."""


DELETE_BATCH_SIZE = 20


def _items(payload: dict[str, Any], *names: str) -> list[Any]:
    for name in names:
        value = payload.get(name)
        if value is not None:
            if not isinstance(value, list):
                raise StoreResetError("RAM returned an invalid reset inventory")
            return value
    return []


def _next_token(payload: dict[str, Any]) -> str | None:
    value = payload.get("nextPageToken", payload.get("next_page_token"))
    return value if isinstance(value, str) and value else None


def _search_ids(ram: Any, scope_filter: dict[str, Any]) -> set[str]:
    token: str | None = None
    seen_tokens: set[str] = set()
    ids: set[str] = set()
    while True:
        request: dict[str, Any] = {
            "filter": scope_filter,
            "filterOp": "all",
            "limit": 100,
        }
        if token:
            request["pageToken"] = token
        page = ram.search(request, timeout_ms=30_000)
        for item in _items(page, "items", "memories"):
            memory_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(memory_id, str) or not memory_id:
                raise StoreResetError("RAM returned a memory without an identity")
            ids.add(memory_id)
        token = _next_token(page)
        if token is None:
            return ids
        if token in seen_tokens:
            raise StoreResetError("RAM repeated a long-term-memory page token")
        seen_tokens.add(token)


def _long_term_ids(config: Any, ram: Any) -> list[str]:
    # Search requires a structured filter, and RAM namespaces are first-class
    # resources. Unnamespaced records plus every visible namespace covers the store.
    ids = _search_ids(ram, {"unnamespaced": True})
    for namespace_id in ram.namespace_ids():
        ids |= _search_ids(ram, {"namespaceId": {"eq": namespace_id}})
    return sorted(ids)


def _session_ids(ram: Any) -> list[str]:
    token: str | None = None
    seen_tokens: set[str] = set()
    ids: list[str] = []
    while True:
        page = ram.list_sessions(token, timeout_ms=30_000)
        for item in _items(page, "items", "sessions"):
            session_id = item.get("sessionId") if isinstance(item, dict) else item
            if not isinstance(session_id, str) or not session_id:
                raise StoreResetError("RAM returned a session without an identity")
            ids.append(session_id)
        token = _next_token(page)
        if token is None:
            return ids
        if token in seen_tokens:
            raise StoreResetError("RAM repeated a session page token")
        seen_tokens.add(token)


def plan_reset(config: Any, ram: Any) -> dict[str, Any]:
    """Inventory the exact configured store without returning data or identifiers."""

    memories = _long_term_ids(config, ram)
    sessions = _session_ids(ram)
    target = hashlib.sha256(
        f"{config.endpoint}\0{config.store_id}".encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "status": "planned",
        "targetSha256": target,
        "longTermMemoryCount": len(memories),
        "sessionCount": len(sessions),
        "preserves": [
            "store",
            "custom-memory-types",
            "document-extractors",
            "namespaces",
        ],
        "deletes": ["long-term-memories", "session-events"],
    }


def apply_reset(config: Any, ram: Any) -> dict[str, Any]:
    """Delete all current entries, then prove both visible entry lanes are empty."""

    before = plan_reset(config, ram)
    memory_ids = _long_term_ids(config, ram)
    deleted_memories = 0
    for offset in range(0, len(memory_ids), DELETE_BATCH_SIZE):
        batch = memory_ids[offset : offset + DELETE_BATCH_SIZE]
        response = ram.bulk_delete_long_term_memories(batch, timeout_ms=120_000)
        errors = response.get("errors", [])
        deleted = response.get("deleted", [])
        if not isinstance(errors, list) or errors:
            raise StoreResetError("RAM failed to delete one or more long-term memories")
        if not isinstance(deleted, list) or set(deleted) != set(batch):
            raise StoreResetError("RAM did not confirm the requested memory deletions")
        deleted_memories += len(deleted)

    sessions = _session_ids(ram)
    for session_id in sessions:
        ram.delete_session(session_id, timeout_ms=30_000)

    after = plan_reset(config, ram)
    if after["longTermMemoryCount"] or after["sessionCount"]:
        raise StoreResetError("RAM store reset could not be verified as empty")
    return {
        "ok": True,
        "status": "emptied",
        "targetSha256": before["targetSha256"],
        "deletedLongTermMemoryCount": deleted_memories,
        "deletedSessionCount": len(sessions),
        "verifiedLongTermMemoryCount": after["longTermMemoryCount"],
        "verifiedSessionCount": after["sessionCount"],
        "preserved": before["preserves"],
    }
