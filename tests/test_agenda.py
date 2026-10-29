from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.agenda import REQUIRED_RESOURCES  # noqa: E402
from ram_plugin.config import Config, PluginError  # noqa: E402
from ram_plugin.management import PluginService  # noqa: E402
from ram_plugin.mcp_server import call_tool  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    personal_namespace="private-alice",
    participant="alice",
    api_key="ram-secret",
    agenda_owner_id="ami-project-office",
    playbook_mcp_url="https://playbook.example.test/v1/playbooks/shared/mcp",
    playbook_api_key="playbook-secret",
)


def record(
    memory_id: str,
    state_id: str,
    *,
    state_kind: str = "risk",
    status: str = "open",
    role: str = "creates",
    requested: str = "Approve the mitigation plan",
    impact: str = "The committed delivery date is at risk",
    owner: str = "employee-laura-project-manager",
    sources=True,
    artifact=None,
    subject=None,
    observed_at="2026-10-20T09:00:00Z",
    event_sequence=1,
    source_offset_ms=0,
):
    return {
        "id": memory_id,
        "text": f"Current state for {state_id}",
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state",
        "sources": [{"sourceId": f"source-{memory_id}"}] if sources else [],
        "attributes": {
            "schema_version": "organizational-state-v2",
            "state_id": state_id,
            "state_kind": state_kind,
            "lifecycle_status": status,
            "evidence_role": role,
            "subject": subject or f"Decision needed for {state_id}",
            "project_id": "project-ami-es2002",
            "accountable_entity_id": owner,
            "observed_at": observed_at,
            "event_sequence": event_sequence,
            "source_offset_ms": source_offset_ms,
            "due_at": "2026-11-05",
            "requested_decision": requested,
            "impact": impact,
            "supersedes_state_ids": [],
            "source_artifact_id": artifact or f"artifact-{memory_id}",
            "source_revision": "1",
            "evidence_locator": "paragraph-3",
        },
    }


def projection_record(records):
    current = records[-1]
    attributes = current["attributes"]
    conflicts = [
        item["id"]
        for item in records
        if item["attributes"]["evidence_role"] == "contradicts"
        or item["attributes"]["state_kind"] == "conflict"
    ]
    return {
        "id": f"projection-{attributes['state_id']}",
        "text": attributes["subject"],
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state_projection",
        "attributes": {
            "schema_version": "organizational-state-projection-v1",
            "state_id": attributes["state_id"],
            "state_kind": attributes["state_kind"],
            "lifecycle_status": attributes["lifecycle_status"],
            "subject": attributes["subject"],
            "project_id": attributes["project_id"],
            "project_step_id": "",
            "meeting_id": "",
            "accountable_entity_id": attributes["accountable_entity_id"],
            "related_entity_ids": [],
            "valid_at": attributes["observed_at"],
            "event_sequence": attributes["event_sequence"],
            "source_offset_ms": attributes["source_offset_ms"],
            "due_at": attributes["due_at"],
            "resolved_at": "",
            "requested_decision": attributes["requested_decision"],
            "impact": attributes["impact"],
            "conflict_status": "unresolved" if conflicts else "none",
            "supporting_memory_ids": [item["id"] for item in records],
            "conflicting_memory_ids": conflicts,
            "observation_count": len(records),
            "current_memory_id": current["id"],
            "resolution_policy_id": "test-policy-v1",
        },
    }


class AgendaRAM:
    def __init__(self, records, evidence=True):
        self.supporting = {item["id"]: item for item in records}
        grouped = {}
        for item in records:
            grouped.setdefault(item["attributes"]["state_id"], []).append(item)
        self.records = [projection_record(items) for items in grouped.values()]
        self.has_evidence = evidence
        self.evidence_calls = []
        self.search_requests = []

    def search(self, request, timeout_ms=None):
        self.search_requests.append(request)
        attributes = request.get("filter", {}).get("attributes", {})
        state_kind = attributes.get("state_kind", {}).get("string")
        records = [
            item
            for item in self.records
            if state_kind is None or item["attributes"]["state_kind"] == state_kind
        ]
        return {"items": records[: request.get("limit", 100)]}

    def get(self, memory_id):
        return self.supporting[memory_id]

    def evidence(self, memory_id, source_id, limit=100, page_token=None):
        self.evidence_calls.append((memory_id, source_id))
        return {
            "source": {
                "sourceId": source_id,
                "kind": "document",
                "identity": {"documentId": "minutes", "revision": "1"},
                "evidence": [{"text": "Verified passage"}] if self.has_evidence else [],
            }
        }


