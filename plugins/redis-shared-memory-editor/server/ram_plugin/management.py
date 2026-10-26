"""Management-state reads shared by the MCP tools and agenda workflow."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .config import Config, PluginError, VERSION
from .playbook import ALLOWED_TOOLS, PlaybookClient
from .ram import RAMClient, _field, _items


STATE_TYPE = "organizational_state"
STATE_SCHEMA = "organizational-state-v1"
STATE_KINDS = frozenset(
    {"action_item", "decision", "risk", "issue", "dependency", "approval", "conflict"}
)
LIFECYCLE_STATUSES = frozenset(
    {
        "proposed",
        "open",
        "pending_approval",
        "in_progress",
        "blocked",
        "decided",
        "approved",
        "rejected",
        "completed",
        "resolved",
        "cancelled",
        "superseded",
        "unknown",
    }
)
TERMINAL_STATUSES = frozenset({"decided", "approved", "rejected", "completed", "resolved", "cancelled", "superseded"})
ROLE_PRECEDENCE = {
    "creates": 0,
    "supports": 1,
    "updates": 2,
    "contradicts": 3,
    "resolves": 4,
    "supersedes": 5,
}
REGISTRY_ID = "management-agenda-ami-es2002-v1"
ENTITY_ROWS = (
    {
        "entity_kind": "project",
        "canonical_id": "project-ami-es2002",
        "display_name": "Real Reaction remote control project",
        "aliases": ["ami-es2002", "ES2002", "remote control project"],
        "filter_field": "project_id",
    },
    {
        "entity_kind": "employee",
        "canonical_id": "employee-laura-project-manager",
        "display_name": "Laura",
        "role": "Project Manager",
        "aliases": ["Laura", "Project Manager", "PM"],
        "filter_field": "accountable_entity_id",
    },
    {
        "entity_kind": "employee",
        "canonical_id": "employee-david-industrial-designer",
        "display_name": "David",
        "role": "Industrial Designer",
        "aliases": ["David", "Industrial Designer", "ID"],
        "filter_field": "accountable_entity_id",
    },
    {
        "entity_kind": "employee",
        "canonical_id": "employee-craig-interface-designer",
        "display_name": "Craig",
        "role": "User Interface Designer",
        "aliases": ["Craig", "User Interface Designer", "Interface Designer", "UID", "UI"],
        "filter_field": "accountable_entity_id",
    },
    {
        "entity_kind": "employee",
        "canonical_id": "employee-andrew-marketing-expert",
        "display_name": "Andrew",
        "role": "Marketing Expert",
        "aliases": ["Andrew", "Andrew Stokes-Rees", "Marketing Expert", "ME"],
        "filter_field": "accountable_entity_id",
    },
    {
        "entity_kind": "meeting",
        "canonical_id": "meeting-ami-es2002a-kickoff",
        "display_name": "ES2002a",
        "project_step_id": "project-step-ami-es2002-kickoff",
        "aliases": ["ES2002a", "kick-off", "kickoff"],
        "filter_field": "meeting_id",
    },
    {
        "entity_kind": "meeting",
        "canonical_id": "meeting-ami-es2002b-functional-design",
        "display_name": "ES2002b",
        "project_step_id": "project-step-ami-es2002-functional-design",
        "aliases": ["ES2002b", "functional design", "second meeting"],
        "filter_field": "meeting_id",
    },
    {
        "entity_kind": "meeting",
        "canonical_id": "meeting-ami-es2002c-conceptual-design",
        "display_name": "ES2002c",
        "project_step_id": "project-step-ami-es2002-conceptual-design",
        "aliases": ["ES2002c", "conceptual design", "third meeting"],
        "filter_field": "meeting_id",
    },
    {
        "entity_kind": "meeting",
        "canonical_id": "meeting-ami-es2002d-detailed-design",
        "display_name": "ES2002d",
        "project_step_id": "project-step-ami-es2002-detailed-design",
        "aliases": ["ES2002d", "detailed design", "fourth meeting", "final meeting"],
        "filter_field": "meeting_id",
    },
)


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _labels(item: dict[str, Any]) -> set[str]:
    values = [item["canonical_id"], item["display_name"], *item["aliases"]]
    if item.get("role"):
        values.append(item["role"])
    return {_normalize_label(str(value)) for value in values}


def resolve_entities(
    query: str | None = None,
    entity_kind: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    normalized = _normalize_label(query) if query else ""
    tokens = set(normalized.split())
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in ENTITY_ROWS:
        if entity_kind and row["entity_kind"] != entity_kind:
            continue
        labels = _labels(row)
        if not normalized:
            score = 3
        elif normalized in labels:
            score = 0
        elif any(label.startswith(normalized) for label in labels):
            score = 1
        elif any(normalized in label or tokens <= set(label.split()) for label in labels):
            score = 2
        else:
            continue
        ranked.append((score, str(row["canonical_id"]), row))
    matches = [dict(row) for _, _, row in sorted(ranked, key=lambda value: value[:2])[:limit]]
    return {
        "ok": True,
        "registry_id": REGISTRY_ID,
        "match_count": len(matches),
        "matches": matches,
        "next_tool": "ram_search_state",
    }


def canonical_entity(value: str | None, kind: str) -> str | None:
    if value is None:
        return None
    normalized = _normalize_label(value)
    matches = {
        str(row["canonical_id"])
        for row in ENTITY_ROWS
        if row["entity_kind"] == kind and normalized in _labels(row)
    }
    if len(matches) != 1:
        raise PluginError(
            "entity_not_found",
            f"The {kind} is unknown or ambiguous. Use context_resolve_entities first.",
        )
    return matches.pop()


def _attribute(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        key, nested = next(iter(value.items()))
        if key in {"string", "number", "boolean", "strings", "numbers", "booleans"}:
            return nested
    return value


def _attributes(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("attributes")
    if not isinstance(raw, dict):
        return {}
    return {str(key): _attribute(value) for key, value in raw.items()}


def _revision_key(value: Any) -> tuple[tuple[int, Any], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.findall(r"\d+|\D+", str(value or ""))
    )


def _sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    attributes = _attributes(record)
    return (
        str(attributes.get("observed_at", "")),
        _revision_key(attributes.get("source_revision")),
        ROLE_PRECEDENCE.get(str(attributes.get("evidence_role", "")), -1),
        str(_field(record, "updatedAt", "updated_at") or ""),
        str(record.get("id") or ""),
    )


def _scope_matches(record: dict[str, Any], config: Config) -> bool:
    attributes = _attributes(record)
    namespace = record.get("namespace")
    namespace_matches = namespace in {None, ""} or (
        isinstance(namespace, str) and namespace.casefold() == config.namespace.casefold()
    )
    return (
        _field(record, "ownerId", "owner_id") == config.agenda_owner_id
        and _field(record, "memoryType", "memory_type") == STATE_TYPE
        and attributes.get("schema_version") == STATE_SCHEMA
        and namespace_matches
    )


def _duplicate_key(record: dict[str, Any]) -> str:
    attributes = _attributes(record)
    material = {
        "text": record.get("text"),
        "state_id": attributes.get("state_id"),
        "evidence_role": attributes.get("evidence_role"),
        "subject": attributes.get("subject"),
        "observed_at": attributes.get("observed_at"),
        "source_artifact_id": attributes.get("source_artifact_id"),
        "source_revision": attributes.get("source_revision"),
        "evidence_locator": attributes.get("evidence_locator"),
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)


def _observation(record: dict[str, Any]) -> dict[str, Any]:
    attributes = _attributes(record)
    return {
        "memory_id": record.get("id"),
        "text": record.get("text"),
        "evidence_role": attributes.get("evidence_role"),
        "lifecycle_status": attributes.get("lifecycle_status"),
        "observed_at": attributes.get("observed_at"),
        "effective_at": attributes.get("effective_at"),
        "source_artifact_id": attributes.get("source_artifact_id"),
        "source_revision": attributes.get("source_revision"),
        "evidence_locator": attributes.get("evidence_locator"),
        "sources": record.get("sources") if isinstance(record.get("sources"), list) else [],
    }


def reconcile_states(
    records: list[dict[str, Any]],
    config: Config,
    lifecycle_status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Reconcile ranked observations without hiding conflicts or terminal states."""

    scoped = [record for record in records if _scope_matches(record, config)]
    rejected = len(records) - len(scoped)

    unique_by_key: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for record in scoped:
        key = _duplicate_key(record)
        previous = unique_by_key.get(key)
        if previous is not None:
            duplicates += 1
        if previous is None or _sort_key(record) > _sort_key(previous):
            unique_by_key[key] = record
    unique = list(unique_by_key.values())

    latest_revision: dict[str, tuple[tuple[int, Any], ...]] = {}
    for record in unique:
        attributes = _attributes(record)
        artifact = attributes.get("source_artifact_id")
        if isinstance(artifact, str) and artifact:
            latest_revision[artifact] = max(
                latest_revision.get(artifact, ()),
                _revision_key(attributes.get("source_revision")),
            )
    current_revision: list[dict[str, Any]] = []
    old_revisions = 0
    for record in unique:
        attributes = _attributes(record)
        artifact = attributes.get("source_artifact_id")
        if (
            isinstance(artifact, str)
            and artifact
            and _revision_key(attributes.get("source_revision")) < latest_revision[artifact]
        ):
            old_revisions += 1
            continue
        current_revision.append(record)

    grouped: dict[str, list[dict[str, Any]]] = {}
    state_rank: dict[str, int] = {}
    for rank, record in enumerate(current_revision):
        state_id = _attributes(record).get("state_id")
        if isinstance(state_id, str) and state_id:
            grouped.setdefault(state_id, []).append(record)
            state_rank.setdefault(state_id, rank)

    superseded_by: dict[str, set[str]] = {}
    for replacement_id, evidence in grouped.items():
        for record in evidence:
            replaced = _attributes(record).get("supersedes_state_ids")
            if isinstance(replaced, list):
                for state_id in replaced:
                    if isinstance(state_id, str) and state_id:
                        superseded_by.setdefault(state_id, set()).add(replacement_id)

    states: list[dict[str, Any]] = []
    conflict_count = 0
    for state_id in sorted(grouped, key=state_rank.get):
        ordered = sorted(grouped[state_id], key=_sort_key)
        current = ordered[-1]
        attributes = _attributes(current)
        contradictions = [
            _observation(record)
            for record in ordered
            if _attributes(record).get("evidence_role") == "contradicts"
        ]
        status = str(attributes.get("lifecycle_status") or "unknown")
        replacement_ids = sorted(superseded_by.get(state_id, set()))
        if replacement_ids:
            status = "superseded"
        conflict = bool(contradictions)
        if conflict:
            conflict_count += 1
        state = {
            "state_id": state_id,
            "state_kind": attributes.get("state_kind"),
            "lifecycle_status": status,
            "terminal": status in TERMINAL_STATUSES,
            "subject": attributes.get("subject") or current.get("text"),
            "project_id": attributes.get("project_id"),
            "project_step_id": attributes.get("project_step_id"),
            "meeting_id": attributes.get("meeting_id"),
            "accountable_entity_id": attributes.get("accountable_entity_id"),
            "requested_decision": attributes.get("requested_decision"),
            "impact": attributes.get("impact"),
            "due_at": attributes.get("due_at"),
            "resolved_at": attributes.get("resolved_at"),
            "superseded_by": replacement_ids,
            "has_conflict": conflict,
            "conflicting_observations": contradictions,
            "observation_count": len(ordered),
            "observations": [_observation(record) for record in ordered],
        }
        if lifecycle_status is None or status == lifecycle_status:
            states.append(state)

    return {
        "ok": True,
        "states": states[:limit],
        "has_more": len(states) > limit,
        "diagnostics": {
            "retrieved_observations": len(records),
            "out_of_scope_rejected": rejected,
            "duplicates_removed": duplicates,
            "old_source_revisions_removed": old_revisions,
            "reconciled_states": len(grouped),
            "conflicted_states": conflict_count,
        },
    }


