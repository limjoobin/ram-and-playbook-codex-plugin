from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import Config, PluginError  # noqa: E402
from ram_plugin.management import PluginService, reconcile_states, resolve_entities  # noqa: E402
from ram_plugin.playbook import PlaybookClient  # noqa: E402


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


def observation(
    memory_id: str,
    state_id: str,
    *,
    role: str = "creates",
    status: str = "open",
    observed: str = "2026-01-01T00:00:00Z",
    artifact: str = "minutes-a",
    revision: str = "1",
    namespace=None,
    supersedes=None,
    requested_decision: str = "Approve the next step",
    impact: str = "The milestone will slip",
):
    return {
        "id": memory_id,
        "text": f"Observation {state_id}",
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state",
        "namespace": namespace,
        "updatedAt": observed,
        "sources": [{"sourceId": f"source-{memory_id}"}],
        "attributes": {
            "schema_version": "organizational-state-v1",
            "state_id": state_id,
            "state_kind": "risk",
            "lifecycle_status": status,
            "evidence_role": role,
            "subject": f"Subject {state_id}",
            "project_id": "project-ami-es2002",
            "accountable_entity_id": "employee-laura-project-manager",
            "observed_at": observed,
            "requested_decision": requested_decision,
            "impact": impact,
            "supersedes_state_ids": supersedes or [],
            "source_artifact_id": artifact,
            "source_revision": revision,
            "evidence_locator": "paragraph-1",
        },
    }


class FakeRAM:
    def __init__(self, records=None):
        self.records = records or []
        self.requests = []

    def search(self, request, timeout_ms=None):
        self.requests.append(request)
        return {"items": list(self.records)}

    def evidence(self, memory_id, source_id, limit=100, page_token=None):
        return {
            "source": {
                "sourceId": source_id,
                "kind": "document",
                "identity": {"documentId": "minutes-a", "revision": "2"},
                "evidence": [{"text": "Grounded source passage"}],
            }
        }


class FakePlaybook:
    def inventory(self):
        return ["discover_entries", "load_skill", "fetch_resource"]

    def call(self, tool, arguments):
        return {"tool": tool, "arguments": arguments}


class FakeEditor:
    pass


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=None):
        return self.payload


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ManagementTests(unittest.TestCase):
    def test_entity_resolution_is_deterministic(self):
        result = resolve_entities("Marketing Expert", "employee", 10)
        self.assertEqual(result["matches"][0]["canonical_id"], "employee-andrew-marketing-expert")

    def test_reconciliation_removes_duplicates_and_old_revisions(self):
        old = observation("old", "state-a", revision="1")
        duplicate = observation("duplicate", "state-a", revision="2", observed="2026-01-02T00:00:00Z")
        latest = observation("latest", "state-a", revision="2", observed="2026-01-02T00:00:00Z")
        result = reconcile_states([old, duplicate, latest], CONFIG)
        self.assertEqual([state["state_id"] for state in result["states"]], ["state-a"])
        self.assertEqual(result["states"][0]["observation_count"], 1)
        self.assertEqual(result["diagnostics"]["duplicates_removed"], 1)
        self.assertEqual(result["diagnostics"]["old_source_revisions_removed"], 1)

    def test_reconciliation_preserves_conflict_terminal_and_supersession(self):
        open_state = observation("open", "state-old", artifact="old-minutes")
        contradiction = observation(
            "conflict",
            "state-old",
            role="contradicts",
            observed="2026-01-02T00:00:00Z",
            artifact="conflict-email",
        )
        replacement = observation(
            "replacement",
            "state-new",
            role="supersedes",
            status="completed",
            observed="2026-01-03T00:00:00Z",
            artifact="new-minutes",
            supersedes=["state-old"],
        )
        result = reconcile_states([open_state, contradiction, replacement], CONFIG)
        states = {state["state_id"]: state for state in result["states"]}
        self.assertTrue(states["state-old"]["has_conflict"])
        self.assertEqual(states["state-old"]["lifecycle_status"], "superseded")
        self.assertEqual(states["state-old"]["superseded_by"], ["state-new"])
        self.assertTrue(states["state-new"]["terminal"])
        completed = reconcile_states([replacement], CONFIG, "completed")
        self.assertEqual(completed["states"][0]["state_id"], "state-new")

    def test_scope_accepts_exact_unnamespaced_lane_and_rejects_other_namespace(self):
        accepted = observation("accepted", "state-a")
        rejected = observation("rejected", "state-b", namespace="other")
        rejected_owner = observation("owner", "state-c")
        rejected_owner["ownerId"] = "another-owner"
        result = reconcile_states([accepted, rejected, rejected_owner], CONFIG)
        self.assertEqual([state["state_id"] for state in result["states"]], ["state-a"])
        self.assertEqual(result["diagnostics"]["out_of_scope_rejected"], 2)

    def test_state_search_applies_lane_and_known_attribute_filters_server_side(self):
        ram = FakeRAM([observation("memory", "state-a")])
        service = PluginService(CONFIG, ram, FakePlaybook(), FakeEditor())
        result = service.ram_search_state(
            text="milestone risk",
            project_id="remote control project",
            accountable_entity="Project Manager",
        )
        filters = ram.requests[0]["filter"]
        self.assertEqual(filters["ownerId"]["eq"], "ami-project-office")
        self.assertEqual(filters["memoryType"]["eq"], "organizational_state")
        self.assertEqual(filters["attributes"]["schema_version"]["string"], "organizational-state-v1")
        self.assertEqual(filters["attributes"]["project_id"]["string"], "project-ami-es2002")
        self.assertEqual(result["states"][0]["state_id"], "state-a")

    def test_evidence_contract_and_playbook_allowlist_wrappers(self):
        service = PluginService(CONFIG, FakeRAM(), FakePlaybook(), FakeEditor())
        evidence = service.ram_get_evidence("memory", "source")
        self.assertEqual(evidence["source"]["evidence"][0]["text"], "Grounded source passage")
        discovered = service.playbook_discover("agenda", pinned_entry_key="prepare-management-review-agenda")
        self.assertEqual(discovered["tool"], "discover_entries")
        self.assertEqual(
            discovered["arguments"]["pinned_entries"],
            [{"entry_key": "prepare-management-review-agenda"}],
        )

    def test_playbook_streamable_http_initializes_and_lists_tools(self):
        client = PlaybookClient(CONFIG)
        client._opener = QueueOpener(
            [
                FakeResponse(
                    json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}).encode(),
                    {"Content-Type": "application/json", "MCP-Session-Id": "session-1"},
                ),
                FakeResponse(b"", {"Content-Type": "application/json"}),
                FakeResponse(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "result": {"tools": [{"name": "load_skill"}, {"name": "discover_entries"}]},
                        }
                    ).encode()
                ),
            ]
        )
        self.assertEqual(client.inventory(), ["discover_entries", "load_skill"])
        self.assertEqual(client.session_id, "session-1")
        self.assertEqual(len(client._opener.requests), 3)

    def test_playbook_auth_errors_are_sanitized(self):
        client = PlaybookClient(CONFIG)
        upstream_error = HTTPError(
            CONFIG.playbook_mcp_url,
            401,
            CONFIG.playbook_api_key,
            {},
            io.BytesIO(b"{}"),
        )
        client._opener = QueueOpener(
            [upstream_error]
        )
        try:
            with self.assertRaises(PluginError) as raised:
                client.inventory()
        finally:
            upstream_error.close()
        self.assertEqual(raised.exception.code, "playbook_authentication_failed")
        self.assertNotIn(CONFIG.playbook_api_key, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
