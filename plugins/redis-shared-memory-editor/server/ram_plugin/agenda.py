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
    state_result = service.ram_search_state(
        text=focus,
        project_id=PROJECT_ID,
        limit=100,
    )
    cutoff = meeting_day - timedelta(days=lookback_days)
    qualified: list[tuple[str, str, str, dict[str, Any]]] = []
    deferred: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = []

    for state in state_result.get("states", []):
        if not isinstance(state, dict):
            continue
        state_id = state.get("state_id")
        reasons: list[str] = []
        status = state.get("lifecycle_status")
        if status in TERMINAL_STATUSES:
            reasons.append("terminal_or_superseded")
        if state.get("has_conflict"):
            reasons.append("unresolved_conflict")
            conflicts.append(
                {
                    "state_id": state_id,
                    "subject": state.get("subject"),
                    "observations": state.get("conflicting_observations", []),
                }
            )
        for field, reason in (
            ("accountable_entity_id", "owner_missing"),
            ("requested_decision", "management_question_missing"),
            ("impact", "material_impact_missing"),
        ):
            if not state.get(field):
                reasons.append(reason)

        observations = state.get("observations") or []
        latest = observations[-1] if observations and isinstance(observations[-1], dict) else {}
        observed = _date(latest.get("observed_at"))
        if observed is None:
            reasons.append("observation_date_missing")
        elif observed > meeting_day:
            reasons.append("evidence_after_meeting_date")
        elif observed < cutoff and status in {"unknown", "proposed"}:
            reasons.append("outside_lookback_without_current_status")

        references: list[dict[str, Any]] = []
        if not reasons:
            references = _references(service, state)
            if not references:
                reasons.append("source_evidence_unavailable")
        if reasons:
            deferred.append(
                {
                    "state_id": state_id,
                    "subject": state.get("subject"),
                    "reasons": sorted(set(reasons)),
                }
            )
            continue

        impact = str(state["impact"])
        requested = str(state["requested_decision"])
        due_at = state.get("due_at")
        why_now = f"{impact} Review requested for {meeting_date}."
        if due_at:
            why_now = f"{impact} The recorded decision horizon is {due_at}."
        item = {
            "title": str(state.get("subject") or state_id)[:160],
            "management_question": requested,
            "why_now": why_now,
            "current_state": str(state.get("subject") or ""),
            "owner": state["accountable_entity_id"],
            "requested_decision": requested,
            "timebox_minutes": 10,
            "confidence": "high" if len(references) > 1 else "medium",
            "evidence_references": references,
        }
        qualified.append(
            (
                str(due_at or "9999-12-31"),
                item["title"],
                str(state_id),
                item,
            )
        )

    qualified.sort(key=lambda value: value[:2])
    for _, title, state_id, _ in qualified[max_items:]:
        deferred.append(
            {
                "state_id": state_id,
                "subject": title,
                "reasons": ["agenda_capacity"],
            }
        )
    items = [item for _, _, _, item in qualified[:max_items]]
    if not items:
        warnings.append(
            "No decision-ready item had current, non-conflicting state plus traversable source evidence."
        )
    return {
        "ok": True,
        "meeting_date": meeting_date,
        "lookback_days": lookback_days,
        "agenda_items": items,
        "deferred_candidates": deferred,
        "conflicts": conflicts,
        "warnings": warnings,
        "retrieval_diagnostics": state_result.get("diagnostics", {}),
        "playbook": policy,
    }

