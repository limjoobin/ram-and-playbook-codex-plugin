from __future__ import annotations

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
from ram_plugin.ram import RAMHTTPError  # noqa: E402
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
    schema_version: str = "organizational-state-v2",
    state_id: str = "project-ami-es2002-action-trend-watching",
    state_kind: str = "action_item",
    subject: str = "Conduct trend watching",
    project_id: str = "project-ami-es2002",
    relations: dict | None = None,
    supersedes: list[str] | None = None,
    event_sequence: int = 0,
    source_offset_ms: int = 0,
) -> dict:
    attributes = {
        "schema_version": schema_version,
        "state_id": state_id,
        "state_kind": state_kind,
        "lifecycle_status": status,
        "evidence_role": role,
        "subject": subject,
        "project_id": project_id,
        "project_step_id": "project-step-ami-es2002-kickoff",
        "meeting_id": "meeting-ami-es2002a-kickoff",
        "accountable_entity_id": "employee-andrew-marketing-expert",
        "related_entity_ids": [],
        "observed_at": observed_at,
        "event_sequence": event_sequence,
        "source_offset_ms": source_offset_ms,
        "effective_at": observed_at,
        "due_at": "",
        "resolved_at": observed_at if status in {"completed", "resolved"} else "",
        "requested_decision": "",
        "impact": "",
        "supersedes_state_ids": supersedes or [],
        "source_artifact_id": source_artifact_id,
        "source_revision": "1",
        "evidence_locator": f"candidate:{source_artifact_id}",
    }
    if relations is not None:
        attributes["relations"] = relations
    return {
        "id": memory_id,
        "text": subject,
        "namespace": CONFIG.namespace,
        "ownerId": CONFIG.agenda_owner_id,
        "memoryType": "organizational_state",
        "attributes": attributes,
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
        if memory_id not in self.records:
            raise RAMHTTPError(404)
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

    def _projections(self, observations: list[dict]) -> dict[str, dict]:
        return {
            item.attributes["state_id"]: item.attributes
            for item in self.bundle.projector()(observations, self.bundle.projection_policy())
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

    def test_confirmed_fulfills_relation_completes_action_projection(self):
        action_id = "project-ami-es2002-action-decide-target-audience"
        action = observation(
            "observation-target-audience-action",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=action_id,
            subject="Decide target audience",
            event_sequence=2,
            source_offset_ms=1,
        )
        decision = observation(
            "observation-target-audience-decision",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-target-group",
            state_kind="decision",
            subject="Target audience is ages 15 to 35",
            source_artifact_id="minutes-functional-design",
            event_sequence=2,
            source_offset_ms=2,
            relations={
                "edges": [
                    {
                        "predicate": "fulfills",
                        "target_state_id": action_id,
                        "confidence": 0.98,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-target-audience-decision"],
                    }
                ]
            },
        )

        projections = self._projections([action, decision])

        projected_action = projections[action_id]
        self.assertEqual(projected_action["lifecycle_status"], "completed")
        self.assertEqual(projected_action["resolved_at"], "2004-12-13T00:00:00Z")
        self.assertIn(
            "observation-target-audience-decision",
            projected_action["supporting_memory_ids"],
        )

    def test_proposed_relation_does_not_change_lifecycle(self):
        action_id = "project-ami-es2002-action-decide-target-audience"
        action = observation(
            "observation-target-audience-action",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=action_id,
            subject="Decide target audience",
            event_sequence=2,
            source_offset_ms=1,
        )
        decision = observation(
            "observation-target-audience-decision",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-target-group",
            state_kind="decision",
            subject="A market segment was selected",
            event_sequence=2,
            source_offset_ms=2,
            relations={
                "edges": [
                    {
                        "predicate": "fulfills",
                        "target_state_id": action_id,
                        "confidence": 0.98,
                        "assertion_status": "proposed",
                        "evidence_memory_ids": ["observation-target-audience-decision"],
                    }
                ]
            },
        )

        projections = self._projections([action, decision])

        self.assertEqual(projections[action_id]["lifecycle_status"], "open")

    def test_exact_later_artifact_fulfils_action_without_human_confirmation(self):
        action_id = "project-ami-es2002-action-write-final-report"
        action = observation(
            "observation-write-report",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=action_id,
            subject="Write final report",
            event_sequence=4,
        )
        report_decision = observation(
            "observation-final-design",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-final-input-controls",
            state_kind="decision",
            subject="Final design uses push buttons",
            source_artifact_id="ami-es2002-final-report",
            event_sequence=5,
        )

        projected = self._projections([action, report_decision])[action_id]

        self.assertEqual(projected["lifecycle_status"], "completed")
        self.assertIn("observation-final-design", projected["supporting_memory_ids"])

    def test_automatic_fulfilment_rejects_partial_or_earlier_matches(self):
        action_id = "project-ami-es2002-action-submit-evaluation-criteria"
        action = observation(
            "observation-submit-criteria",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=action_id,
            subject="Submit evaluation criteria",
            event_sequence=4,
        )
        partial = observation(
            "observation-project-evaluated",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-project-evaluated",
            state_kind="decision",
            subject="Project was evaluated",
            event_sequence=5,
        )
        earlier_exact = observation(
            "observation-old-criteria",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-evaluation-criteria",
            state_kind="decision",
            subject="Evaluation criteria were submitted",
            event_sequence=3,
        )

        projected = self._projections([action, partial, earlier_exact])[action_id]

        self.assertEqual(projected["lifecycle_status"], "open")

    def test_legacy_explicit_supersedes_target_is_applied_automatically(self):
        old_id = "project-ami-es2002-decision-old-scope"
        old = observation(
            "observation-old-scope",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=old_id,
            state_kind="decision",
            subject="Old product scope",
            event_sequence=1,
        )
        replacement = observation(
            "observation-new-scope",
            "decided",
            "supersedes",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-new-scope",
            state_kind="decision",
            subject="New product scope",
            supersedes=[old_id],
            event_sequence=2,
        )

        projected = self._projections([old, replacement])[old_id]

        self.assertEqual(projected["lifecycle_status"], "superseded")
        self.assertIn("observation-new-scope", projected["supporting_memory_ids"])

    def test_confirmed_relation_to_unknown_state_fails_closed(self):
        source = observation(
            "observation-source",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-market",
            state_kind="decision",
            subject="Choose the target market",
            relations={
                "edges": [
                    {
                        "predicate": "fulfills",
                        "target_state_id": "project-ami-es2002-action-missing",
                        "confidence": 0.98,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-source"],
                    }
                ]
            },
        )

        with self.assertRaisesRegex(ValueError, "unknown state"):
            self._projections([source])

    def test_confirmed_relation_cannot_cross_projects(self):
        target = observation(
            "observation-target",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id="project-other-action-launch",
            subject="Launch another project",
            project_id="project-other",
        )
        source = observation(
            "observation-source",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-launch",
            state_kind="decision",
            subject="Approve launch",
            relations={
                "edges": [
                    {
                        "predicate": "fulfills",
                        "target_state_id": "project-other-action-launch",
                        "confidence": 0.98,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-source"],
                    }
                ]
            },
        )

        with self.assertRaisesRegex(ValueError, "crosses projects"):
            self._projections([target, source])

    def test_confirmed_resolves_and_supersedes_relations_are_generic(self):
        issue_id = "project-ami-es2002-issue-target-market-unclear"
        old_decision_id = "project-ami-es2002-decision-initial-market"
        issue = observation(
            "observation-market-issue",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=issue_id,
            state_kind="issue",
            subject="Target market is unclear",
            event_sequence=1,
        )
        old_decision = observation(
            "observation-old-market-decision",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=old_decision_id,
            state_kind="decision",
            subject="Initial target market is broad",
            event_sequence=1,
        )
        new_decision = observation(
            "observation-new-market-decision",
            "decided",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-decision-final-market",
            state_kind="decision",
            subject="Final target market is ages 15 to 35",
            source_artifact_id="minutes-functional-design",
            event_sequence=2,
            relations={
                "edges": [
                    {
                        "predicate": "resolves",
                        "target_state_id": issue_id,
                        "confidence": 0.96,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-new-market-decision"],
                    },
                    {
                        "predicate": "supersedes",
                        "target_state_id": old_decision_id,
                        "confidence": 0.95,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-new-market-decision"],
                    },
                ]
            },
        )

        projections = self._projections([issue, old_decision, new_decision])

        self.assertEqual(projections[issue_id]["lifecycle_status"], "resolved")
        self.assertEqual(projections[old_decision_id]["lifecycle_status"], "superseded")

    def test_confirmed_non_lifecycle_relation_preserves_status_and_support(self):
        action_id = "project-ami-es2002-action-launch"
        issue = observation(
            "observation-blocker",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            schema_version="organizational-state-v3",
            state_id="project-ami-es2002-issue-budget-blocker",
            state_kind="issue",
            subject="Budget blocks launch",
            relations={
                "edges": [
                    {
                        "predicate": "blocks",
                        "target_state_id": action_id,
                        "confidence": 0.94,
                        "assertion_status": "confirmed",
                        "evidence_memory_ids": ["observation-blocker"],
                    }
                ]
            },
        )
        action = observation(
            "observation-launch-action",
            "open",
            "creates",
            "2004-12-13T00:00:00Z",
            state_id=action_id,
            subject="Launch product",
        )

        projections = self._projections([action, issue])

        self.assertEqual(projections[action_id]["lifecycle_status"], "open")
        self.assertIn("observation-blocker", projections[action_id]["supporting_memory_ids"])

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
            extracted_id = promoted["structuredContent"]["observation_memory_id"]
            extracted_attributes = ram.records[extracted_id]["attributes"]

            capture.process(
                {
                    "hook_event_name": "SessionEnd",
                    "session_id": "chat-andrew-1",
                    "reason": "complete",
                    "transcript_path": "/untrusted/session.jsonl",
                }
            )
            self.assertEqual(len(ledger.candidates()), 1)

        self.assertEqual(extracted_attributes["state_id"], state_id)
        self.assertEqual(extracted_attributes["lifecycle_status"], "completed")
        self.assertEqual(extracted_attributes["evidence_role"], "resolves")
        self.assertEqual(extracted_attributes["observed_at"], capture_time)
        self.assertEqual(extracted_attributes["resolved_at"], completion_time)

        job = ReconciliationJob(CONFIG, ram, self.bundle)
        applied = job.run(apply=True, wait_for_candidate=candidate_id)
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(applied["candidate_visible"])
        current = ram.records[prior["id"]]["attributes"]
        self.assertEqual(current["lifecycle_status"], "completed")
        self.assertEqual(current["current_memory_id"], extracted_id)

        repeated = job.run(apply=True, wait_for_candidate=candidate_id)
        self.assertEqual(repeated["status"], "no_changes")
        self.assertEqual(len(ram.created), 2)

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

        self.assertEqual(result["status"], "awaiting_observation")
        self.assertEqual(ram.created, [])


if __name__ == "__main__":
    unittest.main()