class AgendaPlaybook:
    def __init__(self, corrupt=False):
        self.calls = []
        self.text = {path: f"Runtime policy for {path}\n" for path in REQUIRED_RESOURCES}
        self.corrupt = corrupt

    def inventory(self):
        return ["discover_entries", "load_skill", "fetch_resource"]

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "discover_entries":
            return {
                "discoveredEntries": [
                    {
                        "entryKey": "prepare-management-review-agenda",
                        "entryId": "entry-agenda",
                        "version": 7,
                        "contentDigest": "sha256:skill-digest",
                    }
                ]
            }
        if tool == "load_skill":
            resources = [
                {
                    "path": path,
                    "uri": f"playbook://entry-agenda/7/{path}",
                    "digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                    "mimeType": "text/markdown",
                }
                for path, text in self.text.items()
            ]
            resources.append(
                {
                    "path": "SKILL.md",
                    "uri": "playbook://entry-agenda/7/SKILL.md",
                    "digest": "sha256:unused",
                }
            )
            return {
                "entryId": "entry-agenda",
                "version": 7,
                "content": {
                    "format": "skill",
                    "manifest": {"name": "prepare-management-review-agenda"},
                    "instructions": "Use the linked runtime policy resources.",
                    "resources": resources,
                },
            }
        if tool == "fetch_resource":
            path = arguments["uri"].split("/7/", 1)[1]
            text = self.text[path]
            digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
            if self.corrupt and path == REQUIRED_RESOURCES[0]:
                text += "changed"
            return {"uri": arguments["uri"], "digest": digest, "text": text}
        raise AssertionError(tool)


