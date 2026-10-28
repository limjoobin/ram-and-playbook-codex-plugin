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
RELATION_ASSERTION_STATUSES = frozenset({"proposed", "confirmed", "rejected"})
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
            "relations": attributes.get("relations"),
        }
        key = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        previous = unique.get(key)
        if previous is None or event_key(record) > event_key(previous):
            unique[key] = record
    return list(unique.values())


def _relation_contract(
    policy: dict[str, Any],
) -> tuple[frozenset[str], str, dict[tuple[str, str], str]]:
    relation_policy = policy.get("relationPolicy")
    if not isinstance(relation_policy, dict):
        raise ValueError("projection policy is missing relationPolicy")
    predicates = relation_policy.get("allowedPredicates")
    confirmation = relation_policy.get("confirmationStatus")
    effects = relation_policy.get("lifecycleEffects")
    if (
        not isinstance(predicates, list)
        or not predicates
        or any(not isinstance(item, str) or not item for item in predicates)
        or len(set(predicates)) != len(predicates)
        or not isinstance(confirmation, str)
        or confirmation not in RELATION_ASSERTION_STATUSES
        or not isinstance(effects, list)
    ):
        raise ValueError("projection relation policy is invalid")
    lifecycle_effects: dict[tuple[str, str], str] = {}
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError("projection relation lifecycle effect is invalid")
        predicate = effect.get("predicate")
        target_kinds = effect.get("targetKinds")
        target_status = effect.get("targetStatus")
        if (
            predicate not in predicates
            or not isinstance(target_kinds, list)
            or not target_kinds
            or any(item not in STATE_KINDS for item in target_kinds)
            or target_status not in LIFECYCLE_STATUSES
        ):
            raise ValueError("projection relation lifecycle effect is invalid")
        for target_kind in target_kinds:
            key = (predicate, target_kind)
            if key in lifecycle_effects:
                raise ValueError("projection relation lifecycle effect is duplicated")
            lifecycle_effects[key] = target_status
    return frozenset(predicates), confirmation, lifecycle_effects


def _relation_edges(
    record: dict[str, Any], allowed_predicates: frozenset[str]
) -> tuple[dict[str, Any], ...]:
    attributes = record.get("attributes") or {}
    relations = attributes.get("relations")
    if relations is None or relations == "":
        return ()
    if isinstance(relations, dict) and set(relations) == {"object"}:
        relations = relations["object"]
    if not isinstance(relations, dict) or not isinstance(relations.get("edges"), list):
        raise ValueError("organizational-state relations must contain an edges array")
    normalized: list[dict[str, Any]] = []
    for edge in relations["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("organizational-state relation edge is invalid")
        predicate = edge.get("predicate")
        target_state_id = edge.get("target_state_id")
        confidence = edge.get("confidence")
        assertion_status = edge.get("assertion_status")
        evidence_memory_ids = edge.get("evidence_memory_ids")
        if (
            predicate not in allowed_predicates
            or not isinstance(target_state_id, str)
            or not target_state_id
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
            or assertion_status not in RELATION_ASSERTION_STATUSES
            or not isinstance(evidence_memory_ids, list)
            or any(not isinstance(item, str) or not item for item in evidence_memory_ids)
        ):
            raise ValueError("organizational-state relation edge is invalid")
        normalized.append(
            {
                "predicate": predicate,
                "target_state_id": target_state_id,
                "confidence": float(confidence),
                "assertion_status": assertion_status,
                "evidence_memory_ids": list(evidence_memory_ids),
            }
        )
    return tuple(normalized)


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
    allowed_predicates, confirmed_status, lifecycle_effects = _relation_contract(policy)
    selected = _current_revisions(_deduplicate(observations))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in selected:
        family_id = _family_id(record, aliases, policy)
        if family_id is None:
            continue
        grouped.setdefault(family_id, []).append(record)

    projected_by_family: dict[str, dict[str, Any]] = {}
    current_keys: dict[str, tuple[Any, ...]] = {}
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
        projected_by_family[family_id] = {"memory_id": memory_id, "attributes": projected}
        current_keys[family_id] = current_key

    observation_ids = {
        str(record["id"])
        for record in selected
        if isinstance(record.get("id"), str) and record["id"]
    }
    confirmed_edges: list[tuple[tuple[Any, ...], str, dict[str, Any], dict[str, Any]]] = []
    for record in selected:
        source_family_id = _family_id(record, aliases, policy)
        if source_family_id is None:
            continue
        for edge in _relation_edges(record, allowed_predicates):
            if edge["assertion_status"] != confirmed_status:
                continue
            confirmed_edges.append(
                (_resolved_event_key(record, policy), source_family_id, edge, record)
            )

    for relation_key, source_family_id, edge, record in sorted(
        confirmed_edges,
        key=lambda item: (item[0], item[1], item[2]["predicate"], item[2]["target_state_id"]),
    ):
        target_family_id = aliases.get(edge["target_state_id"], edge["target_state_id"])
        source_projection = projected_by_family.get(source_family_id)
        target_projection = projected_by_family.get(target_family_id)
        if source_projection is None or target_projection is None:
            raise ValueError("confirmed organizational-state relation references an unknown state")
        if source_family_id == target_family_id:
            raise ValueError("confirmed organizational-state relation cannot target its source")
        source_attributes = source_projection["attributes"]
        target_attributes = target_projection["attributes"]
        if source_attributes["project_id"] != target_attributes["project_id"]:
            raise ValueError("confirmed organizational-state relation crosses projects")

        relation_memory_id = record.get("id")
        if isinstance(relation_memory_id, str) and relation_memory_id:
            supports = target_attributes["supporting_memory_ids"]
            if relation_memory_id not in supports:
                supports.append(relation_memory_id)
        for evidence_id in edge["evidence_memory_ids"]:
            if (
                evidence_id in observation_ids
                and evidence_id not in target_attributes["supporting_memory_ids"]
            ):
                target_attributes["supporting_memory_ids"].append(evidence_id)

        target_kind = str(target_attributes["state_kind"])
        target_status = lifecycle_effects.get((edge["predicate"], target_kind))
        if target_status is None or relation_key < current_keys[target_family_id]:
            continue
        target_attributes["lifecycle_status"] = target_status
        relation_attributes = record.get("attributes") or {}
        target_attributes["resolved_at"] = (
            relation_attributes.get("resolved_at")
            or relation_attributes.get("effective_at")
            or relation_attributes.get("observed_at")
            or target_attributes.get("resolved_at", "")
        )
        if edge["predicate"] == "resolves" and target_kind == "conflict":
            target_attributes["conflict_status"] = "none"
            target_attributes["conflicting_memory_ids"] = []

    return tuple(
        ProjectionMemory(
            projected_by_family[family_id]["memory_id"],
            projected_by_family[family_id]["attributes"]["subject"],
            projected_by_family[family_id]["attributes"],
        )
        for family_id in sorted(projected_by_family)
    )
