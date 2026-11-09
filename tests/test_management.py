from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import Config, PluginError  # noqa: E402
from ram_plugin.management import PluginService, resolve_entities  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    personal_namespace="private-alice",
    participant="alice",
    api_key="ram-secret",
    agenda_owner_id="ami-project-office",
    playbook_url="https://playbook.example.test",
    playbook_id="pb_0123456789abcdef0123456789abcdef",
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
    namespace="shared-namespace",
    supersedes=None,
    requested_decision: str = "Approve the next step",
    impact: str = "The milestone will slip",
    schema_version: str = "organizational-state-v2",
    relations=None,
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
            "schema_version": schema_version,
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
            **({"relations": relations} if relations is not None else {}),
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
        "namespace": "shared-namespace",
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
        self.assertEqual(filters["namespace"]["eq"], "shared-namespace")
        self.assertNotIn("ownerId", filters)
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

    def test_exact_current_state_lookup_is_server_filtered_and_evidence_bound(self):
        source = observation("memory", "state-a")
        ram = FakeRAM([projection("projection", "state-a", [source])], [source])
        # The expanded layout filters on state_id in RAM; the compact layout
        # cannot (see test_memory_layout).
        expanded = replace(CONFIG, memory_layout="expanded")
        service = PluginService(expanded, ram, FakePlaybook(), FakeEditor())

        state = service.current_state_by_id("state-a")

        self.assertEqual(state["state_id"], "state-a")
        self.assertEqual(
            ram.requests[0]["filter"]["attributes"]["state_id"]["string"],
            "state-a",
        )
        self.assertEqual(state["observations"][0]["memory_id"], "memory")

    def test_current_state_exposes_confirmed_generic_relations(self):
        relations = {
            "edges": [
                {
                    "predicate": "resolves",
                    "target_state_id": "state-a",
                    "confidence": 0.97,
                    "assertion_status": "confirmed",
                    "evidence_memory_ids": ["memory"],
                }
            ]
        }
        source = observation(
            "memory",
            "decision-a",
            schema_version="organizational-state-v3",
            relations=relations,
        )
        ram = FakeRAM([projection("projection", "state-a", [source])], [source])
        service = PluginService(CONFIG, ram, FakePlaybook(), FakeEditor())

        state = service.ram_search_state(project_id="remote control project")["states"][0]

        self.assertEqual(state["observations"][0]["relations"], relations)
        self.assertEqual(
            state["confirmed_relations"][0],
            {"source_state_id": "decision-a", **relations["edges"][0]},
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

    def test_confirmed_human_observation_is_independently_citable(self):
        direct = observation(
            "observation-human",
            "state-a",
            status="completed",
            artifact="personal-candidate-candidate-abc",
            schema_version="organizational-state-v3",
        )
        direct["sources"] = []
        direct["attributes"].update(
            {
                "evidence_locator": "candidate:candidate-abc;private-session:session-1;turn:turn-1",
                "resolved_at": "2026-01-02T00:00:00Z",
            }
        )
        service = PluginService(
            CONFIG,
            FakeRAM(supporting=[direct]),
            FakePlaybook(),
            FakeEditor(),
        )

        result = service.ram_get_evidence("observation-human")

        self.assertEqual(result["source"]["referenceType"], "ram_memory")
        evidence = result["source"]["evidence"][0]["observation"]
        self.assertEqual(evidence["lifecycle_status"], "completed")
        self.assertEqual(evidence["resolved_at"], "2026-01-02T00:00:00Z")
        self.assertEqual(
            evidence["accountable_entity_id"],
            "employee-laura-project-manager",
        )

    def test_ordinary_memory_requires_a_returned_document_source_id(self):
        ordinary = observation("memory", "state-a")
        service = PluginService(
            CONFIG,
            FakeRAM(supporting=[ordinary]),
            FakePlaybook(),
            FakeEditor(),
        )

        with self.assertRaises(PluginError) as raised:
            service.ram_get_evidence("memory")

        self.assertEqual(raised.exception.code, "evidence_unavailable")

if __name__ == "__main__":
    unittest.main()