class AgendaTests(unittest.TestCase):
    def service(self, records, evidence=True, corrupt=False):
        ram = AgendaRAM(records, evidence)
        playbook = AgendaPlaybook(corrupt)
        return PluginService(CONFIG, ram, playbook, object()), ram, playbook

    def test_prepares_cited_item_from_runtime_skill(self):
        service, ram, playbook = self.service([record("memory-a", "state-a")])
        result = service.agenda_prepare("2026-11-01", lookback_days=30, max_items=8)
        self.assertEqual(len(result["agenda_items"]), 1)
        item = result["agenda_items"][0]
        self.assertEqual(
            set(item),
            {
                "state_id", "title", "agenda_purpose", "state_kind",
                "lifecycle_status", "why_now", "current_state", "owner", "due_at",
                "timebox_minutes", "confidence", "evidence_references",
            },
        )
        self.assertEqual(item["owner"], "employee-laura-project-manager")
        self.assertEqual(item["evidence_references"][0]["memory_id"], "memory-a")
        self.assertEqual(ram.evidence_calls, [("memory-a", "source-memory-a")])
        self.assertEqual(
            [
                request["filter"]["attributes"]["state_kind"]["string"]
                for request in ram.search_requests
            ],
            [
                "action_item",
                "decision",
                "approval",
                "risk",
                "issue",
                "dependency",
                "conflict",
            ],
        )
        self.assertEqual(result["playbook"]["version"], 7)
        fetched = [
            arguments["uri"].split("/7/", 1)[1]
            for tool, arguments in playbook.calls
            if tool == "fetch_resource"
        ]
        self.assertEqual(fetched, list(REQUIRED_RESOURCES))

    def test_defers_candidate_without_traversable_evidence(self):
        service, _, _ = self.service([record("memory-a", "state-a")], evidence=False)
        result = service.agenda_prepare("2026-11-01")
        self.assertEqual(result["agenda_items"], [])
        self.assertIn("source_evidence_unavailable", result["deferred_candidates"][0]["reasons"])
        self.assertTrue(result["warnings"])

    def test_returns_shared_state_context_without_inventing_decision_fields(self):
        records = [
            record(
                "decision",
                "state-decision",
                state_kind="decision",
                status="decided",
                requested="",
                impact="",
                owner="",
            ),
            record(
                "completed",
                "state-completed",
                state_kind="action_item",
                status="completed",
                requested="",
                impact="",
            ),
            record(
                "open-action",
                "state-open-action",
                state_kind="action_item",
                requested="",
                impact="",
            ),
        ]
        service, _, _ = self.service(records)

        result = service.agenda_prepare("2026-11-01")

        self.assertEqual(
            [item["state_id"] for item in result["agenda_items"]],
            ["state-open-action"],
        )
        self.assertNotIn("management_question", result["agenda_items"][0])
        self.assertNotIn("requested_decision", result["agenda_items"][0])
        self.assertEqual(
            [item["state_id"] for item in result["confirmed_decisions"]],
            ["state-decision"],
        )
        self.assertEqual(
            [item["state_id"] for item in result["completed_work"]],
            ["state-completed"],
        )
        self.assertEqual(
            [item["state_id"] for item in result["open_work_items"]],
            ["state-open-action"],
        )
        for collection in (
            result["confirmed_decisions"],
            result["completed_work"],
            result["open_work_items"],
        ):
            self.assertTrue(collection[0]["evidence_references"])
        self.assertEqual(
            [item["state_id"] for item in result["action_items"]],
            ["state-open-action", "state-completed"],
        )
        self.assertEqual(result["action_item_summary"]["total"], 2)
        self.assertEqual(result["confirmed_decisions"][0]["owner"], "")
        self.assertFalse(result["deferred_candidates"])

    def test_completed_work_cites_the_confirmed_human_observation(self):
        assignment = record(
            "assignment",
            "state-completed",
            state_kind="action_item",
            status="open",
            subject="Complete the evaluation criteria",
            observed_at="2026-10-20T09:00:00Z",
        )
        completion = record(
            "human-completion",
            "state-completed",
            state_kind="action_item",
            status="completed",
            sources=False,
            artifact="personal-candidate-candidate-abc",
            subject="Complete the evaluation criteria",
            observed_at="2026-10-21T09:00:00Z",
            event_sequence=2,
        )
        completion["attributes"].update(
            {
                "schema_version": "organizational-state-v3",
                "evidence_locator": "candidate:candidate-abc;private-session:session-1;turn:turn-1",
                "resolved_at": "2026-10-21T09:00:00Z",
            }
        )
        service, ram, _ = self.service([assignment, completion])

        result = service.agenda_prepare("2026-11-01")

        reference = result["completed_work"][0]["evidence_references"][0]
        self.assertEqual(reference["reference_type"], "ram_memory")
        self.assertEqual(reference["memory_id"], "human-completion")
        evidence = service.ram_get_evidence("human-completion")
        self.assertEqual(
            evidence["source"]["evidence"][0]["observation"]["lifecycle_status"],
            "completed",
        )
        self.assertNotIn(("human-completion", None), ram.evidence_calls)

    def test_context_registers_are_not_capped_by_agenda_capacity(self):
        records = [
            record(
                f"action-{index}",
                f"state-action-{index}",
                state_kind="action_item",
                requested="",
                impact="",
                owner=(
                    "employee-andrew-marketing-expert"
                    if index % 2
                    else "employee-laura-project-manager"
                ),
            )
            for index in range(5)
        ]
        records.extend(
            record(
                f"decision-{index}",
                f"state-decision-{index}",
                state_kind="decision",
                status="decided",
                requested="",
                impact="",
            )
            for index in range(4)
        )
        service, ram, _ = self.service(records)

        result = service.agenda_prepare("2026-11-01", max_items=1, focus="launch")

        self.assertEqual(len(result["action_items"]), 5)
        self.assertEqual(len(result["open_work_items"]), 5)
        self.assertEqual(len(result["confirmed_decisions"]), 4)
        self.assertEqual(result["action_item_summary"]["by_status"], {"open": 5})
        self.assertEqual(result["retrieval_diagnostics"]["total_current_states"], 9)
        self.assertTrue(result["retrieval_diagnostics"]["focus_used_for_ranking_only"])
        self.assertTrue(all(request.get("text") == "launch" for request in ram.search_requests))
        self.assertEqual(ram.evidence_calls, [("action-0", "source-action-0")])

    def test_keeps_topic_without_decision_fields_and_excludes_terminal_state(self):
        missing = record("missing", "state-missing", requested="")
        resolved = record("resolved", "state-resolved", status="resolved")
        service, ram, _ = self.service([missing, resolved])
        result = service.agenda_prepare("2026-11-01")
        self.assertEqual(
            [item["state_id"] for item in result["agenda_items"]],
            ["state-missing"],
        )
        self.assertEqual(
            [item["state_id"] for item in result["completed_work"]],
            ["state-resolved"],
        )
        self.assertEqual(ram.evidence_calls, [("missing", "source-missing")])

    def test_preserves_unresolved_conflict_as_a_management_topic(self):
        initial = record("initial", "state-a", artifact="minutes")
        conflicting = record(
            "conflicting",
            "state-a",
            role="contradicts",
            artifact="email",
        )
        service, _, _ = self.service([initial, conflicting])
        result = service.agenda_prepare("2026-11-01")
        self.assertEqual(result["agenda_items"][0]["agenda_purpose"], "resolve_conflict")
        self.assertEqual(result["conflicts"][0]["state_id"], "state-a")
        self.assertEqual(result["conflicts"][0]["agenda_status"], "unresolved")
        self.assertEqual(result["reconciled_conflicts"], [])

    def test_second_pass_resolves_only_conflicts_with_later_matching_evidence(self):
        colour = record(
            "colour-conflict",
            "state-colour-conflict",
            state_kind="conflict",
            subject="Corporate colour specification",
            event_sequence=2,
        )
        yellow = record(
            "yellow-decision",
            "state-yellow-decision",
            state_kind="decision",
            status="decided",
            subject="Yellow corporate colour",
            event_sequence=3,
        )
        price = record(
            "price-conflict",
            "state-price-conflict",
            state_kind="conflict",
            subject="Selling price basis",
            event_sequence=1,
        )
        budget = record(
            "budget-decision",
            "state-budget-decision",
            state_kind="decision",
            status="decided",
            subject="Costs within budget",
            event_sequence=4,
        )
        service, ram, _ = self.service([colour, yellow, price, budget])

        result = service.agenda_prepare("2026-11-01")

        self.assertEqual(
            [item["state_id"] for item in result["reconciled_conflicts"]],
            ["state-colour-conflict"],
        )
        self.assertEqual(
            result["reconciled_conflicts"][0]["resolution_state"]["state_id"],
            "state-yellow-decision",
        )
        self.assertEqual(
            [item["state_id"] for item in result["conflicts"]],
            ["state-price-conflict"],
        )
        self.assertEqual(
            [item["state_id"] for item in result["agenda_items"]],
            ["state-price-conflict"],
        )
        semantic_queries = [
            request["text"]
            for request in ram.search_requests
            if request.get("text") is not None
        ]
        self.assertEqual(semantic_queries, ["colour corporate", "price selling"])

    def test_rejects_changed_runtime_resource(self):
        service, _, _ = self.service([record("memory-a", "state-a")], corrupt=True)
        with self.assertRaises(PluginError) as raised:
            service.agenda_prepare("2026-11-01")
        self.assertEqual(raised.exception.code, "playbook_digest_mismatch")

    def test_mcp_rejects_invalid_date_before_service_creation(self):
        invoked = False

        def factory():
            nonlocal invoked
            invoked = True
            return object()

        result = call_tool("agenda_prepare", {"meeting_date": "November 1"}, factory)
        self.assertTrue(result["isError"])
        self.assertFalse(invoked)


if __name__ == "__main__":
    unittest.main()
