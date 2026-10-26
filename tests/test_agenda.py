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
    status: str = "open",
    role: str = "creates",
    requested: str = "Approve the mitigation plan",
    impact: str = "The committed delivery date is at risk",
    sources=True,
    artifact=None,
):
    return {
        "id": memory_id,
        "text": f"Current state for {state_id}",
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state",
        "sources": [{"sourceId": f"source-{memory_id}"}] if sources else [],
        "attributes": {
            "schema_version": "organizational-state-v1",
            "state_id": state_id,
            "state_kind": "risk",
            "lifecycle_status": status,
            "evidence_role": role,
            "subject": f"Decision needed for {state_id}",
            "project_id": "project-ami-es2002",
            "accountable_entity_id": "employee-laura-project-manager",
            "observed_at": "2026-10-20T09:00:00Z",
            "due_at": "2026-11-05",
            "requested_decision": requested,
            "impact": impact,
            "supersedes_state_ids": [],
            "source_artifact_id": artifact or f"artifact-{memory_id}",
            "source_revision": "1",
            "evidence_locator": "paragraph-3",
        },
    }


class AgendaRAM:
    def __init__(self, records, evidence=True):
        self.records = records
        self.has_evidence = evidence
        self.evidence_calls = []

    def search(self, request, timeout_ms=None):
        return {"items": self.records}

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
                "title", "management_question", "why_now", "current_state", "owner",
                "requested_decision", "timebox_minutes", "confidence", "evidence_references",
            },
        )
        self.assertEqual(item["owner"], "employee-laura-project-manager")
        self.assertEqual(item["evidence_references"][0]["memory_id"], "memory-a")
        self.assertEqual(ram.evidence_calls, [("memory-a", "source-memory-a")])
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

    def test_defers_missing_decision_and_terminal_state(self):
        missing = record("missing", "state-missing", requested="")
        resolved = record("resolved", "state-resolved", status="resolved")
        service, ram, _ = self.service([missing, resolved])
        result = service.agenda_prepare("2026-11-01")
        reasons = {item["state_id"]: item["reasons"] for item in result["deferred_candidates"]}
        self.assertIn("management_question_missing", reasons["state-missing"])
        self.assertIn("terminal_or_superseded", reasons["state-resolved"])
        self.assertEqual(ram.evidence_calls, [])

    def test_preserves_conflict_and_abstains(self):
        initial = record("initial", "state-a", artifact="minutes")
        conflicting = record(
            "conflicting",
            "state-a",
            role="contradicts",
            artifact="email",
        )
        service, _, _ = self.service([initial, conflicting])
        result = service.agenda_prepare("2026-11-01")
        self.assertEqual(result["agenda_items"], [])
        self.assertEqual(result["conflicts"][0]["state_id"], "state-a")
        self.assertIn("unresolved_conflict", result["deferred_candidates"][0]["reasons"])

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
