"""Run the one canonical projector after RAM observations become visible."""

from __future__ import annotations

import time
from typing import Any


OBSERVATION_TYPE = "organizational_state"
OBSERVATION_SCHEMA = "organizational-state-v3"
OBSERVATION_SCHEMAS = (OBSERVATION_SCHEMA, "organizational-state-v2")
PROJECTION_TYPE = "organizational_state_projection"
PROJECTION_SCHEMA = "organizational-state-projection-v1"
PAGE_SIZE = 100
WRITE_BATCH_SIZE = 50


class ReconciliationError(RuntimeError):
    """A safe reconciliation failure."""


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


class ReconciliationJob:
    """Read all immutable observations and upsert changed derived projections."""

    def __init__(self, config: Any, ram: Any, bundle: Any) -> None:
        self.config = config
        self.ram = ram
        self.bundle = bundle

    def _scope_matches(self, record: dict[str, Any], memory_type: str, schema: str) -> bool:
        namespace = record.get("namespace")
        namespace_matches = namespace in {None, ""} or (
            isinstance(namespace, str)
            and namespace.casefold() == self.config.namespace.casefold()
        )
        return (
            _field(record, "ownerId", "owner_id") == self.config.agenda_owner_id
            and _field(record, "memoryType", "memory_type") == memory_type
            and _attributes(record).get("schema_version") == schema
            and namespace_matches
        )

    def _search_all(self, memory_type: str, schema: str) -> list[dict[str, Any]]:
        token: str | None = None
        seen_tokens: set[str] = set()
        records: list[dict[str, Any]] = []
        while True:
            request: dict[str, Any] = {
                "filter": {
                    "ownerId": {"eq": self.config.agenda_owner_id},
                    "memoryType": {"eq": memory_type},
                    "attributes": {"schema_version": {"string": schema}},
                },
                "filterOp": "all",
                "limit": PAGE_SIZE,
            }
            if token is not None:
                request["pageToken"] = token
            result = self.ram.search(request, timeout_ms=30_000)
            page = _items(result)
            if any(not self._scope_matches(item, memory_type, schema) for item in page):
                raise ReconciliationError("RAM returned an out-of-scope management record")
            records.extend(page)
            next_token = _field(result, "nextPageToken", "next_page_token")
            if not isinstance(next_token, str) or not next_token:
                return records
            if next_token in seen_tokens:
                raise ReconciliationError("RAM repeated a pagination token")
            seen_tokens.add(next_token)
            token = next_token

    @staticmethod
    def _candidate_visible(observations: list[dict[str, Any]], candidate_id: str) -> bool:
        artifact = f"personal-{candidate_id}"[:64]
        return any(
            _attributes(record).get("source_artifact_id") == artifact
            or candidate_id in str(_attributes(record).get("evidence_locator") or "")
            for record in observations
        )

    def _observations(
        self,
        wait_for_candidate: str | None,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> tuple[list[dict[str, Any]], bool]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            observations = [
                record
                for schema in OBSERVATION_SCHEMAS
                for record in self._search_all(OBSERVATION_TYPE, schema)
            ]
            visible = wait_for_candidate is None or self._candidate_visible(
                observations, wait_for_candidate
            )
            if visible or time.monotonic() >= deadline:
                return observations, visible
            time.sleep(min(poll_seconds, max(0.01, deadline - time.monotonic())))

    def _payload(self, projection: Any) -> dict[str, Any]:
        value = projection.sdk_input(self.config.agenda_owner_id)
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
        return (
            self._scope_matches(current, PROJECTION_TYPE, PROJECTION_SCHEMA)
            and current.get("text") == desired["text"]
            and _attributes(current) == desired["attributes"]
        )

    def _verify(self, payload: dict[str, Any]) -> None:
        record = self.ram.get(payload["id"])
        if not self._same_projection(record, payload):
            raise ReconciliationError("A written projection could not be verified")

    def run(
        self,
        *,
        apply: bool = False,
        wait_for_candidate: str | None = None,
        timeout_seconds: int = 0,
        poll_seconds: float = 5.0,
    ) -> dict[str, Any]:
        if timeout_seconds < 0 or timeout_seconds > 900:
            raise ReconciliationError("timeout_seconds must be from 0 to 900")
        if poll_seconds <= 0 or poll_seconds > 60:
            raise ReconciliationError("poll_seconds must be greater than 0 and no more than 60")

        observations, candidate_visible = self._observations(
            wait_for_candidate, timeout_seconds, poll_seconds
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

        try:
            projections = self.bundle.projector()(
                observations, self.bundle.projection_policy()
            )
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
        result = {
            "ok": True,
            "status": "ready" if changed else "no_changes",
            "applied": False,
            "policy_id": self.bundle.projection_policy()["policyId"],
            "observation_count": len(observations),
            "projection_count": len(desired),
            "changed_projection_count": len(changed),
            "unchanged_projection_count": len(desired) - len(changed),
            "candidate_visible": candidate_visible,
        }
        if not apply or not changed:
            return result

        for offset in range(0, len(changed), WRITE_BATCH_SIZE):
            batch = changed[offset : offset + WRITE_BATCH_SIZE]
            response = self.ram.create(batch)
            if response.get("errors"):
                raise ReconciliationError("RAM rejected one or more derived projections")
        for payload in changed:
            self._verify(payload)
        return {**result, "status": "applied", "applied": True}
