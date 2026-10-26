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
from ram_plugin.management import PluginService, resolve_entities  # noqa: E402
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
            "schema_version": "organizational-state-v2",
            "state_id": state_id,
            "state_kind": "risk",
            "lifecycle_status": status,
            "evidence_role": role,
            "subject": f"Subject {state_id}",
            "project_id": "project-ami-es2002",
            "accountable_entity_id": "employee-laura-project-manager",
            "observed_at": observed,
            "event_sequence": 1,
            "source_offset_ms": 0,
            "requested_decision": requested_decision,
            "impact": impact,
            "supersedes_state_ids": supersedes or [],
            "source_artifact_id": artifact,
            "source_revision": revision,
            "evidence_locator": "paragraph-1",
        },
    }


def projection(memory_id: str, state_id: str, supporting, *, status="open", conflict=False):
    source = supporting[-1]
    attributes = source["attributes"]
    return {
        "id": memory_id,
        "text": attributes["subject"],
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state_projection",
        "namespace": None,
        "attributes": {
            "schema_version": "organizational-state-projection-v1",
            "state_id": state_id,
            "state_kind": attributes["state_kind"],
            "lifecycle_status": status,
            "subject": attributes["subject"],
            "project_id": attributes["project_id"],
            "project_step_id": "",
            "meeting_id": "",
            "accountable_entity_id": attributes["accountable_entity_id"],
            "related_entity_ids": [],
            "valid_at": attributes["observed_at"],
            "event_sequence": attributes["event_sequence"],
            "source_offset_ms": attributes["source_offset_ms"],
            "due_at": "",
            "resolved_at": "",
            "requested_decision": attributes["requested_decision"],
            "impact": attributes["impact"],
            "conflict_status": "unresolved" if conflict else "none",
            "supporting_memory_ids": [item["id"] for item in supporting],
            "conflicting_memory_ids": [supporting[-1]["id"]] if conflict else [],
            "observation_count": len(supporting),
            "current_memory_id": supporting[-1]["id"],
            "resolution_policy_id": "test-policy-v1",
        },
    }


class FakeRAM:
    def __init__(self, records=None, supporting=None):
        self.records = records or []
        self.supporting = {item["id"]: item for item in (supporting or [])}
        self.requests = []

    def search(self, request, timeout_ms=None):
        self.requests.append(request)
        return {"items": list(self.records)}

    def get(self, memory_id):
        return self.supporting[memory_id]

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

    def test_state_search_applies_lane_and_known_attribute_filters_server_side(self):
        source = observation("memory", "state-a")
        ram = FakeRAM([projection("projection", "state-a", [source])], [source])
        service = PluginService(CONFIG, ram, FakePlaybook(), FakeEditor())
        result = service.ram_search_state(
            text="milestone risk",
            project_id="remote control project",
            accountable_entity="Project Manager",
            limit=100,
        )
        filters = ram.requests[0]["filter"]
        self.assertEqual(filters["ownerId"]["eq"], "ami-project-office")
        self.assertEqual(filters["memoryType"]["eq"], "organizational_state_projection")
        self.assertEqual(filters["attributes"]["schema_version"]["string"], "organizational-state-projection-v1")
        self.assertEqual(filters["attributes"]["project_id"]["string"], "project-ami-es2002")
        self.assertEqual(ram.requests[0]["limit"], 100)
        self.assertEqual(result["states"][0]["state_id"], "state-a")

    def test_state_history_reads_immutable_observations_without_projection_ids(self):
        source = observation("memory", "state-a")
        ram = FakeRAM([source])
        service = PluginService(CONFIG, ram, FakePlaybook(), FakeEditor())

        result = service.ram_search_state(project_id="remote control project", view="history")

        self.assertEqual(result["view"], "history")
        self.assertEqual(result["observations"][0]["memory_id"], "memory")
        self.assertEqual(result["observations"][0]["event_sequence"], 1)
        self.assertEqual(result["observations"][0]["source_offset_ms"], 0)
        self.assertEqual(
            ram.requests[0]["filter"]["memoryType"]["eq"], "organizational_state"
        )

    def test_semantic_history_preserves_ram_rank_before_limit(self):
        relevant = observation("relevant", "state-a", observed="2026-01-02T00:00:00Z")
        older = observation("older", "state-b", observed="2026-01-01T00:00:00Z")
        ram = FakeRAM([relevant, older])
        service = PluginService(CONFIG, ram, FakePlaybook(), FakeEditor())

        result = service.ram_search_state(text="relevant", view="history", limit=1)

        self.assertEqual(result["observations"][0]["memory_id"], "relevant")

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
