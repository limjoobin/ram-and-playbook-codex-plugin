"""Evidence-bound management agenda preparation using a runtime Playbook Skill."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from typing import Any

from .config import PluginError
from .management import TERMINAL_STATUSES
from .ram import _field


SKILL_KEY = "prepare-management-review-agenda"
PROJECT_ID = "project-ami-es2002"
REQUIRED_RESOURCES = (
    "references/meeting-charter.md",
    "references/agenda-qualification-rules.md",
    "references/agenda-item-output-schema.md",
    "references/evidence-lifecycle.md",
    "references/abstention-and-escalation.md",
)
CONFIRMED_DECISION_STATUSES = frozenset({"decided", "approved"})
COMPLETED_WORK_STATUSES = frozenset({"completed", "resolved"})
OPEN_WORK_STATUSES = frozenset(
    {"proposed", "open", "pending_approval", "in_progress", "blocked"}
)
RETRIEVAL_STATE_KINDS = (
    "action_item",
    "decision",
    "approval",
    "risk",
    "issue",
    "dependency",
    "conflict",
)
ACTION_STATUS_ORDER = {
    "blocked": 0,
    "pending_approval": 1,
    "in_progress": 2,
    "open": 3,
    "proposed": 4,
    "completed": 5,
    "resolved": 6,
    "cancelled": 7,
    "superseded": 8,
    "rejected": 9,
    "unknown": 10,
}


def _field_value(value: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return None


def _entries(result: dict[str, Any]) -> list[dict[str, Any]]:
    for name in ("pinnedEntries", "pinned_entries", "discoveredEntries", "entries", "results"):
        value = result.get(name)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _load_policy(playbook: Any) -> dict[str, Any]:
    discovery = playbook.call(
        "discover_entries",
        {
            "query": "prepare a decision-focused management review agenda from current cited evidence",
            "pinned_entries": [{"entry_key": SKILL_KEY}],
            "limit": 5,
        },
    )
    selected = None
    for entry in _entries(discovery):
        key = _field_value(entry, "entryKey", "entry_key", "key")
        if key == SKILL_KEY:
            selected = entry
            break
    if selected is None:
        raise PluginError(
            "playbook_contract_error",
            "The required management-agenda Playbook entry was not discovered.",
        )
    entry_id = _field_value(selected, "entryId", "entry_id", "id")
    version = selected.get("version")
    if not isinstance(entry_id, str) or not entry_id or isinstance(version, bool) or not isinstance(version, int):
        raise PluginError(
            "playbook_contract_error",
            "The required management-agenda Playbook entry has no exact version.",
        )

    loaded = playbook.call("load_skill", {"entry_id": entry_id, "version": version})
    if _field_value(loaded, "entryId", "entry_id") not in {None, entry_id}:
        raise PluginError("playbook_contract_error", "Playbook loaded a different entry.")
    if loaded.get("version") not in {None, version}:
        raise PluginError("playbook_contract_error", "Playbook loaded a different version.")
    content = loaded.get("content")
    if not isinstance(content, dict):
        raise PluginError("playbook_contract_error", "The Playbook Skill content is incomplete.")
    manifest = content.get("manifest")
    manifest_name = manifest.get("name") if isinstance(manifest, dict) else None
    if manifest_name != SKILL_KEY:
        raise PluginError("playbook_contract_error", "Playbook loaded an unexpected Skill manifest.")
    if not isinstance(content.get("instructions"), str) or not content["instructions"].strip():
        raise PluginError("playbook_contract_error", "The Playbook Skill has no instructions.")

    descriptors = content.get("resources")
    if not isinstance(descriptors, list):
        raise PluginError("playbook_contract_error", "The Playbook Skill has no resource inventory.")
    by_path: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        path = descriptor.get("path")
        if isinstance(path, str) and path not in by_path:
            by_path[path] = descriptor

    verified: dict[str, str] = {}
    for path in REQUIRED_RESOURCES:
        descriptor = by_path.get(path)
        if descriptor is None:
            raise PluginError("playbook_contract_error", f"The Playbook Skill is missing {path}.")
        uri, expected = descriptor.get("uri"), descriptor.get("digest")
        if not isinstance(uri, str) or not uri or not isinstance(expected, str):
            raise PluginError("playbook_contract_error", "A Playbook resource descriptor is incomplete.")
        fetched = playbook.call("fetch_resource", {"uri": uri})
        if fetched.get("uri") not in {None, uri} or fetched.get("digest") not in {None, expected}:
            raise PluginError("playbook_contract_error", "A Playbook resource identity changed while loading.")
        text = fetched.get("text")
        if not isinstance(text, str):
            raise PluginError("playbook_contract_error", "A required Playbook resource is not text.")
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected_hash = expected.removeprefix("sha256:")
        if actual != expected_hash:
            raise PluginError("playbook_digest_mismatch", "A Playbook resource failed digest verification.")
        verified[path] = expected

    digest = _field_value(selected, "contentDigest", "content_digest")
    if not isinstance(digest, str):
        digest = _field_value(loaded, "contentDigest", "content_digest")
    if not isinstance(digest, str):
        digest = "sha256:" + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "entry_id": entry_id,
        "version": version,
        "digest": digest,
        "resources": verified,
    }


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _source_id(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    value = _field(source, "sourceId", "source_id")
    return value if isinstance(value, str) and value else None


def _references(service: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    observations = state.get("observations")
    if not isinstance(observations, list):
        return references
    for observation in reversed(observations):
        if not isinstance(observation, dict):
            continue
        memory_id = observation.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            continue
        for source in observation.get("sources") or []:
            source_id = _source_id(source)
            if source_id is None or (memory_id, source_id) in seen:
                continue
            seen.add((memory_id, source_id))
            evidence = service.ram_get_evidence(memory_id, source_id, 100, None)
            resolved = evidence.get("source")
            passages = resolved.get("evidence") if isinstance(resolved, dict) else None
            if not passages:
                continue
            references.append(
                {
                    "memory_id": memory_id,
                    "source_id": source_id,
                    "source_artifact_id": observation.get("source_artifact_id"),
                    "source_revision": observation.get("source_revision"),
                    "evidence_locator": observation.get("evidence_locator"),
                }
            )
            if len(references) == 3:
                return references
    return references


def _linked_references(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact source links without opening every evidence passage."""

    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    observations = state.get("observations")
    if not isinstance(observations, list):
        return references
    for observation in reversed(observations):
        if not isinstance(observation, dict):
            continue
        memory_id = observation.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            continue
        for source in observation.get("sources") or []:
            source_id = _source_id(source)
            if source_id is None or (memory_id, source_id) in seen:
                continue
            seen.add((memory_id, source_id))
            references.append(
                {
                    "memory_id": memory_id,
                    "source_id": source_id,
                    "source_artifact_id": observation.get("source_artifact_id"),
                    "source_revision": observation.get("source_revision"),
                    "evidence_locator": observation.get("evidence_locator"),
                }
            )
            if len(references) == 3:
                return references
    return references


