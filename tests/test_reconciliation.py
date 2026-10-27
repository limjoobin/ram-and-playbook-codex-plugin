from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_ROOT))

from admin_bootstrap.bundle import Bundle  # noqa: E402
from ram_plugin.config import Config  # noqa: E402
from ram_plugin.mcp_server import call_tool  # noqa: E402
from ram_plugin.promotion import (  # noqa: E402
    HookCapture,
    PromotionFacade,
    PromotionLedger,
    PromotionService,
)
from reconciliation.job import ReconciliationJob  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    personal_namespace="private-andrew",
    participant="andrew",
    api_key="secret",
    agenda_owner_id="ami-project-office",
    playbook_mcp_url="https://playbook.example.test/v1/playbooks/shared/mcp",
    playbook_api_key="secret",
)


def observation(
    memory_id: str,
    status: str,
    role: str,
    observed_at: str,
    *,
    source_artifact_id: str = "minutes-kickoff",
) -> dict:
    return {
        "id": memory_id,
        "text": "Conduct trend watching",
        "namespace": CONFIG.namespace,
        "ownerId": CONFIG.agenda_owner_id,
        "memoryType": "organizational_state",
        "attributes": {
            "schema_version": "organizational-state-v2",
            "state_id": "project-ami-es2002-action-trend-watching",
            "state_kind": "action_item",
            "lifecycle_status": status,
            "evidence_role": role,
            "subject": "Conduct trend watching",
            "project_id": "project-ami-es2002",
            "project_step_id": "project-step-ami-es2002-kickoff",
            "meeting_id": "meeting-ami-es2002a-kickoff",
            "accountable_entity_id": "employee-andrew-marketing-expert",
            "related_entity_ids": [],
            "observed_at": observed_at,
            "event_sequence": 0,
            "source_offset_ms": 0,
            "effective_at": observed_at,
            "due_at": "",
            "resolved_at": observed_at if status == "completed" else "",
            "requested_decision": "",
            "impact": "",
            "supersedes_state_ids": [],
            "source_artifact_id": source_artifact_id,
            "source_revision": "1",
            "evidence_locator": f"candidate:{source_artifact_id}",
        },
    }


class FakeRAM:
    def __init__(self, records: list[dict]) -> None:
        self.records = {str(item["id"]): item for item in records}
        self.created: list[list[dict]] = []
        self.sessions: dict[str, list[dict]] = {}
        self.idempotent_events: dict[str, dict] = {}

    def search(self, request, timeout_ms=None):
        filters = request["filter"]
        memory_type = filters["memoryType"]["eq"]
        schema = filters["attributes"]["schema_version"]["string"]
        items = [
            item
            for item in self.records.values()
            if item.get("memoryType") == memory_type
            and item.get("ownerId") == CONFIG.agenda_owner_id
            and item.get("attributes", {}).get("schema_version") == schema
        ]
        return {"items": items}

    def create(self, memories):
        batch = [dict(item) for item in memories]
        self.created.append(batch)
        self.records.update({str(item["id"]): item for item in batch})
        return {"created": [item["id"] for item in batch], "errors": []}

    def get(self, memory_id):
        return self.records[memory_id]

    def add_session_event(self, **values):
        key = values["idempotency_key"]
        if key in self.idempotent_events:
            return self.idempotent_events[key]
        event = {
            "eventId": f"event-{sum(map(len, self.sessions.values())) + 1}",
            "actorId": values["actor_id"],
            "namespace": values["namespace"],
            "role": values["role"],
            "content": [{"text": values["text"]}],
            "metadata": values["metadata"],
        }
        self.sessions.setdefault(values["session_id"], []).append(event)
        result = {"event": event}
        self.idempotent_events[key] = result
        return result

    def get_session(self, session_id, timeout_ms=None):
        return {"events": list(self.sessions.get(session_id, []))}