class PluginService:
    """One local service surface over RAM and Playbook."""

    def __init__(
        self,
        config: Config,
        ram: RAMClient,
        playbook: PlaybookClient,
        editor: Any,
    ) -> None:
        self.config = config
        self.ram = ram
        self.playbook = playbook
        self.editor = editor

    def editor_status(self) -> dict[str, Any]:
        return self.editor.status()

    def editor_search(self, query: str) -> dict[str, Any]:
        return self.editor.search(query)

    def editor_publish(self, fact: str) -> dict[str, Any]:
        return self.editor.publish(fact)

    def editor_update(self, memory_id: str, fact: str) -> dict[str, Any]:
        return self.editor.update(memory_id, fact)

    def system_status(self) -> dict[str, Any]:
        ram_status: dict[str, Any] = {
            "status": "available",
            "endpoint_sha256": hashlib.sha256(self.config.endpoint.encode()).hexdigest(),
            "credential_configured": bool(self.config.api_key),
            "required_operations": ["search", "get", "evidence"],
        }
        try:
            self.ram.search(self._state_request(None, {}, 1, None))
        except Exception:
            ram_status["status"] = "unavailable"

        playbook_status: dict[str, Any] = {
            "status": "available",
            "endpoint_sha256": hashlib.sha256(self.config.playbook_mcp_url.encode()).hexdigest(),
            "credential_configured": bool(self.config.playbook_api_key),
            "required_read_tools": sorted(ALLOWED_TOOLS),
        }
        try:
            inventory = self.playbook.inventory()
            missing = sorted(ALLOWED_TOOLS - set(inventory))
            playbook_status["advertised_tool_count"] = len(inventory)
            if missing:
                playbook_status["status"] = "contract_error"
                playbook_status["missing_read_tools"] = missing
        except PluginError as error:
            playbook_status["status"] = error.code

        return {
            "ok": ram_status["status"] == playbook_status["status"] == "available",
            "version": VERSION,
            "upstreams": {"ram": ram_status, "playbook": playbook_status},
        }

    def context_resolve_entities(
        self,
        query: str | None = None,
        entity_kind: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return resolve_entities(query, entity_kind, limit)

    def _state_request(
        self,
        text: str | None,
        attributes: dict[str, str],
        limit: int,
        similarity_threshold: float | None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {
            "ownerId": {"eq": self.config.agenda_owner_id},
            "memoryType": {"eq": STATE_TYPE},
            "attributes": {
                "schema_version": {"string": STATE_SCHEMA},
                **{key: {"string": value} for key, value in attributes.items()},
            },
        }
        request: dict[str, Any] = {"filter": filters, "filterOp": "all", "limit": limit}
        if text is not None:
            request["text"] = text
        if similarity_threshold is not None:
            request["similarityThreshold"] = similarity_threshold
        return request

    def ram_search_state(
        self,
        text: str | None = None,
        state_kind: str | None = None,
        lifecycle_status: str | None = None,
        project_id: str | None = None,
        meeting_id: str | None = None,
        accountable_entity: str | None = None,
        limit: int = 20,
        similarity_threshold: float | None = None,
    ) -> dict[str, Any]:
        attributes = {
            key: value
            for key, value in {
                "state_kind": state_kind,
                "project_id": canonical_entity(project_id, "project"),
                "meeting_id": canonical_entity(meeting_id, "meeting"),
                "accountable_entity_id": canonical_entity(accountable_entity, "employee"),
            }.items()
            if value is not None
        }
        request = self._state_request(text, attributes, 100, similarity_threshold)
        records = _items(self.ram.search(request))
        result = reconcile_states(records, self.config, lifecycle_status, limit)
        result.update(
            {
                "schema_version": STATE_SCHEMA,
                "owner_id": self.config.agenda_owner_id,
                "applied_filters": attributes,
            }
        )
        return result

    def ram_get_evidence(
        self,
        memory_id: str,
        source_id: str,
        limit: int = 100,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        response = self.ram.evidence(memory_id, source_id, limit, page_token)
        source = response.get("source")
        if not isinstance(source, dict):
            raise PluginError("ram_contract_error", "RAM returned incompatible source evidence.")
        returned_id = _field(source, "sourceId", "source_id")
        if returned_id not in {None, source_id}:
            raise PluginError("scope_mismatch", "RAM returned evidence for a different source.")
        return {
            "ok": True,
            "memory_id": memory_id,
            "source": source,
            "next_page_token": _field(response, "evidenceNextPageToken", "evidence_next_page_token"),
        }

    def playbook_discover(
        self,
        query: str,
        limit: int = 10,
        pinned_entry_key: str | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"query": query, "limit": limit}
        if pinned_entry_key:
            arguments["pinned_entries"] = [{"entry_key": pinned_entry_key}]
        return {"ok": True, **self.playbook.call("discover_entries", arguments)}

    def playbook_load_skill(self, entry_id: str, version: int) -> dict[str, Any]:
        return {
            "ok": True,
            **self.playbook.call("load_skill", {"entry_id": entry_id, "version": version}),
        }

    def playbook_fetch_resource(self, uri: str) -> dict[str, Any]:
        return {"ok": True, **self.playbook.call("fetch_resource", {"uri": uri})}

    def agenda_prepare(
        self,
        meeting_date: str,
        lookback_days: int = 30,
        max_items: int = 8,
        focus: str | None = None,
    ) -> dict[str, Any]:
        from .agenda import prepare_agenda

        return prepare_agenda(self, meeting_date, lookback_days, max_items, focus)