def _context_item(
    state: dict[str, Any], references: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "state_id": state.get("state_id"),
        "state_kind": state.get("state_kind"),
        "lifecycle_status": state.get("lifecycle_status"),
        "subject": state.get("subject"),
        "owner": state.get("accountable_entity_id") or "",
        "due_at": state.get("due_at") or "",
        "valid_at": state.get("valid_at") or "",
        "evidence_references": references,
    }


def _action_item_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("owner") or "~"),
        ACTION_STATUS_ORDER.get(str(item.get("lifecycle_status") or "unknown"), 99),
        str(item.get("due_at") or "9999-12-31"),
        str(item.get("subject") or ""),
        str(item.get("state_id") or ""),
    )


def _action_item_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_owner: dict[str, dict[str, Any]] = {}
    for item in items:
        status = str(item.get("lifecycle_status") or "unknown")
        owner = str(item.get("owner") or "unassigned")
        by_status[status] = by_status.get(status, 0) + 1
        owner_summary = by_owner.setdefault(owner, {"total": 0, "by_status": {}})
        owner_summary["total"] += 1
        owner_statuses = owner_summary["by_status"]
        owner_statuses[status] = owner_statuses.get(status, 0) + 1
    return {
        "total": len(items),
        "by_status": dict(sorted(by_status.items())),
        "by_owner": {owner: by_owner[owner] for owner in sorted(by_owner)},
    }