class CurrentStateBase:
    def current_state_by_id(self, state_id: str) -> dict:
        return {
            "state_id": state_id,
            "state_kind": "action_item",
            "lifecycle_status": "open",
            "subject": "Conduct trend watching",
            "project_id": "project-ami-es2002",
            "project_step_id": "project-step-ami-es2002-kickoff",
            "meeting_id": "meeting-ami-es2002a-kickoff",
            "accountable_entity_id": "employee-andrew-marketing-expert",
            "related_entity_ids": [],
            "due_at": "",
            "requested_decision": "",
            "impact": "",
        }


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")

    def _projection(self, observations: list[dict]) -> dict:
        item = self.bundle.projector()(observations, self.bundle.projection_policy())[0]
        value = item.sdk_input(CONFIG.agenda_owner_id)
        return {
            "id": value["id"],
            "text": value["text"],
            "namespace": CONFIG.namespace,
            "ownerId": value["owner_id"],
            "memoryType": value["memory_type"],
            "topics": value["topics"],
            "attributes": value["attributes"],
        }

    def test_new_explicit_completion_updates_projection(self):
        opened = observation("observation-open", "open", "creates", "2026-01-01T00:00:00Z")
        prior = self._projection([opened])
        candidate_id = "candidate-" + "a" * 48
        completed = observation(
            "observation-completed",
            "completed",
            "resolves",
            "2026-10-27T00:00:00Z",
            source_artifact_id=f"personal-{candidate_id}"[:64],
        )
        ram = FakeRAM([opened, completed, prior])
        job = ReconciliationJob(CONFIG, ram, self.bundle)

        planned = job.run(wait_for_candidate=candidate_id)
        self.assertEqual(planned["status"], "ready")
        self.assertEqual(planned["changed_projection_count"], 1)
        self.assertTrue(planned["candidate_visible"])

        applied = job.run(apply=True, wait_for_candidate=candidate_id)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(len(ram.created), 1)
        self.assertEqual(ram.created[0][0]["attributes"]["lifecycle_status"], "completed")

    def test_timestamped_employee_report_promotes_and_materializes_completion(self):
        completion_time = "2026-10-27T09:15:00Z"
        capture_time = "2026-10-27T09:20:00Z"
        statement = (
            f"At {completion_time}, I completed the trend-watching artifact. "
            "Publish this update to shared memory."
        )
        state_id = "project-ami-es2002-action-trend-watching"
        opened = observation("observation-open", "open", "creates", "2026-01-01T00:00:00Z")
        prior = self._projection([opened])
        ram = FakeRAM([opened, prior])

        with tempfile.TemporaryDirectory() as directory, patch(
            "ram_plugin.promotion._now", return_value=capture_time
        ):
            ledger = PromotionLedger(Path(directory) / "promotion" / "events.jsonl")
            capture = HookCapture(CONFIG, ram, ledger)
            hook_result = capture.process(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "chat-andrew-1",
                    "turn_id": "turn-1",
                    "prompt": statement,
                }
            )
            self.assertIn(
                "memory_state_update_propose",
                hook_result["hookSpecificOutput"]["additionalContext"],
            )

            facade = PromotionFacade(
                CurrentStateBase(),
                PromotionService(CONFIG, ram, ledger),
            )
            proposed = call_tool(
                "memory_state_update_propose",
                {
                    "state_id": state_id,
                    "expected_current_status": "open",
                    "lifecycle_status": "completed",
                    "evidence_text": statement,
                    "resolved_at": completion_time,
                },
                lambda: facade,
            )
            candidate = proposed["structuredContent"]["candidate"]
            candidate_id = candidate["candidate_id"]
            self.assertEqual(candidate["actor_id"], "andrew")
            self.assertEqual(candidate["captured_at"], capture_time)
            self.assertEqual(candidate["proposed_observation"]["resolved_at"], completion_time)

            inspected = call_tool(
                "memory_candidate_inspect",
                {"candidate_id": candidate_id},
                lambda: facade,
            )
            self.assertEqual(
                inspected["structuredContent"]["candidate"]["source_statement"],
                statement,
            )
            promoted = call_tool(
                "memory_candidate_promote",
                {"candidate_id": candidate_id, "confirmed": True},
                lambda: facade,
            )
            self.assertFalse(promoted["isError"])
            shared_session_id = promoted["structuredContent"]["shared_session_id"]
            envelope = json.loads(ram.sessions[shared_session_id][-1]["content"][0]["text"])

            capture.process(
                {
                    "hook_event_name": "SessionEnd",
                    "session_id": "chat-andrew-1",
                    "reason": "complete",
                    "transcript_path": "/untrusted/session.jsonl",
                }
            )
            self.assertEqual(len(ledger.candidates()), 1)

        extracted_attributes = envelope["observation"]
        self.assertEqual(envelope["confirmed_by"], "andrew")
        self.assertEqual(extracted_attributes["state_id"], state_id)
        self.assertEqual(extracted_attributes["lifecycle_status"], "completed")
        self.assertEqual(extracted_attributes["evidence_role"], "resolves")
        self.assertEqual(extracted_attributes["observed_at"], capture_time)
        self.assertEqual(extracted_attributes["resolved_at"], completion_time)

        # Simulate RAM's asynchronous custom extraction of the confirmed envelope.
        extracted_id = "observation-andrew-completed-trend-watching"
        ram.records[extracted_id] = {
            "id": extracted_id,
            "text": extracted_attributes["subject"],
            "namespace": CONFIG.namespace,
            "ownerId": CONFIG.agenda_owner_id,
            "memoryType": "organizational_state",
            "attributes": extracted_attributes,
        }
        job = ReconciliationJob(CONFIG, ram, self.bundle)
        applied = job.run(apply=True, wait_for_candidate=candidate_id)
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(applied["candidate_visible"])
        current = ram.records[prior["id"]]["attributes"]
        self.assertEqual(current["lifecycle_status"], "completed")
        self.assertEqual(current["current_memory_id"], extracted_id)

        repeated = job.run(apply=True, wait_for_candidate=candidate_id)
        self.assertEqual(repeated["status"], "no_changes")
        self.assertEqual(len(ram.created), 1)

    def test_no_new_observation_leaves_open_projection_unchanged(self):
        opened = observation("observation-open", "open", "creates", "2026-01-01T00:00:00Z")
        prior = self._projection([opened])
        ram = FakeRAM([opened, prior])

        result = ReconciliationJob(CONFIG, ram, self.bundle).run(apply=True)

        self.assertEqual(result["status"], "no_changes")
        self.assertEqual(result["changed_projection_count"], 0)
        self.assertEqual(ram.created, [])

    def test_missing_promoted_observation_does_not_write(self):
        opened = observation("observation-open", "open", "creates", "2026-01-01T00:00:00Z")
        prior = self._projection([opened])
        ram = FakeRAM([opened, prior])

        result = ReconciliationJob(CONFIG, ram, self.bundle).run(
            apply=True,
            wait_for_candidate="candidate-" + "b" * 48,
        )

        self.assertEqual(result["status"], "awaiting_extraction")
        self.assertEqual(ram.created, [])


if __name__ == "__main__":
    unittest.main()
