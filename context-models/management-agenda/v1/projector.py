"""Deterministic current-state projections over immutable RAM observations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

PROJECTION_MEMORY_TYPE = "organizational_state_projection"
PROJECTION_SCHEMA_VERSION = "organizational-state-projection-v1"
STATE_BEARING_ROLES = frozenset({"creates", "updates", "resolves", "supersedes"})
ROLE_PRECEDENCE = {
    "supports": 0,
    "creates": 1,
    "updates": 2,
    "resolves": 3,
    "supersedes": 4,
    "contradicts": 5,
}


def _revision_key(value: Any) -> tuple[tuple[int, Any], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.findall(r"\d+|\D+", str(value or ""))
    )


def event_key(record: dict[str, Any]) -> tuple[Any, ...]:
    attributes = record.get("attributes") or {}
    sequence = attributes.get("event_sequence", 0)
    offset = attributes.get("source_offset_ms", 0)
    return (
        str(attributes.get("observed_at", "")),
        sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else 0,
        offset if isinstance(offset, int) and not isinstance(offset, bool) else 0,
        ROLE_PRECEDENCE.get(str(attributes.get("evidence_role", "")), -1),
        _revision_key(attributes.get("source_revision")),
        str(attributes.get("source_artifact_id", "")),
        str(record.get("id", "")),
    )


def _effective_sequence(record: dict[str, Any], policy: dict[str, Any]) -> int:
    attributes = record.get("attributes") or {}
    sequence = attributes.get("event_sequence", 0)
    resolved = sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else 0
    locator = str(attributes.get("evidence_locator", "")).casefold()
    for rule in policy.get("historicalLocatorSequences", []):
        marker = rule.get("locatorContains") if isinstance(rule, dict) else None
        candidate = rule.get("eventSequence") if isinstance(rule, dict) else None
        if (
            isinstance(marker, str)
            and marker.casefold() in locator
            and isinstance(candidate, int)
            and not isinstance(candidate, bool)
        ):
            return candidate
    return resolved


def _resolved_event_key(
    record: dict[str, Any], policy: dict[str, Any]
) -> tuple[Any, ...]:
    key = event_key(record)
    return (key[0], _effective_sequence(record, policy), *key[2:])


def _family_index(policy: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for family in policy.get("families", []):
        family_id = family.get("stateFamilyId")
        members = family.get("memberStateIds")
        if not isinstance(family_id, str) or not family_id or not isinstance(members, list):
            raise ValueError("state-family policy contains an invalid family")
        for member in members:
            if not isinstance(member, str) or not member or member in index:
                raise ValueError("state-family policy contains an invalid or duplicate member")
            index[member] = family_id
    return index


def _family_id(
    record: dict[str, Any], aliases: dict[str, str], policy: dict[str, Any]
) -> str | None:
    attributes = record.get("attributes")
    state_id = attributes.get("state_id") if isinstance(attributes, dict) else None
    if not isinstance(state_id, str) or not state_id:
        return None
    if state_id in aliases:
        return aliases[state_id]
    subject = f"{attributes.get('subject', '')} {record.get('text', '')}".casefold()
    state_kind = attributes.get("state_kind")
    for rule in policy.get("matchRules", []):
        if not isinstance(rule, dict):
            raise ValueError("state-family policy contains an invalid match rule")
        family_id = rule.get("stateFamilyId")
        kinds = rule.get("stateKinds", [])
        phrases = rule.get("anySubjectContains", [])
        if (
            not isinstance(family_id, str)
            or not family_id
            or not isinstance(kinds, list)
            or not isinstance(phrases, list)
        ):
            raise ValueError("state-family policy contains an invalid match rule")
        if kinds and state_kind not in kinds:
            continue
        if any(isinstance(phrase, str) and phrase.casefold() in subject for phrase in phrases):
            return family_id
    return state_id


def _current_revisions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, Any], ...]] = {}
    for record in records:
        attributes = record.get("attributes") or {}
        artifact = attributes.get("source_artifact_id")
        if isinstance(artifact, str) and artifact:
            latest[artifact] = max(
                latest.get(artifact, ()), _revision_key(attributes.get("source_revision"))
            )
    selected: list[dict[str, Any]] = []
    for record in records:
        attributes = record.get("attributes") or {}
        artifact = attributes.get("source_artifact_id")
        if (
            isinstance(artifact, str)
            and artifact
            and _revision_key(attributes.get("source_revision")) < latest[artifact]
        ):
            continue
        selected.append(record)
    return selected


def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        attributes = record.get("attributes") or {}
        material = {
            "text": record.get("text"),
            "state_id": attributes.get("state_id"),
            "subject": attributes.get("subject"),
            "evidence_role": attributes.get("evidence_role"),
            "source_artifact_id": attributes.get("source_artifact_id"),
            "source_revision": attributes.get("source_revision"),
            "evidence_locator": attributes.get("evidence_locator"),
        }
        key = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        previous = unique.get(key)
        if previous is None or event_key(record) > event_key(previous):
            unique[key] = record
    return list(unique.values())


@dataclass(frozen=True)
class ProjectionMemory:
    memory_id: str
    text: str
    attributes: dict[str, Any]

    def sdk_input(self, owner_id: str) -> dict[str, Any]:
        return {
            "id": self.memory_id,
            "text": self.text,
            "owner_id": owner_id,
            "memory_type": PROJECTION_MEMORY_TYPE,
            "topics": [
                "organizational-state-current",
                self.attributes["state_kind"],
                self.attributes["lifecycle_status"],
                self.attributes["project_id"],
            ],
            "attributes": self.attributes,
        }


def build_projections(
    observations: list[dict[str, Any]], policy: dict[str, Any]
) -> tuple[ProjectionMemory, ...]:
    """Build one current projection per configured or fallback state family."""

    policy_id = policy.get("policyId")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("state-family policy identifier is missing")
    aliases = _family_index(policy)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in _current_revisions(_deduplicate(observations)):
        family_id = _family_id(record, aliases, policy)
        if family_id is None:
            continue
        grouped.setdefault(family_id, []).append(record)

    projections: list[ProjectionMemory] = []
    for family_id in sorted(grouped):
        ordered = sorted(grouped[family_id], key=lambda record: _resolved_event_key(record, policy))
        state_bearing = [
            record
            for record in ordered
            if (record.get("attributes") or {}).get("evidence_role") in STATE_BEARING_ROLES
            and (record.get("attributes") or {}).get("state_kind") != "conflict"
        ]
        current = state_bearing[-1] if state_bearing else ordered[-1]
        current_key = _resolved_event_key(current, policy)
        conflicts = [
            record
            for record in ordered
            if (
                (record.get("attributes") or {}).get("state_kind") == "conflict"
                or (record.get("attributes") or {}).get("evidence_role") == "contradicts"
            )
            and (not state_bearing or _resolved_event_key(record, policy) >= current_key)
        ]
        attributes = current["attributes"]
        memory_ids = [str(record["id"]) for record in ordered if record.get("id")]
        conflict_ids = [str(record["id"]) for record in conflicts if record.get("id")]
        memory_id = "projection-" + hashlib.sha256(family_id.encode()).hexdigest()[:48]
        projected = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "state_id": family_id,
            "state_kind": attributes["state_kind"],
            "lifecycle_status": attributes["lifecycle_status"],
            "subject": attributes["subject"],
            "project_id": attributes["project_id"],
            "project_step_id": attributes.get("project_step_id", ""),
            "meeting_id": attributes.get("meeting_id", ""),
            "accountable_entity_id": attributes.get("accountable_entity_id", ""),
            "related_entity_ids": attributes.get("related_entity_ids", []),
            "valid_at": attributes["observed_at"],
            "event_sequence": _effective_sequence(current, policy),
            "source_offset_ms": attributes["source_offset_ms"],
            "due_at": attributes.get("due_at", ""),
            "resolved_at": attributes.get("resolved_at", ""),
            "requested_decision": attributes.get("requested_decision", ""),
            "impact": attributes.get("impact", ""),
            "conflict_status": "unresolved" if conflicts else "none",
            "supporting_memory_ids": memory_ids,
            "conflicting_memory_ids": conflict_ids,
            "observation_count": len(ordered),
            "current_memory_id": str(current["id"]),
            "resolution_policy_id": policy_id,
        }
        projections.append(ProjectionMemory(memory_id, projected["subject"], projected))
    return tuple(projections)