def _retrieve_current_states(
    service: Any, focus: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Enumerate the complete PoC state register with structured kind filters."""

    states: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "strategy": "structured-current-state-by-kind",
        "focus_used_for_ranking_only": bool(focus),
        "by_state_kind": {},
    }
    warnings: list[str] = []
    seen: set[str] = set()
    for state_kind in RETRIEVAL_STATE_KINDS:
        result = service.ram_search_state(
            text=focus,
            state_kind=state_kind,
            project_id=PROJECT_ID,
            limit=100,
        )
        returned = result.get("states")
        if not isinstance(returned, list):
            raise PluginError("ram_contract_error", "RAM returned an invalid state collection.")
        accepted = 0
        for state in returned:
            if not isinstance(state, dict) or state.get("state_kind") != state_kind:
                raise PluginError("ram_contract_error", "RAM returned a state outside its filter.")
            state_id = state.get("state_id")
            if not isinstance(state_id, str) or not state_id:
                raise PluginError("ram_contract_error", "RAM returned a state without an ID.")
            if state_id in seen:
                warnings.append(f"Duplicate current state was ignored: {state_id}.")
                continue
            seen.add(state_id)
            states.append(state)
            accepted += 1
        kind_diagnostics = result.get("diagnostics")
        diagnostics["by_state_kind"][state_kind] = {
            "returned_states": accepted,
            "has_more": bool(result.get("has_more")),
            **(kind_diagnostics if isinstance(kind_diagnostics, dict) else {}),
        }
        if result.get("has_more") or len(returned) >= 100:
            warnings.append(
                f"Current {state_kind} retrieval reached its 100-record safety bound."
            )
    diagnostics["total_current_states"] = len(states)
    return states, diagnostics, warnings


def prepare_agenda(
    service: Any,
    meeting_date: str,
    lookback_days: int = 30,
    max_items: int = 8,
    focus: str | None = None,
) -> dict[str, Any]:
    try:
        meeting_day = date.fromisoformat(meeting_date)
    except ValueError:
        raise PluginError("invalid_input", "meeting_date must use YYYY-MM-DD.") from None
    policy = _load_policy(service.playbook)
    states, retrieval_diagnostics, retrieval_warnings = _retrieve_current_states(
        service, focus
    )
    cutoff = meeting_day - timedelta(days=lookback_days)
    qualified: list[tuple[str, str, str, dict[str, Any]]] = []
    action_items: list[dict[str, Any]] = []
    confirmed_decisions: list[dict[str, Any]] = []
    completed_work: list[dict[str, Any]] = []
    open_work_items: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = list(retrieval_warnings)
    reference_cache: dict[str, list[dict[str, Any]]] = {}

    def references_for(state: dict[str, Any]) -> list[dict[str, Any]]:
        state_id = str(state.get("state_id") or "")
        if state_id not in reference_cache:
            reference_cache[state_id] = _references(service, state)
        return reference_cache[state_id]

    for state in states:
        state_id = state.get("state_id")
        reasons: list[str] = []
        status = state.get("lifecycle_status")
        state_kind = state.get("state_kind")
        has_conflict = bool(state.get("has_conflict"))
        if has_conflict:
            reasons.append("unresolved_conflict")
            conflicts.append(
                {
                    "state_id": state_id,
                    "subject": state.get("subject"),
                    "observations": state.get("conflicting_observations", []),
                }
            )

        observations = state.get("observations") or []
        latest = observations[-1] if observations and isinstance(observations[-1], dict) else {}
        observed = _date(latest.get("observed_at"))
        context_references = _linked_references(state)
        context = _context_item(state, context_references)
        if not context_references:
            reasons.append("source_evidence_unavailable")
        if state_kind == "action_item":
            action_items.append(context)
        if not has_conflict:
            if (
                state_kind in {"decision", "approval"}
                and status in CONFIRMED_DECISION_STATUSES
            ):
                confirmed_decisions.append(context)
            if (
                status in COMPLETED_WORK_STATUSES
                and observed is not None
                and observed >= cutoff
            ):
                completed_work.append(context)
            elif state_kind == "action_item" and status in OPEN_WORK_STATUSES:
                open_work_items.append(context)

        if status in TERMINAL_STATUSES:
            if reasons and not context_references:
                deferred.append(
                    {
                        "state_id": state_id,
                        "subject": state.get("subject"),
                        "reasons": sorted(set(reasons)),
                    }
                )
            continue

        for field, reason in (
            ("accountable_entity_id", "owner_missing"),
            ("requested_decision", "management_question_missing"),
            ("impact", "material_impact_missing"),
        ):
            if not state.get(field):
                reasons.append(reason)

        if observed is None:
            reasons.append("observation_date_missing")
        elif observed > meeting_day:
            reasons.append("evidence_after_meeting_date")
        elif observed < cutoff and status in {"unknown", "proposed"}:
            reasons.append("outside_lookback_without_current_status")

        if reasons:
            deferred.append(
                {
                    "state_id": state_id,
                    "subject": state.get("subject"),
                    "reasons": sorted(set(reasons)),
                }
            )
            continue

        qualified.append(
            (
                str(state.get("due_at") or "9999-12-31"),
                str(state.get("subject") or state_id)[:160],
                str(state_id),
                state,
            )
        )

    qualified.sort(key=lambda value: value[:2])
    items: list[dict[str, Any]] = []
    for _, title, state_id, state in qualified:
        if len(items) >= max_items:
            deferred.append(
                {
                    "state_id": state_id,
                    "subject": title,
                    "reasons": ["agenda_capacity"],
                }
            )
            continue
        references = references_for(state)
        if not references:
            deferred.append(
                {
                    "state_id": state_id,
                    "subject": title,
                    "reasons": ["source_evidence_unavailable"],
                }
            )
            continue
        impact = str(state["impact"])
        requested = str(state["requested_decision"])
        due_at = state.get("due_at")
        why_now = f"{impact} Review requested for {meeting_date}."
        if due_at:
            why_now = f"{impact} The recorded decision horizon is {due_at}."
        items.append(
            {
                "title": title,
                "management_question": requested,
                "why_now": why_now,
                "current_state": str(state.get("subject") or ""),
                "owner": state["accountable_entity_id"],
                "requested_decision": requested,
                "timebox_minutes": 10,
                "confidence": "high" if len(references) > 1 else "medium",
                "evidence_references": references,
            }
        )
    action_items.sort(key=_action_item_key)
    open_work_items.sort(key=_action_item_key)
    completed_work.sort(
        key=lambda item: (str(item.get("valid_at") or ""), str(item.get("state_id") or "")),
        reverse=True,
    )
    confirmed_decisions.sort(
        key=lambda item: (str(item.get("valid_at") or ""), str(item.get("state_id") or "")),
        reverse=True,
    )
    if not items:
        warnings.append(
            "No decision-ready item had current, non-conflicting state plus traversable source evidence."
        )
    return {
        "ok": True,
        "meeting_date": meeting_date,
        "lookback_days": lookback_days,
        "action_item_summary": _action_item_summary(action_items),
        "action_items": action_items,
        "confirmed_decisions": confirmed_decisions,
        "completed_work": completed_work,
        "open_work_items": open_work_items,
        "agenda_items": items,
        "deferred_candidates": deferred,
        "conflicts": conflicts,
        "warnings": warnings,
        "retrieval_diagnostics": {
            **retrieval_diagnostics,
            "returned_action_items": len(action_items),
            "returned_confirmed_decisions": len(confirmed_decisions),
            "returned_completed_work": len(completed_work),
            "returned_open_work_items": len(open_work_items),
        },
        "playbook": policy,
    }

