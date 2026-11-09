"""Rebuild the derived current-state projections from the shared observation lane.

Every management record lives in the configured shared namespace. Observations
keep their author as ``ownerId``; the namespace, memory type, and schema decide
what is in scope. The plugin runs this after a confirmed promotion, and the
administrator script and setup run the same code.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable

from .config import Config, error_status, public_error
from .projector import build_projections


OBSERVATION_TYPE = "organizational_state"
OBSERVATION_SCHEMA = "organizational-state-v3"
OBSERVATION_SCHEMAS = (OBSERVATION_SCHEMA, "organizational-state-v2")
PROJECTION_TYPE = "organizational_state_projection"
PROJECTION_SCHEMA = "organizational-state-projection-v1"
PAGE_SIZE = 100
WRITE_BATCH_SIZE = 50
MOVE_BATCH_SIZE = 50
# A pass that loses a race with another writer reads everything again.
MAX_WRITE_PASSES = 3
_CONFLICT_STATUSES = {404, 409, 412}
POLICY_PATH = Path(__file__).with_name("projection-policy.json")

Projector = Callable[[list[dict[str, Any]], dict[str, Any]], tuple[Any, ...]]


class ReconciliationError(RuntimeError):
    """A safe reconciliation failure."""


class _WriteConflict(Exception):
    """Another writer changed a projection between our read and our write."""


def bundled_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _field(record: dict[str, Any], camel: str, snake: str) -> Any:
    return record.get(camel, record.get(snake))


def _items(result: dict[str, Any]) -> list[dict[str, Any]]:
    value = result.get("items", result.get("memories", []))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ReconciliationError("RAM returned an invalid memory page")
    return value


def _attribute(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        key, nested = next(iter(value.items()))
        if key in {"string", "number", "boolean", "strings", "numbers", "booleans", "object"}:
            return nested
    return value


def _attributes(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("attributes")
    if not isinstance(value, dict):
        return {}
    return {str(key): _attribute(item) for key, item in value.items()}


def in_lane(record: dict[str, Any], config: Config, memory_type: str, schemas: tuple[str, ...] | frozenset[str]) -> bool:
    """A management record is in scope by namespace, type, and schema; any author."""

    namespace = record.get("namespace")
    return (
        isinstance(namespace, str)
        and namespace.casefold() == config.namespace.casefold()
        and _field(record, "memoryType", "memory_type") == memory_type
        and _attributes(record).get("schema_version") in schemas
    )


def _pages(ram: Any, filter_: dict[str, Any]) -> list[dict[str, Any]]:
    token: str | None = None
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    while True:
        request: dict[str, Any] = {"filter": filter_, "filterOp": "all", "limit": PAGE_SIZE}
        if token is not None:
            request["pageToken"] = token
        result = ram.search(request, timeout_ms=30_000)
        records.extend(_items(result))
        next_token = _field(result, "nextPageToken", "next_page_token")
        if not isinstance(next_token, str) or not next_token:
            return records
        if next_token in seen:
            raise ReconciliationError("RAM repeated a pagination token")
        seen.add(next_token)
        token = next_token


def unnamespaced_management_ids(config: Config, ram: Any) -> dict[str, list[str]]:
    """Management records from earlier versions, which had no namespace.

    Earlier versions wrote every management record under one shared owner,
    ``RAM_AGENDA_OWNER_ID``. Only that owner's records are adopted, so other
    teams' unnamespaced records in the same store are left alone. Without the
    setting nothing is adopted.
    """

    found: dict[str, list[str]] = {"observations": [], "projections": []}
    if not config.agenda_owner_id:
        return found
    lanes = [("observations", OBSERVATION_TYPE, schema) for schema in OBSERVATION_SCHEMAS]
    lanes.append(("projections", PROJECTION_TYPE, PROJECTION_SCHEMA))
    for kind, memory_type, schema in lanes:
        for record in _pages(
            ram,
            {
                "unnamespaced": True,
                "ownerId": {"eq": config.agenda_owner_id},
                "memoryType": {"eq": memory_type},
                "attributes": {"schema_version": {"string": schema}},
            },
        ):
            memory_id = record.get("id")
            if isinstance(memory_id, str) and memory_id and memory_id not in found[kind]:
                found[kind].append(memory_id)
    return found


def _in_namespace(config: Config, record: dict[str, Any]) -> bool:
    namespace = record.get("namespace")
    return isinstance(namespace, str) and namespace.casefold() == config.namespace.casefold()


def move_into_namespace(config: Config, ram: Any, memory_ids: list[str]) -> list[str]:
    """Move explicit records into the shared namespace, creating it if needed.

    A record that is already there counts as moved, so reruns are harmless.
    """

    moved: list[str] = []
    ids = sorted({item for item in memory_ids if isinstance(item, str) and item})
    for offset in range(0, len(ids), MOVE_BATCH_SIZE):
        batch = ids[offset : offset + MOVE_BATCH_SIZE]
        result = ram.move(batch, config.namespace)
        moved.extend(str(item) for item in result.get("moved") or [])
        failed = [
            str(error.get("memoryId") or error.get("memory_id") or "")
            for error in result.get("errors") or []
            if isinstance(error, dict)
        ]
        stuck = []
        for memory_id in failed:
            try:
                placed = memory_id and _in_namespace(config, ram.get(memory_id))
            except Exception:  # noqa: BLE001 - report the count, not the upstream error
                placed = False
            (moved if placed else stuck).append(memory_id)
        if stuck or len(failed) < len(result.get("errors") or []):
            raise ReconciliationError(
                f"RAM could not move {max(len(stuck), 1)} record(s) into the {config.namespace} namespace"
            )
    return moved


def adopt_unnamespaced(config: Config, ram: Any, *, apply: bool) -> dict[str, Any]:
    """Find, and with apply move, earlier management records that have no namespace."""

    found = unnamespaced_management_ids(config, ram)
    total = len(found["observations"]) + len(found["projections"])
    if not apply or not total:
        return {"unnamespaced_count": total, "moved_count": 0, "moved_observation_ids": []}
    move_into_namespace(config, ram, found["observations"] + found["projections"])
    return {
        "unnamespaced_count": total,
        "moved_count": total,
        "moved_observation_ids": found["observations"],
    }


class ReconciliationJob:
    """Read all observations and write only the projections that changed."""

    def __init__(
        self,
        config: Config,
        ram: Any,
        projector: Projector | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.ram = ram
        self.projector = projector or build_projections
        self.policy = policy if policy is not None else bundled_policy()

    def _search_all(self, memory_type: str, schema: str) -> list[dict[str, Any]]:
        page = _pages(
            self.ram,
            {
                "namespace": {"eq": self.config.namespace},
                "memoryType": {"eq": memory_type},
                "attributes": {"schema_version": {"string": schema}},
            },
        )
        if any(not in_lane(item, self.config, memory_type, (schema,)) for item in page):
            raise ReconciliationError("RAM returned an out-of-scope management record")
        return page

    @staticmethod
    def _candidate_visible(observations: list[dict[str, Any]], candidate_id: str) -> bool:
        artifact = f"personal-{candidate_id}"[:64]
        return any(
            _attributes(record).get("source_artifact_id") == artifact
            or candidate_id in str(_attributes(record).get("evidence_locator") or "")
            for record in observations
        )

    def load_observations(self) -> list[dict[str, Any]]:
        """Read the complete observation lane for projection or verification."""

        return [
            record
            for schema in OBSERVATION_SCHEMAS
            for record in self._search_all(OBSERVATION_TYPE, schema)
        ]

    def wait_until_searchable(self, memory_ids: list[str], timeout_seconds: float = 60, poll_seconds: float = 2) -> bool:
        """Wait until moved or new observations appear in namespace searches."""

        wanted = set(memory_ids)
        deadline = time.monotonic() + timeout_seconds
        while True:
            if wanted <= {str(item.get("id")) for item in self.load_observations()}:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(poll_seconds, max(0.01, deadline - time.monotonic())))

    def _observations(
        self,
        wait_for_candidate: str | None,
        timeout_seconds: float,
        poll_seconds: float,
    ) -> tuple[list[dict[str, Any]], bool]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            observations = self.load_observations()
            visible = wait_for_candidate is None or self._candidate_visible(
                observations, wait_for_candidate
            )
            if visible or time.monotonic() >= deadline:
                return observations, visible
            time.sleep(min(poll_seconds, max(0.01, deadline - time.monotonic())))

    def _payload(self, projection: Any) -> dict[str, Any]:
        # The person whose run rebuilt a projection is its owner.
        value = projection.sdk_input(self.config.participant)
        return {
            "id": value["id"],
            "text": value["text"],
            "namespace": self.config.namespace,
            "ownerId": value["owner_id"],
            "memoryType": value["memory_type"],
            "topics": value["topics"],
            "attributes": value["attributes"],
        }

    def _same_projection(self, current: dict[str, Any], desired: dict[str, Any]) -> bool:
        # Ownership is ignored: a rebuild by another participant changes nothing.
        return (
            in_lane(current, self.config, PROJECTION_TYPE, (PROJECTION_SCHEMA,))
            and current.get("text") == desired["text"]
            and _attributes(current) == desired["attributes"]
        )

    def _verify(self, payload: dict[str, Any]) -> None:
        record = self.ram.get(payload["id"])
        if not self._same_projection(record, payload):
            raise ReconciliationError("A written projection could not be verified")

    def _plan(self, observations: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        try:
            projections = self.projector(observations, self.policy)
        except (KeyError, TypeError, ValueError) as error:
            raise ReconciliationError("The versioned projection policy could not be applied") from error
        desired = {item.memory_id: self._payload(item) for item in projections}
        existing = {
            str(item.get("id")): item
            for item in self._search_all(PROJECTION_TYPE, PROJECTION_SCHEMA)
            if item.get("id")
        }
        changed = [
            payload
            for memory_id, payload in sorted(desired.items())
            if memory_id not in existing
            or not self._same_projection(existing[memory_id], payload)
        ]
        return desired, existing, changed

    def _read(self, memory_id: str) -> dict[str, Any] | None:
        """Read one record by ID; None when it does not exist (an ordinary race)."""

        try:
            return self.ram.get(memory_id)
        except Exception as error:  # noqa: BLE001 - map to a stable message
            if error_status(error) == 404:
                return None
            raise ReconciliationError("RAM refused to read a derived projection") from error

    def _replace(self, payload: dict[str, Any], current: dict[str, Any]) -> bool:
        """Replace one projection only if it is unchanged since read; False on a race."""

        revision = current.get("revision")
        if not isinstance(revision, str) or not revision:
            # Some search results omit the revision; read it by ID instead.
            current = self._read(payload["id"]) or {}
            revision = current.get("revision")
        owner = _field(current, "ownerId", "owner_id")
        # Keep the existing owner: replacing a record never changes who owns it.
        replacement = {**payload, "ownerId": owner} if isinstance(owner, str) and owner else payload
        try:
            self.ram.upsert(
                replacement,
                expected_revision=revision if isinstance(revision, str) and revision else None,
            )
        except Exception as error:  # noqa: BLE001 - report a stable message
            if error_status(error) in _CONFLICT_STATUSES:
                return False
            raise ReconciliationError("RAM rejected an updated derived projection") from error
        return True

    def _write(self, changed: list[dict[str, Any]], existing: dict[str, dict[str, Any]]) -> int:
        """Create new projections and conditionally replace changed ones.

        Returns how many were written; raises _WriteConflict (after writing the
        rest) when another writer got to one first.
        """

        written = 0
        conflict = False
        new = [payload for payload in changed if payload["id"] not in existing]
        for offset in range(0, len(new), WRITE_BATCH_SIZE):
            batch = new[offset : offset + WRITE_BATCH_SIZE]
            pending = {str(payload["id"]): payload for payload in batch}
            response = self.ram.create(batch)
            errors = response.get("errors") or []
            written += len(batch) - len(errors)
            for error in errors:
                memory_id = str(error.get("memoryId") or error.get("memory_id") or "")
                if error.get("status") != 409 or memory_id not in pending:
                    raise ReconciliationError("RAM rejected one or more derived projections")
                # It exists already: search had not caught up, or someone else
                # created it first. Replace it if it is ours to see.
                current = self._read(memory_id)
                if current is None:
                    conflict = True
                    continue
                if not _in_namespace(self.config, current):
                    raise ReconciliationError(
                        "A derived projection with the same ID exists outside the shared namespace. "
                        "Run scripts/reconcile_management_state.py --apply to move it."
                    )
                if self._same_projection(current, pending[memory_id]):
                    continue
                if self._replace(pending[memory_id], current):
                    written += 1
                else:
                    conflict = True
        for payload in changed:
            current = existing.get(payload["id"])
            if current is None:
                continue
            if self._replace(payload, current):
                written += 1
            else:
                conflict = True
        if conflict:
            raise _WriteConflict(written)
        return written

    @staticmethod
    def _behind(observations: list[dict[str, Any]], existing: dict[str, dict[str, Any]], changed: list[dict[str, Any]]) -> bool:
        """True when a stored projection cites an observation this run has not seen.

        Someone else rebuilt it from a newer observation that search has not
        returned to us yet; writing now would undo their update.
        """

        seen = {str(item.get("id")) for item in observations}
        for payload in changed:
            current = existing.get(payload["id"])
            supports = _attributes(current).get("supporting_memory_ids") if current else None
            if isinstance(supports, list) and any(str(item) not in seen for item in supports):
                return True
        return False

    def run(
        self,
        *,
        apply: bool = False,
        wait_for_candidate: str | None = None,
        timeout_seconds: float = 0,
        poll_seconds: float = 5.0,
        retry_delay_seconds: float = 2.0,
    ) -> dict[str, Any]:
        if timeout_seconds < 0 or timeout_seconds > 900:
            raise ReconciliationError("timeout_seconds must be from 0 to 900")
        if poll_seconds <= 0 or poll_seconds > 60:
            raise ReconciliationError("poll_seconds must be greater than 0 and no more than 60")

        wrote = False
        for attempt in range(MAX_WRITE_PASSES):
            if attempt:
                time.sleep(retry_delay_seconds * attempt)  # let search catch up
            observations, candidate_visible = self._observations(
                wait_for_candidate, timeout_seconds if attempt == 0 else 0, poll_seconds
            )
            if wait_for_candidate is not None and not candidate_visible:
                return {
                    "ok": True,
                    "status": "awaiting_observation",
                    "applied": False,
                    "candidate_id": wait_for_candidate,
                    "observation_count": len(observations),
                    "message": "The confirmed promotion observation is not visible in long-term memory. Inspect it before retrying a write.",
                }
            desired, existing, changed = self._plan(observations)
            result = {
                "ok": True,
                "status": "ready" if changed else "no_changes",
                "applied": False,
                "policy_id": self.policy["policyId"],
                "observation_count": len(observations),
                "projection_count": len(desired),
                "changed_projection_count": len(changed),
                "unchanged_projection_count": len(desired) - len(changed),
                "candidate_visible": candidate_visible,
            }
            if not apply or not changed:
                return {**result, "status": "applied", "applied": True} if wrote else result
            # On the last pass a missing citation may be a deleted record, so write.
            if attempt < MAX_WRITE_PASSES - 1 and self._behind(observations, existing, changed):
                continue
            try:
                written = self._write(changed, existing)
            except _WriteConflict as conflict:
                wrote = wrote or bool(conflict.args and conflict.args[0])
                continue
            for payload in changed:
                self._verify(payload)
            return {**result, "status": "applied", "applied": True, "written_projection_count": written}
        raise ReconciliationError(
            "Other people kept changing the current state at the same time. Run the update again."
        )

    def refresh_after_promotion(self, candidate_id: str, timeout_seconds: float = 20, poll_seconds: float = 1) -> dict[str, Any]:
        """Bring the current view up to date right after a confirmed promotion."""

        try:
            result = self.run(
                apply=True,
                wait_for_candidate=candidate_id,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )
        except ReconciliationError:
            return {"projection_status": "pending_reconciliation", "projection_error": "projection_write_failed"}
        except Exception as error:  # noqa: BLE001 - report the public code only
            return {"projection_status": "pending_reconciliation", "projection_error": str(public_error(error)["code"])}
        if result["status"] == "awaiting_observation":
            return {"projection_status": "pending_reconciliation", "projection_error": "observation_not_yet_searchable"}
        return {"projection_status": "current", "changed_projection_count": result["changed_projection_count"]}
