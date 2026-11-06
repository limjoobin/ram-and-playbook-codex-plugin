"""Private session capture and confirmed personal-to-shared promotion policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping, Protocol

from .config import Config, PluginError, SLUG, public_error
from .management import LIFECYCLE_STATUSES, STATE_KINDS, _attributes


OBSERVATION_SCHEMA = "organizational-state-v3"
PROMOTION_CONTRACT = "personal-to-shared-promotion-v1"
EVIDENCE_ROLES = {"creates", "supports", "updates", "contradicts", "resolves", "supersedes"}
HOOK_EVENTS = {"UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"}
PRIVATE_LEDGER_NAME = "promotion-events.jsonl"
MAX_LEDGER_BYTES = 8_000_000
MAX_EVENT_BYTES = 32_000
MAX_PROMPT = 4_000
MAX_ASSISTANT = 8_000
MAX_TOOL_PREVIEW = 2_000

_SHARE_INTENT = re.compile(
    r"\b(?:remember|save|share|publish)\b[\s\S]{0,80}"
    r"\b(?:team|shared|everyone|organisation|organization|company|memory)\b",
    re.IGNORECASE,
)
_COMPLETION = re.compile(
    r"\b(?:completed|finished|done|implemented|fixed|created|updated|delivered|decided|approved|resolved|closed|cancelled|canceled)\b",
    re.IGNORECASE,
)
_STATE_UPDATE_INTENT = re.compile(
    r"\b(?:i|we|he|she|they|andrew|laura|david|craig)\b[\s\S]{0,160}"
    r"\b(?:completed|finished|done|implemented|delivered|resolved|closed|cancelled|canceled|blocked|started)\b"
    r"|\b(?:completed|finished|done|resolved|closed|cancelled|canceled|blocked)\b[\s\S]{0,160}"
    r"\b(?:task|action|item|work|report|analysis|design|minutes|evaluation)\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|password|secret|token)\b\s*[:=]\s*[^\s,;]+"
)
_SECRET_VALUE = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}"
)


class PromotionRAM(Protocol):
    def add_session_event(
        self,
        *,
        session_id: str,
        actor_id: str,
        namespace: str,
        role: str,
        text: str,
        created_at: str,
        metadata: dict[str, Any],
        idempotency_key: str,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]: ...

    def create(self, memories: list[dict[str, Any]]) -> dict[str, Any]: ...

    def get(self, memory_id: str) -> dict[str, Any]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any, length: int = 48) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:length]


def _bounded_text(value: Any, maximum: int) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _SECRET_VALUE.sub("[REDACTED]", text)
    return text[:maximum]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if re.search(r"(?i)(authorization|api[_-]?key|password|secret|token)", str(key))
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        return _bounded_text(value, MAX_TOOL_PREVIEW)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:200]


def _session_id(prefix: str, participant: str, source_session_id: str) -> str:
    return f"{prefix}-{_digest([participant, source_session_id], 40)}"


def _event_id(payload: Mapping[str, Any]) -> str:
    identity = {
        "event": payload.get("hook_event_name"),
        "session": payload.get("session_id"),
        "turn": payload.get("turn_id"),
        "tool_use": payload.get("tool_use_id"),
        "prompt": payload.get("prompt"),
        "last_assistant_message": payload.get("last_assistant_message"),
        "reason": payload.get("reason"),
    }
    return f"hook-{_digest(identity)}"


def _ram_event_id(result: Mapping[str, Any]) -> str | None:
    event = result.get("event")
    if not isinstance(event, dict):
        return None
    value = event.get("eventId", event.get("event_id"))
    return value if isinstance(value, str) and value else None


def _tool_completed(response: Any) -> bool:
    if isinstance(response, dict):
        if response.get("isError") is True or response.get("ok") is False:
            return False
        status = response.get("status")
        if isinstance(status, str) and status.lower() in {"failed", "error", "cancelled"}:
            return False
        exit_code = response.get("exit_code", response.get("exitCode"))
        if isinstance(exit_code, int):
            return exit_code == 0
    text = str(response).lower()
    return not any(marker in text for marker in ("status: failed", '"iserror":true', "exit code 1"))


def _artifact_refs(tool_input: Any) -> list[str]:
    refs: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if len(refs) >= 8:
            return
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                visit(nested, str(nested_key))
        elif isinstance(value, list):
            for nested in value[:20]:
                visit(nested, key)
        elif isinstance(value, str) and re.search(r"(?i)(path|file|url|uri|artifact|document)", key):
            clean = _bounded_text(value, 512)
            if clean and clean not in refs:
                refs.append(clean)

    visit(tool_input)
    return refs


class PromotionLedger:
    """Append-only private ledger; duplicate hook deliveries fold by event ID."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "PromotionLedger":
        values = os.environ if environment is None else environment
        root = (values.get("PLUGIN_DATA") or "").strip()
        base = Path(root).expanduser() if root else Path.home() / ".local" / "share" / "redis-shared-memory"
        return cls(base / "promotion" / PRIVATE_LEDGER_NAME)

    def _prepare_parent(self) -> None:
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise PluginError("promotion_store_invalid", "The private promotion store is not a safe directory.")
        try:
            os.chmod(parent, 0o700)
        except OSError as error:
            raise PluginError("promotion_store_invalid", "The private promotion store permissions are invalid.") from error

    def append(self, kind: str, payload: Mapping[str, Any], *, event_id: str | None = None) -> str:
        self._prepare_parent()
        identifier = event_id or f"ledger-{_digest([kind, payload])}"
        record = {
            "schema": "promotion-ledger-v1",
            "event_id": identifier,
            "kind": kind,
            "recorded_at": _now(),
            "payload": _redact(dict(payload)),
        }
        encoded = (_canonical(record) + "\n").encode("utf-8")
        if len(encoded) > MAX_EVENT_BYTES:
            raise PluginError("promotion_event_too_large", "The private promotion event exceeds its safe size limit.")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
            os.chmod(self.path, 0o600)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise PluginError("promotion_store_unavailable", "The private promotion store could not be updated.") from error
        return identifier

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise PluginError("promotion_store_invalid", "The private promotion ledger must be a regular file.")
        if self.path.stat().st_size > MAX_LEDGER_BYTES:
            raise PluginError("promotion_store_too_large", "The private promotion ledger requires operator review.")
        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if len(line) > MAX_EVENT_BYTES:
                        continue
                    try:
                        record = json.loads(line)
                    except (UnicodeError, json.JSONDecodeError):
                        continue
                    identifier = record.get("event_id") if isinstance(record, dict) else None
                    if not isinstance(identifier, str) or identifier in seen:
                        continue
                    if record.get("schema") != "promotion-ledger-v1" or not isinstance(record.get("payload"), dict):
                        continue
                    seen.add(identifier)
                    records.append(record)
        except OSError as error:
            raise PluginError("promotion_store_unavailable", "The private promotion store could not be read.") from error
        return records

    def session_state(self, session_id: str, turn_id: str | None = None) -> dict[str, Any]:
        state: dict[str, Any] = {
            "share_intent": False,
            "prompt": "",
            "last_assistant_message": "",
            "evidence": [],
            "private_event_ids": [],
        }
        for event in self.events():
            payload = event["payload"]
            if payload.get("session_id") != session_id:
                continue
            if turn_id and payload.get("turn_id") not in {None, "", turn_id}:
                continue
            kind = event.get("kind")
            if kind == "hook_prompt":
                state["share_intent"] = state["share_intent"] or bool(payload.get("share_intent"))
                state["prompt"] = payload.get("prompt") or state["prompt"]
            elif kind == "hook_tool":
                state["evidence"].append(payload)
            elif kind == "hook_stop":
                state["last_assistant_message"] = payload.get("last_assistant_message") or state["last_assistant_message"]
            elif kind == "ram_private_event":
                ram_event_id = payload.get("ram_event_id")
                if isinstance(ram_event_id, str) and ram_event_id not in state["private_event_ids"]:
                    state["private_event_ids"].append(ram_event_id)
        state["evidence"] = state["evidence"][-8:]
        return state

    def prompt_source(self, evidence_text: str) -> dict[str, Any] | None:
        """Return the newest exact private prompt and its RAM provenance."""

        expected = _bounded_text(evidence_text, MAX_PROMPT).strip()
        for event in reversed(self.events()):
            if event.get("kind") != "hook_prompt":
                continue
            payload = event["payload"]
            captured = payload.get("prompt")
            if not isinstance(captured, str) or captured.strip() != expected:
                continue
            session_id = payload.get("session_id")
            turn_id = payload.get("turn_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            state = self.session_state(session_id, turn_id if isinstance(turn_id, str) else None)
            return {
                "hook_event_id": event.get("event_id"),
                "session_id": session_id,
                "turn_id": turn_id if isinstance(turn_id, str) else "",
                "prompt": captured,
                "captured_at": event.get("recorded_at"),
                "source_private_event_ids": state["private_event_ids"],
            }
        return None

    def candidates(self) -> dict[str, dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        private_events: list[tuple[Any, Any, str]] = []
        for event in self.events():
            payload = event["payload"]
            if event.get("kind") == "ram_private_event" and isinstance(payload.get("ram_event_id"), str):
                private_events.append((payload.get("session_id"), payload.get("turn_id"), payload["ram_event_id"]))
                continue
            candidate_id = payload.get("candidate_id")
            if not isinstance(candidate_id, str):
                continue
            if event.get("kind") == "candidate_created":
                candidates.setdefault(candidate_id, {**payload, "status": "pending"})
            elif candidate_id in candidates and event.get("kind") == "candidate_promoted":
                candidates[candidate_id].update(
                    {
                        "status": "promoted",
                        "promoted_at": payload.get("promoted_at"),
                        "state_id": payload.get("state_id"),
                        "observation_memory_id": payload.get("observation_memory_id"),
                    }
                )
            elif candidate_id in candidates and event.get("kind") == "candidate_materialized":
                candidates[candidate_id].update(
                    {"observation_memory_id": payload.get("observation_memory_id")}
                )
            elif candidate_id in candidates and event.get("kind") == "candidate_rejected":
                candidates[candidate_id].update(
                    {"status": "rejected", "rejected_at": payload.get("rejected_at")}
                )
        # Private events are delivered to RAM after capture, so resolve their IDs at read time.
        for candidate in candidates.values():
            if candidate.get("status") != "pending":
                continue  # a promoted observation keeps the provenance it was written with
            session, turn = candidate.get("session_id"), candidate.get("turn_id")
            ids = list(candidate.get("source_private_event_ids") or [])
            for event_session, event_turn, ram_event_id in private_events:
                if event_session == session and (not turn or event_turn in {None, "", turn}) and ram_event_id not in ids:
                    ids.append(ram_event_id)
            candidate["source_private_event_ids"] = ids
        return candidates


class PrivateEventOutbox:
    """Durable local queue of private RAM session events written by hooks.

    Hooks run as short-lived processes and must stay fast, so they only queue
    the exact event here. The long-running MCP server, which already holds the
    redis-iris SDK and a warm connection, delivers queued events. Each event
    carries its RAM idempotency key, so a redelivery after an uncertain write
    is deduplicated by RAM rather than blindly repeated.
    """

    _FIELDS = ("session_id", "actor_id", "namespace", "role", "text", "created_at", "metadata", "idempotency_key")
    STALE_CLAIM_SECONDS = 300

    def __init__(self, ledger: PromotionLedger) -> None:
        self.ledger = ledger
        self.directory = ledger.path.parent / "outbox"
        self._lock = threading.Lock()
        self.blocked = False

    def _prepare(self) -> None:
        self.ledger._prepare_parent()
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise PluginError("promotion_store_invalid", "The private event outbox is not a safe directory.")
        os.chmod(self.directory, 0o700)

    def put(self, request: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        self._prepare()
        name = re.sub(r"[^A-Za-z0-9_-]", "", str(request["idempotency_key"]))[:128]
        record = {"request": {key: request[key] for key in self._FIELDS}, "context": dict(context)}
        encoded = _canonical(record).encode("utf-8")
        if len(encoded) > 4 * MAX_EVENT_BYTES:
            raise PluginError("promotion_event_too_large", "The private event exceeds its safe size limit.")
        temporary = self.directory / f".{name}.{os.getpid()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(temporary, flags, 0o600)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            # A duplicate hook delivery replaces the same file: one event per key.
            os.replace(temporary, self.directory / f"{name}.json")
        except OSError as error:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise PluginError("promotion_store_unavailable", "The private event outbox could not be updated.") from error

    def pending(self) -> int:
        try:
            return sum(1 for path in self.directory.glob("*.json"))
        except OSError:
            return 0

    def _reclaim_stale(self) -> None:
        now = time.time()
        for claimed in self.directory.glob("*.json.inflight-*"):
            owner = claimed.name.rsplit("-", 1)[-1]
            alive = owner.isdigit() and _process_alive(int(owner))
            try:
                stale = now - claimed.stat().st_mtime > self.STALE_CLAIM_SECONDS
                if not alive or stale:
                    os.replace(claimed, claimed.with_name(claimed.name.split(".inflight-")[0]))
            except OSError:
                continue

    def drain(self, ram: PromotionRAM, config: Config, *, limit: int = 100, timeout_ms: int = 8_000) -> int:
        """Deliver queued events in capture order; returns how many were delivered.

        Stops at the first transient failure and leaves the rest queued.
        """

        if not self.directory.is_dir():
            self.blocked = False
            return 0
        delivered = attempts = 0
        with self._lock:
            self.blocked = False
            self._reclaim_stale()
            for path in sorted(self.directory.glob("*.json"), key=_mtime):
                if attempts >= limit:
                    break
                claimed = path.with_name(f"{path.name}.inflight-{os.getpid()}")
                try:
                    os.replace(path, claimed)  # atomic claim; another server may hold it
                except OSError:
                    continue
                try:
                    record = json.loads(claimed.read_text(encoding="utf-8"))
                    request = {key: record["request"][key] for key in self._FIELDS}
                    context = dict(record.get("context") or {})
                except (OSError, ValueError, KeyError, TypeError):
                    self._set_aside(claimed, "unreadable")
                    continue
                if request["actor_id"] != config.participant or request["namespace"] != config.personal_namespace:
                    # Captured under another configuration; leave it for a matching server.
                    os.replace(claimed, path)
                    continue
                attempts += 1
                try:
                    result = ram.add_session_event(**request, timeout_ms=timeout_ms)
                except Exception as error:
                    status = getattr(error, "status_code", None)
                    if status in {400, 409, 413, 422}:
                        # RAM rejected this exact event; retrying cannot succeed.
                        self._set_aside(claimed, f"http_{status}")
                        continue
                    os.replace(claimed, path)  # transient: retry later with the same key
                    self.blocked = True
                    break
                ram_event_id = _ram_event_id(result)
                if ram_event_id:
                    self.ledger.append(
                        "ram_private_event",
                        {**context, "ram_event_id": ram_event_id},
                        event_id=f"private-{request['idempotency_key']}",
                    )
                claimed.unlink(missing_ok=True)
                delivered += 1
        return delivered

    def _set_aside(self, claimed: Path, reason: str) -> None:
        """Move a permanently rejected event out of the queue for operator review."""

        rejected = self.directory / "rejected"
        try:
            rejected.mkdir(mode=0o700, exist_ok=True)
            os.replace(claimed, rejected / claimed.name.split(".inflight-")[0])
        except OSError:
            return
        self.ledger.append("ram_private_event_rejected", {"file": claimed.name.split(".inflight-")[0], "reason": reason})


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class OutboxDelivery(threading.Thread):
    """Background delivery of hook-queued private events from the MCP server."""

    BATCH = 100

    def __init__(self, outbox: PrivateEventOutbox, ram: PromotionRAM, config: Config, interval: float = 0.25) -> None:
        super().__init__(name="private-event-delivery", daemon=True)
        self.outbox = outbox
        self.ram = ram
        self.config = config
        self.interval = interval
        self._halt = threading.Event()  # not "_stop": that name is Thread's own method

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        wait = self.interval
        while not self._halt.is_set():
            try:
                delivered = self.outbox.drain(self.ram, self.config, limit=self.BATCH)
                if self.outbox.blocked:
                    wait = min(max(wait, self.interval) * 2, 30.0)  # RAM unavailable: back off
                elif delivered >= self.BATCH:
                    wait = 0.0  # more than one batch queued
                else:
                    wait = self.interval
            except Exception:
                wait = min(max(wait, self.interval) * 2, 30.0)
            self._halt.wait(wait)


@dataclass
class HookCapture:
    config: Config
    ram: PromotionRAM | None
    ledger: PromotionLedger
    timeout_ms: int = 1_500
    outbox: PrivateEventOutbox | None = None

    def _private_event(
        self,
        payload: Mapping[str, Any],
        *,
        role: str,
        text: str,
        hook_id: str,
    ) -> str | None:
        source_session = str(payload.get("session_id") or "unknown")
        private_session = _session_id("personal", self.config.participant, source_session)
        metadata = {
            "contract": PROMOTION_CONTRACT,
            "hook_event": payload.get("hook_event_name"),
            "source_session_hash": _digest(source_session, 32),
            "turn_id": _bounded_text(payload.get("turn_id") or "", 128),
            "tool_use_id": _bounded_text(payload.get("tool_use_id") or "", 128),
            "private_only": True,
        }
        context = {
            "session_id": source_session,
            "turn_id": payload.get("turn_id"),
            "private_session_id": private_session,
            "hook_event": payload.get("hook_event_name"),
        }
        if self.outbox is not None:
            # Fast path for hook processes: queue locally; the MCP server delivers it.
            self.outbox.put(
                {
                    "session_id": private_session,
                    "actor_id": self.config.participant,
                    "namespace": self.config.personal_namespace,
                    "role": role,
                    "text": text,
                    "created_at": _now(),
                    "metadata": metadata,
                    "idempotency_key": hook_id[:128],
                },
                context,
            )
            return None
        if self.ram is None:
            raise PluginError("configuration_missing", "Hook capture needs RAM or a private event outbox.")
        try:
            result = self.ram.add_session_event(
                session_id=private_session,
                actor_id=self.config.participant,
                namespace=self.config.personal_namespace,
                role=role,
                text=text,
                created_at=_now(),
                metadata=metadata,
                idempotency_key=hook_id[:128],
                timeout_ms=self.timeout_ms,
            )
        except Exception:
            self.ledger.append("ram_private_event_pending", context, event_id=f"pending-{hook_id}")
            return None
        ram_event_id = _ram_event_id(result)
        if ram_event_id:
            self.ledger.append(
                "ram_private_event",
                {**context, "ram_event_id": ram_event_id},
                event_id=f"private-{hook_id}",
            )
        return ram_event_id

    def process(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        event_name = payload.get("hook_event_name")
        if event_name not in HOOK_EVENTS:
            raise PluginError("hook_input_invalid", "The hook event is not supported by this plugin.")
        source_session = str(payload.get("session_id") or "")
        if not source_session:
            raise PluginError("hook_input_invalid", "The hook event has no session identifier.")
        hook_id = _event_id(payload)
        turn_id = _bounded_text(payload.get("turn_id") or "", 128)

        if event_name == "UserPromptSubmit":
            prompt = _bounded_text(payload.get("prompt") or "", MAX_PROMPT)
            share_intent = bool(_SHARE_INTENT.search(prompt))
            state_update_intent = bool(_STATE_UPDATE_INTENT.search(prompt))
            self.ledger.append(
                "hook_prompt",
                {
                    "session_id": source_session,
                    "turn_id": turn_id,
                    "prompt": prompt,
                    "share_intent": share_intent,
                    "state_update_intent": state_update_intent,
                },
                event_id=hook_id,
            )
            self._private_event(payload, role="USER", text=prompt or "[empty prompt]", hook_id=hook_id)
            if share_intent or state_update_intent:
                return {
                    "continue": True,
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": (
                            "Possible shared lifecycle update. The prompt is private. Do not merely acknowledge "
                            "a completion-and-publish request. Retrieve the exact current state, then call "
                            "memory_state_update_propose with its ID/current lifecycle, the exact prompt, and "
                            "any explicit resolution time. Inspect the candidate and obtain explicit "
                            "confirmation before memory_candidate_promote."
                        ),
                    },
                }
            return {"continue": True}

        if event_name == "PostToolUse":
            tool_name = _bounded_text(payload.get("tool_name") or "unknown", 256)
            tool_input = _redact(payload.get("tool_input"))
            tool_response = _redact(payload.get("tool_response"))
            evidence = {
                "session_id": source_session,
                "turn_id": turn_id,
                "tool_name": tool_name,
                "tool_use_id": _bounded_text(payload.get("tool_use_id") or "", 128),
                "completed": _tool_completed(payload.get("tool_response")),
                "input_preview": _bounded_text(tool_input, MAX_TOOL_PREVIEW),
                "response_digest": _digest(tool_response, 64),
                "artifact_refs": _artifact_refs(tool_input),
            }
            self.ledger.append("hook_tool", evidence, event_id=hook_id)
            self._private_event(
                payload,
                role="SYSTEM",
                text=(
                    f"Tool {tool_name} completed={str(evidence['completed']).lower()}; "
                    f"artifact_refs={_canonical(evidence['artifact_refs'])}; "
                    f"response_digest={evidence['response_digest']}"
                ),
                hook_id=hook_id,
            )
            return {}

        if event_name == "Stop":
            assistant = _bounded_text(payload.get("last_assistant_message") or "", MAX_ASSISTANT)
            self.ledger.append(
                "hook_stop",
                {
                    "session_id": source_session,
                    "turn_id": turn_id,
                    "last_assistant_message": assistant,
                },
                event_id=hook_id,
            )
            self._private_event(
                payload,
                role="ASSISTANT",
                text=assistant or "[assistant turn completed without text]",
                hook_id=hook_id,
            )
            state = self.ledger.session_state(source_session, turn_id or None)
            completed_evidence = [item for item in state["evidence"] if item.get("completed")]
            should_create = bool(state["share_intent"]) or (
                bool(completed_evidence) and bool(_COMPLETION.search(assistant))
            )
            if should_create:
                subject = (assistant or state["prompt"] or "Review captured session work")[:2_000]
                candidate_id = f"candidate-{_digest([self.config.participant, source_session, turn_id, subject])}"
                self.ledger.append(
                    "candidate_created",
                    {
                        "candidate_id": candidate_id,
                        "session_id": source_session,
                        "turn_id": turn_id,
                        "subject": subject,
                        "captured_at": _now(),
                        "actor_id": self.config.participant,
                        "personal_namespace": self.config.personal_namespace,
                        "explicit_share_intent": bool(state["share_intent"]),
                        "confidence": 1.0 if state["share_intent"] else 0.6,
                        "evidence": completed_evidence[-8:],
                        "source_private_event_ids": state["private_event_ids"],
                    },
                    event_id=f"create-{candidate_id}",
                )
            return {"continue": True}

        # SessionEnd is an advisory, bounded marker. The transcript path is
        # unstable and untrusted, so retain only a digest. Reduced capture does
        # not create a promotion candidate from this event.
        transcript_path = payload.get("transcript_path")
        self.ledger.append(
            "hook_session_end",
            {
                "session_id": source_session,
                "reason": _bounded_text(payload.get("reason") or "other", 64),
                "transcript_path_digest": _digest(transcript_path or "", 64),
            },
            event_id=hook_id,
        )
        self._private_event(
            payload,
            role="SYSTEM",
            text="Session ended; captured prompts remain private and no automatic promotion candidate was created.",
            hook_id=hook_id,
        )
        return {}


class PromotionService:
    def __init__(
        self,
        config: Config,
        ram: PromotionRAM,
        ledger: PromotionLedger,
        outbox: PrivateEventOutbox | None = None,
    ) -> None:
        self.config = config
        self.ram = ram
        self.ledger = ledger
        self.outbox = outbox

    def _flush_private_events(self) -> None:
        """Deliver queued hook events first so candidates carry their RAM event IDs."""

        if self.outbox is None:
            return
        try:
            self.outbox.drain(self.ram, self.config, timeout_ms=3_000)
        except Exception:
            # Still queued; promotion records "pending" provenance as before.
            pass

    @staticmethod
    def _public(candidate: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "candidate_id",
            "status",
            "subject",
            "captured_at",
            "actor_id",
            "explicit_share_intent",
            "confidence",
            "evidence",
            "source_private_event_ids",
            "source_statement",
            "source_hook_event_id",
            "current_state",
            "proposed_observation",
            "promoted_at",
            "rejected_at",
            "state_id",
            "observation_memory_id",
        }
        return {key: candidate.get(key) for key in allowed if key in candidate}

    def candidate_propose_state_update(
        self,
        *,
        current_state: Mapping[str, Any],
        expected_current_status: str,
        lifecycle_status: str,
        evidence_text: str,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        self._flush_private_events()
        source = self.ledger.prompt_source(evidence_text)
        if source is None:
            raise PluginError(
                "private_evidence_not_found",
                "The exact statement was not found in this user's private hook capture. Use the complete prompt text.",
            )
        current_status = current_state.get("lifecycle_status")
        if current_status != expected_current_status:
            raise PluginError(
                "state_changed",
                "The current lifecycle no longer matches the retrieved value. Search the state again before proposing an update.",
            )
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise PluginError("invalid_input", "lifecycle_status is not supported by organizational-state-v3.")
        state_id = current_state.get("state_id")
        state_kind = current_state.get("state_kind")
        project_id = current_state.get("project_id")
        if not all(isinstance(value, str) and SLUG.fullmatch(value) for value in (state_id, project_id)):
            raise PluginError("ram_contract_error", "The current state has incompatible canonical identifiers.")
        if state_kind not in STATE_KINDS:
            raise PluginError("ram_contract_error", "The current state has an incompatible state kind.")
        observed_at = source.get("captured_at") or _now()
        terminal = lifecycle_status in {
            "decided", "approved", "rejected", "completed", "resolved", "cancelled", "superseded"
        }
        proposal = {
            "state_id": state_id,
            "state_kind": state_kind,
            "lifecycle_status": lifecycle_status,
            "evidence_role": "resolves" if terminal else "updates",
            "subject": str(current_state.get("subject") or "")[:4_000],
            "project_id": project_id,
            "project_step_id": str(current_state.get("project_step_id") or ""),
            "meeting_id": str(current_state.get("meeting_id") or ""),
            "accountable_entity_id": str(current_state.get("accountable_entity_id") or ""),
            "related_entity_ids": list(current_state.get("related_entity_ids") or []),
            "effective_at": observed_at,
            "due_at": str(current_state.get("due_at") or ""),
            "resolved_at": str(resolved_at or observed_at) if terminal else "",
            "requested_decision": str(current_state.get("requested_decision") or "")[:4_000],
            "impact": str(current_state.get("impact") or "")[:4_000],
            "supersedes_state_ids": [],
            "relations": {"edges": []},
        }
        candidate_id = f"candidate-{_digest([source['hook_event_id'], state_id, lifecycle_status])}"
        self.ledger.append(
            "candidate_created",
            {
                "candidate_id": candidate_id,
                "session_id": source["session_id"],
                "turn_id": source["turn_id"],
                "subject": proposal["subject"],
                "captured_at": observed_at,
                "actor_id": self.config.participant,
                "personal_namespace": self.config.personal_namespace,
                "explicit_share_intent": False,
                "confidence": 1.0,
                "evidence": [],
                "source_statement": source["prompt"],
                "source_hook_event_id": source["hook_event_id"],
                "source_private_event_ids": source["source_private_event_ids"],
                "current_state": {
                    "state_id": state_id,
                    "lifecycle_status": current_status,
                    "subject": current_state.get("subject"),
                    "project_id": project_id,
                    "accountable_entity_id": current_state.get("accountable_entity_id"),
                },
                "proposed_observation": proposal,
            },
            event_id=f"create-{candidate_id}",
        )
        candidate = self.ledger.candidates()[candidate_id]
        return {
            "ok": True,
            "candidate": self._public(candidate),
            "next_step": (
                "Show the source statement and exact proposed observation to the user. "
                "Only after explicit confirmation call memory_candidate_promote with confirmed=true."
            ),
        }

    def candidate_list(self, status: str = "pending", limit: int = 50) -> dict[str, Any]:
        if status not in {"pending", "promoted", "rejected", "all"}:
            raise PluginError("invalid_input", "status must be pending, promoted, rejected, or all.")
        self._flush_private_events()
        candidates = list(self.ledger.candidates().values())
        if status != "all":
            candidates = [candidate for candidate in candidates if candidate.get("status") == status]
        candidates.sort(key=lambda item: str(item.get("captured_at", "")), reverse=True)
        return {
            "ok": True,
            "personal_namespace": self.config.personal_namespace,
            "candidates": [self._public(candidate) for candidate in candidates[:limit]],
            "note": "Candidates are private. Promotion always requires explicit confirmation.",
        }

    def candidate_inspect(self, candidate_id: str) -> dict[str, Any]:
        self._flush_private_events()
        candidate = self.ledger.candidates().get(candidate_id)
        if candidate is None:
            raise PluginError("candidate_not_found", "The private promotion candidate was not found.")
        return {
            "ok": True,
            "candidate": self._public(candidate),
            "required_confirmation": (
                "Confirm that this evidence should become a shared organizational-state observation, "
                "including its project, state kind, lifecycle, authority, and sensitivity."
            ),
        }


    def candidate_reject(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.ledger.candidates().get(candidate_id)
        if candidate is None:
            raise PluginError("candidate_not_found", "The private promotion candidate was not found.")
        if candidate.get("status") == "promoted":
            raise PluginError("candidate_already_promoted", "A promoted candidate cannot be rejected locally.")
        if candidate.get("status") != "rejected":
            self.ledger.append(
                "candidate_rejected",
                {"candidate_id": candidate_id, "rejected_at": _now()},
                event_id=f"reject-{candidate_id}",
            )
        return {"ok": True, "candidate_id": candidate_id, "status": "rejected"}

    def _validated_observation(self, candidate: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
        state_kind = values.get("state_kind")
        lifecycle = values.get("lifecycle_status")
        evidence_role = values.get("evidence_role", "creates")
        if state_kind not in STATE_KINDS:
            raise PluginError("invalid_input", "state_kind is not supported by organizational-state-v3.")
        if lifecycle not in LIFECYCLE_STATUSES:
            raise PluginError("invalid_input", "lifecycle_status is not supported by organizational-state-v3.")
        if evidence_role not in EVIDENCE_ROLES:
            raise PluginError("invalid_input", "evidence_role is not supported by organizational-state-v3.")
        project_id = values.get("project_id")
        if not isinstance(project_id, str) or not SLUG.fullmatch(project_id):
            raise PluginError("invalid_input", "project_id must be a canonical slug.")
        state_id = values.get("state_id") or f"state-personal-{_digest([candidate['candidate_id'], project_id], 32)}"
        if not isinstance(state_id, str) or not SLUG.fullmatch(state_id):
            raise PluginError("invalid_input", "state_id must be a canonical slug.")

        def slug(name: str) -> str:
            value = values.get(name, "")
            if value in {None, ""}:
                return ""
            if not isinstance(value, str) or not SLUG.fullmatch(value):
                raise PluginError("invalid_input", f"{name} must be a canonical slug.")
            return value

        def slug_list(name: str) -> list[str]:
            value = values.get(name, [])
            if not isinstance(value, list) or len(value) > 50 or any(
                not isinstance(item, str) or not SLUG.fullmatch(item) for item in value
            ):
                raise PluginError("invalid_input", f"{name} must contain canonical slugs.")
            return value

        subject = values.get("subject") or candidate.get("subject")
        if not isinstance(subject, str) or not subject.strip() or len(subject.strip()) > 4_000:
            raise PluginError("invalid_input", "subject must contain 1–4000 characters.")
        observed_at = candidate.get("captured_at") or _now()
        private_events = candidate.get("source_private_event_ids") or []
        locator = (
            f"private-session:{_digest(candidate.get('session_id', ''), 24)};"
            f"events:{','.join(str(item) for item in private_events[:20]) or 'pending'};"
            f"candidate:{candidate['candidate_id']}"
        )
        return {
            "schema_version": OBSERVATION_SCHEMA,
            "state_id": state_id,
            "state_kind": state_kind,
            "lifecycle_status": lifecycle,
            "evidence_role": evidence_role,
            "subject": subject.strip(),
            "project_id": project_id,
            "project_step_id": slug("project_step_id"),
            "meeting_id": slug("meeting_id"),
            "accountable_entity_id": slug("accountable_entity_id"),
            "related_entity_ids": slug_list("related_entity_ids"),
            "observed_at": observed_at,
            "event_sequence": 0,
            "source_offset_ms": 0,
            "effective_at": str(values.get("effective_at") or ""),
            "due_at": str(values.get("due_at") or ""),
            "resolved_at": str(values.get("resolved_at") or ""),
            "requested_decision": str(values.get("requested_decision") or "")[:4_000],
            "impact": str(values.get("impact") or "")[:4_000],
            "supersedes_state_ids": slug_list("supersedes_state_ids"),
            "relations": {"edges": []},
            "source_artifact_id": f"personal-{candidate['candidate_id']}"[:64],
            "source_revision": f"turn-{_digest(candidate.get('turn_id', ''), 24)}",
            "evidence_locator": locator,
        }

    def _observation_payload(
        self,
        candidate_id: str,
        observation: Mapping[str, Any],
    ) -> dict[str, Any]:
        memory_id = f"observation-{_digest(candidate_id)}"
        return {
            "id": memory_id,
            "text": observation["subject"],
            "namespace": self.config.namespace,
            "ownerId": self.config.agenda_owner_id,
            "memoryType": "organizational_state",
            "topics": [
                "organizational-state",
                str(observation["state_kind"]),
                str(observation["project_id"]),
            ],
            "attributes": dict(observation),
        }

    def _matches_observation(
        self,
        record: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> bool:
        owner = record.get("ownerId", record.get("owner_id"))
        memory_type = record.get("memoryType", record.get("memory_type"))
        namespace = record.get("namespace")
        return (
            record.get("id") == expected["id"]
            and record.get("text") == expected["text"]
            and isinstance(namespace, str)
            and namespace.casefold() == self.config.namespace.casefold()
            and owner == self.config.agenda_owner_id
            and memory_type == "organizational_state"
            and _canonical(_attributes(dict(record))) == _canonical(expected["attributes"])
        )

    def _ensure_observation(self, payload: dict[str, Any]) -> str:
        memory_id = str(payload["id"])
        try:
            existing = self.ram.get(memory_id)
        except Exception as error:
            problem = public_error(error)
            if problem.get("code") != "not_found":
                raise PluginError(str(problem["code"]), str(problem["message"])) from error
        else:
            if self._matches_observation(existing, payload):
                return "already_present"
            raise PluginError(
                "promotion_conflict",
                "A different shared observation already uses this promotion identifier. Do not retry automatically.",
            )

        try:
            self.ram.create([payload])
        except Exception as write_error:
            try:
                existing = self.ram.get(memory_id)
            except Exception as read_error:
                problem = public_error(write_error)
                if problem.get("code") in {
                    "authentication_failed",
                    "access_denied",
                    "request_rejected",
                    "not_found",
                }:
                    raise PluginError(str(problem["code"]), str(problem["message"])) from write_error
                raise PluginError(
                    "write_unverified",
                    "The shared observation write could not be verified. Do not publish it again automatically.",
                ) from read_error
            if self._matches_observation(existing, payload):
                return "already_present"
            raise PluginError(
                "promotion_conflict",
                "A different shared observation was read after the write. Do not retry automatically.",
            ) from write_error

        try:
            created = self.ram.get(memory_id)
        except Exception as error:
            raise PluginError(
                "write_unverified",
                "RAM acknowledged the shared observation but it could not be read back. Do not publish it again automatically.",
            ) from error
        if not self._matches_observation(created, payload):
            raise PluginError(
                "write_unverified",
                "RAM returned a different shared observation after the write. Do not publish it again automatically.",
            )
        return "created"

    def candidate_promote(
        self,
        *,
        candidate_id: str,
        confirmed: bool,
        observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PluginError("confirmation_required", "Explicit confirmation is required before shared promotion.")
        self._flush_private_events()
        candidate = self.ledger.candidates().get(candidate_id)
        if candidate is None:
            raise PluginError("candidate_not_found", "The private promotion candidate was not found.")
        if candidate.get("status") == "rejected":
            raise PluginError("candidate_rejected", "The rejected candidate must be recaptured before promotion.")
        proposed = candidate.get("proposed_observation")
        if isinstance(proposed, dict):
            if observation is not None and _canonical(dict(observation)) != _canonical(proposed):
                raise PluginError(
                    "candidate_changed",
                    "The supplied observation differs from the inspected proposal. Inspect it again before promotion.",
                )
            observation = proposed
        if observation is None:
            if candidate.get("status") == "promoted":
                return {
                    "ok": True,
                    "outcome": "already_submitted",
                    "candidate_id": candidate_id,
                    "state_id": candidate.get("state_id"),
                    "observation_memory_id": candidate.get("observation_memory_id"),
                    "projection_status": "pending_reconciliation",
                }
            raise PluginError(
                "observation_required",
                "This older candidate has no prepared observation. Supply the reviewed organizational-state fields.",
            )
        normalized = self._validated_observation(candidate, observation)
        payload = self._observation_payload(candidate_id, normalized)
        write_outcome = self._ensure_observation(payload)
        confirmed_at = _now()
        was_promoted = candidate.get("status") == "promoted"
        event = {
            "candidate_id": candidate_id,
            "promoted_at": confirmed_at,
            "state_id": normalized["state_id"],
            "observation_memory_id": payload["id"],
            "contract": OBSERVATION_SCHEMA,
        }
        if was_promoted:
            self.ledger.append(
                "candidate_materialized",
                event,
                event_id=f"materialize-{candidate_id}",
            )
        else:
            self.ledger.append(
                "candidate_promoted",
                event,
                event_id=f"promote-{candidate_id}",
            )
        return {
            "ok": True,
            "outcome": (
                "promotion_materialized"
                if was_promoted and not candidate.get("observation_memory_id")
                else "already_submitted"
                if was_promoted or write_outcome == "already_present"
                else "promotion_saved"
            ),
            "candidate_id": candidate_id,
            "state_id": normalized["state_id"],
            "observation_memory_id": payload["id"],
            "observation_contract": OBSERVATION_SCHEMA,
            "projection_status": "pending_reconciliation",
            "message": (
                "RAM stored the confirmed organizational-state observation directly. The central "
                "reconciliation projector will update the current view on its next run."
            ),
        }


class PromotionFacade:
    """Add promotion tools to the existing single plugin service surface."""

    def __init__(self, base: Any, promotion: PromotionService) -> None:
        self.base = base
        self.promotion = promotion

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def system_status(self) -> dict[str, Any]:
        result = self.base.system_status()
        outbox = self.promotion.outbox
        if outbox is not None and isinstance(result, dict):
            result["private_capture"] = {"queued_events": outbox.pending()}
        return result

    def memory_candidate_list(self, status: str = "pending", limit: int = 50) -> dict[str, Any]:
        return self.promotion.candidate_list(status=status, limit=limit)

    def memory_state_update_propose(
        self,
        state_id: str,
        expected_current_status: str,
        lifecycle_status: str,
        evidence_text: str,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        current_state = self.base.current_state_by_id(state_id)
        return self.promotion.candidate_propose_state_update(
            current_state=current_state,
            expected_current_status=expected_current_status,
            lifecycle_status=lifecycle_status,
            evidence_text=evidence_text,
            resolved_at=resolved_at,
        )

    def memory_candidate_inspect(self, candidate_id: str) -> dict[str, Any]:
        return self.promotion.candidate_inspect(candidate_id)

    def memory_candidate_promote(
        self,
        candidate_id: str,
        confirmed: bool,
        observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.promotion.candidate_promote(
            candidate_id=candidate_id,
            confirmed=confirmed,
            observation=observation,
        )

    def memory_candidate_reject(self, candidate_id: str) -> dict[str, Any]:
        return self.promotion.candidate_reject(candidate_id)

