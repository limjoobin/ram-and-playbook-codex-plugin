from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import Config, PluginError  # noqa: E402
from ram_plugin.mcp_server import call_tool  # noqa: E402
from ram_plugin.promotion import (  # noqa: E402
    HookCapture,
    OBSERVATION_SCHEMA,
    PromotionFacade,
    PromotionLedger,
    PromotionService,
)


class RAMHTTPError(Exception):
    """Stand-in for a redis-iris SDK HTTP error, which exposes status_code."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code



CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    personal_namespace="private-alice",
    participant="alice",
    api_key="secret",
    agenda_owner_id="ami-project-office",
    playbook_url="https://playbook.example.test",
    playbook_id="pb_0123456789abcdef0123456789abcdef",
    playbook_api_key="secret",
)


class FakePromotionRAM:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sessions: dict[str, list[dict]] = {}
        self.keys: dict[str, dict] = {}
        self.records: dict[str, dict] = {}
        self.created: list[list[dict]] = []

    def add_session_event(self, **values):
        key = values["idempotency_key"]
        if key in self.keys:
            return self.keys[key]
        event_id = f"event-{len(self.calls) + 1}"
        event = {
            "eventId": event_id,
            "actorId": values["actor_id"],
            "namespace": values["namespace"],
            "role": values["role"],
            "content": [{"text": values["text"]}],
            "metadata": values["metadata"],
        }
        self.calls.append(dict(values))
        self.sessions.setdefault(values["session_id"], []).append(event)
        result = {"event": event}
        self.keys[key] = result
        return result

    def create(self, memories):
        batch = [dict(item) for item in memories]
        self.created.append(batch)
        self.records.update({str(item["id"]): item for item in batch})
        return {"created": [item["id"] for item in batch], "errors": []}

    def get(self, memory_id):
        if memory_id not in self.records:
            raise RAMHTTPError(404)
        return self.records[memory_id]


class EmptyBase:
    pass


class CurrentStateBase:
    def __init__(self, status: str = "open") -> None:
        self.status = status
        self.requested: list[str] = []

    def current_state_by_id(self, state_id: str) -> dict:
        self.requested.append(state_id)
        return {
            "state_id": state_id,
            "state_kind": "action_item",
            "lifecycle_status": self.status,
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


def prompt(session: str = "chat-1", text: str = "Please remember this for the team") -> dict:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session,
        "turn_id": "turn-1",
        "prompt": text,
    }


def stop(session: str = "chat-1", text: str = "Implemented the launch approval workflow.") -> dict:
    return {
        "hook_event_name": "Stop",
        "session_id": session,
        "turn_id": "turn-1",
        "last_assistant_message": text,
        "stop_hook_active": False,
    }


def observation() -> dict:
    return {
        "state_kind": "approval",
        "lifecycle_status": "approved",
        "evidence_role": "creates",
        "subject": "The launch workflow was approved.",
        "project_id": "project-launch",
        "project_step_id": "step-go-live",
        "meeting_id": "meeting-steering-7",
        "accountable_entity_id": "employee-alice",
        "related_entity_ids": ["employee-bob"],
        "effective_at": "2026-10-26T10:00:00Z",
        "due_at": "",
        "resolved_at": "",
        "requested_decision": "",
        "impact": "The launch can proceed.",
        "supersedes_state_ids": ["state-launch-pending"],
    }


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = PromotionLedger(Path(self.directory.name) / "promotion" / "events.jsonl")
        self.ram = FakePromotionRAM()
        self.capture = HookCapture(CONFIG, self.ram, self.ledger)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _candidate(self) -> str:
        result = self.capture.process(prompt())
        self.assertIn("explicit confirmation", result["hookSpecificOutput"]["additionalContext"])
        self.capture.process(stop())
        candidates = self.ledger.candidates()
        self.assertEqual(len(candidates), 1)
        return next(iter(candidates))

    def test_hooks_capture_private_only_and_deduplicate_delivery(self):
        payload = prompt(text="Continue investigating this privately.")
        self.capture.process(payload)
        self.capture.process(payload)
        self.assertEqual(len(self.ram.calls), 1)
        self.assertEqual(self.ram.calls[0]["namespace"], CONFIG.personal_namespace)
        self.assertTrue(self.ram.calls[0]["metadata"]["private_only"])
        self.assertEqual(self.ledger.candidates(), {})
        self.assertNotIn(CONFIG.namespace, [call["namespace"] for call in self.ram.calls])

    def test_completion_prompt_points_to_explicit_proposal_without_sharing(self):
        result = self.capture.process(
            prompt(
                text=(
                    "At 2026-10-27T09:15:00Z, I completed the trend-watching artifact. "
                    "Publish this update to shared memory."
                )
            )
        )
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("memory_state_update_propose", context)
        self.assertIn("Do not merely acknowledge", context)
        self.assertIn("explicit resolution time", context)
        self.assertEqual(self.ledger.candidates(), {})
        self.assertTrue(all(call["namespace"] == CONFIG.personal_namespace for call in self.ram.calls))

    def test_completed_tool_evidence_can_create_private_candidate(self):
        self.capture.process(prompt(text="Implement the local validation."))
        self.capture.process(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "chat-1",
                "tool_name": "apply_patch",
                "tool_use_id": "tool-1",
                "tool_input": {"path": "/project/app.py"},
                "tool_response": {"ok": True},
            }
        )
        self.capture.process(stop(text="Implemented and tested the validation."))
        candidate = next(iter(self.ledger.candidates().values()))
        self.assertFalse(candidate["explicit_share_intent"])
        self.assertEqual(candidate["evidence"][0]["tool_name"], "apply_patch")
        self.assertTrue(all(call["namespace"] == CONFIG.personal_namespace for call in self.ram.calls))

    def test_secret_values_and_untrusted_transcript_are_not_retained(self):
        secret = "sk-secret-value"
        self.capture.process(prompt(text=f"api_key={secret} keep this private"))
        self.capture.process(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "chat-1",
                "tool_name": "shell",
                "tool_use_id": "tool-2",
                "tool_input": {"authorization": f"Bearer {secret}", "path": "/tmp/result.txt"},
                "tool_response": {"token": secret, "ok": True},
            }
        )
        self.capture.process(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "chat-1",
                "reason": "other",
                "transcript_path": f"/tmp/$(run-{secret}).jsonl",
            }
        )
        stored = self.ledger.path.read_text(encoding="utf-8")
        self.assertNotIn(secret, stored)
        self.assertNotIn("$(run-", stored)
        self.assertIn("transcript_path_digest", stored)

    def test_hook_adapter_handles_malformed_input_without_disclosing_errors(self):
        import subprocess

        script = ROOT / "plugins" / "redis-shared-memory-editor" / "hooks" / "capture.py"
        process = subprocess.run(
            [sys.executable, "-I", str(script)],
            input="not-json",
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(process.stdout, "")
        self.assertEqual(process.stderr, "")

    def test_promotion_requires_confirmation_and_preserves_provenance(self):
        candidate_id = self._candidate()
        service = PromotionService(CONFIG, self.ram, self.ledger)
        with self.assertRaisesRegex(PluginError, "Explicit confirmation"):
            service.candidate_promote(
                candidate_id=candidate_id,
                confirmed=False,
                observation=observation(),
            )
        result = service.candidate_promote(
            candidate_id=candidate_id,
            confirmed=True,
            observation=observation(),
        )
        self.assertEqual(result["outcome"], "promotion_saved")
        self.assertEqual(result["projection_status"], "pending_reconciliation")
        self.assertEqual(len(self.ram.created), 1)
        shared = self.ram.created[0][0]
        self.assertEqual(shared["namespace"], CONFIG.namespace)
        self.assertEqual(shared["ownerId"], CONFIG.agenda_owner_id)
        self.assertEqual(shared["memoryType"], "organizational_state")
        self.assertEqual(shared["attributes"]["schema_version"], OBSERVATION_SCHEMA)
        self.assertEqual(
            set(shared["attributes"]),
            {
                "schema_version", "state_id", "state_kind", "lifecycle_status", "evidence_role",
                "subject", "project_id", "project_step_id", "meeting_id", "accountable_entity_id",
                "related_entity_ids", "observed_at", "event_sequence", "source_offset_ms",
                "effective_at", "due_at", "resolved_at", "requested_decision", "impact",
                "supersedes_state_ids", "relations", "source_artifact_id", "source_revision",
                "evidence_locator",
            },
        )
        self.assertEqual(shared["attributes"]["relations"], {"edges": []})
        self.assertIn(candidate_id, shared["attributes"]["evidence_locator"])
        created_count = len(self.ram.created)
        repeated = service.candidate_promote(
            candidate_id=candidate_id,
            confirmed=True,
            observation=observation(),
        )
        self.assertEqual(repeated["outcome"], "already_submitted")
        self.assertEqual(len(self.ram.created), created_count)
        self.assertEqual(
            self.ledger.candidates()[candidate_id]["observation_memory_id"],
            shared["id"],
        )

    def test_explicit_state_update_proposal_uses_exact_private_prompt_and_current_state(self):
        statement = "I finished the trend-watching action."
        self.capture.process(prompt(text=statement))
        base = CurrentStateBase()
        facade = PromotionFacade(base, PromotionService(CONFIG, self.ram, self.ledger))

        proposed = call_tool(
            "memory_state_update_propose",
            {
                "state_id": "project-ami-es2002-action-trend-watching",
                "expected_current_status": "open",
                "lifecycle_status": "completed",
                "evidence_text": statement,
            },
            lambda: facade,
        )

        self.assertFalse(proposed["isError"])
        candidate = proposed["structuredContent"]["candidate"]
        self.assertEqual(base.requested, ["project-ami-es2002-action-trend-watching"])
        self.assertEqual(candidate["source_statement"], statement)
        self.assertEqual(candidate["current_state"]["lifecycle_status"], "open")
        self.assertEqual(candidate["proposed_observation"]["lifecycle_status"], "completed")
        self.assertEqual(candidate["proposed_observation"]["evidence_role"], "resolves")
        self.assertEqual(candidate["proposed_observation"]["relations"], {"edges": []})

        inspected = call_tool(
            "memory_candidate_inspect",
            {"candidate_id": candidate["candidate_id"]},
            lambda: facade,
        )
        self.assertEqual(
            inspected["structuredContent"]["candidate"]["proposed_observation"],
            candidate["proposed_observation"],
        )
        promoted = call_tool(
            "memory_candidate_promote",
            {"candidate_id": candidate["candidate_id"], "confirmed": True},
            lambda: facade,
        )
        self.assertFalse(promoted["isError"])
        self.assertEqual(promoted["structuredContent"]["state_id"], candidate["current_state"]["state_id"])

    def test_pre_direct_write_promotion_can_be_materialized_idempotently(self):
        candidate_id = self._candidate()
        self.ledger.append(
            "candidate_promoted",
            {
                "candidate_id": candidate_id,
                "promoted_at": "2026-10-27T09:20:00Z",
                "state_id": "state-launch-approved",
                "shared_session_id": "legacy-shared-session",
            },
            event_id=f"promote-{candidate_id}",
        )
        service = PromotionService(CONFIG, self.ram, self.ledger)

        materialized = service.candidate_promote(
            candidate_id=candidate_id,
            confirmed=True,
            observation=observation(),
        )

        self.assertEqual(materialized["outcome"], "promotion_materialized")
        memory_id = materialized["observation_memory_id"]
        self.assertEqual(self.ram.records[memory_id]["memoryType"], "organizational_state")
        self.assertEqual(
            self.ledger.candidates()[candidate_id]["observation_memory_id"],
            memory_id,
        )
        repeated = service.candidate_promote(
            candidate_id=candidate_id,
            confirmed=True,
            observation=observation(),
        )
        self.assertEqual(repeated["outcome"], "already_submitted")
        self.assertEqual(len(self.ram.created), 1)

    def test_state_update_proposal_rejects_stale_state_and_uncaptured_evidence(self):
        self.capture.process(prompt(text="I finished the trend-watching action."))
        facade = PromotionFacade(CurrentStateBase(status="in_progress"), PromotionService(CONFIG, self.ram, self.ledger))
        stale = call_tool(
            "memory_state_update_propose",
            {
                "state_id": "project-ami-es2002-action-trend-watching",
                "expected_current_status": "open",
                "lifecycle_status": "completed",
                "evidence_text": "I finished the trend-watching action.",
            },
            lambda: facade,
        )
        self.assertEqual(stale["structuredContent"]["code"], "state_changed")
        missing = call_tool(
            "memory_state_update_propose",
            {
                "state_id": "project-ami-es2002-action-trend-watching",
                "expected_current_status": "in_progress",
                "lifecycle_status": "completed",
                "evidence_text": "This text was never captured.",
            },
            lambda: facade,
        )
        self.assertEqual(missing["structuredContent"]["code"], "private_evidence_not_found")

    def test_candidate_tools_validate_confirmation_and_rejection(self):
        candidate_id = self._candidate()
        facade = PromotionFacade(EmptyBase(), PromotionService(CONFIG, self.ram, self.ledger))
        listed = call_tool("memory_candidate_list", {}, lambda: facade)
        self.assertFalse(listed["isError"])
        self.assertEqual(listed["structuredContent"]["candidates"][0]["candidate_id"], candidate_id)
        denied = call_tool(
            "memory_candidate_promote",
            {"candidate_id": candidate_id, "confirmed": False, "observation": observation()},
            lambda: facade,
        )
        self.assertTrue(denied["isError"])
        self.assertEqual(denied["structuredContent"]["code"], "confirmation_required")
        rejected = call_tool("memory_candidate_reject", {"candidate_id": candidate_id}, lambda: facade)
        self.assertEqual(rejected["structuredContent"]["status"], "rejected")
        self.assertTrue(all(call["namespace"] == CONFIG.personal_namespace for call in self.ram.calls))

    def test_multi_user_identity_isolated_but_shared_target_matches(self):
        alice_id = self._candidate()
        with tempfile.TemporaryDirectory() as directory:
            bob_config = replace(CONFIG, participant="bob", personal_namespace="private-bob")
            bob_ram = FakePromotionRAM()
            bob_ledger = PromotionLedger(Path(directory) / "promotion" / "events.jsonl")
            bob = HookCapture(bob_config, bob_ram, bob_ledger)
            bob.process(prompt())
            bob.process(stop())
            bob_id = next(iter(bob_ledger.candidates()))
            self.assertNotEqual(alice_id, bob_id)
            self.assertEqual(self.ram.calls[0]["namespace"], "private-alice")
            self.assertEqual(bob_ram.calls[0]["namespace"], "private-bob")
            PromotionService(CONFIG, self.ram, self.ledger).candidate_promote(
                candidate_id=alice_id, confirmed=True, observation=observation()
            )
            PromotionService(bob_config, bob_ram, bob_ledger).candidate_promote(
                candidate_id=bob_id, confirmed=True, observation=observation()
            )
            self.assertEqual(self.ram.created[-1][0]["namespace"], CONFIG.namespace)
            self.assertEqual(bob_ram.created[-1][0]["namespace"], CONFIG.namespace)
            self.assertEqual(self.ram.created[-1][0]["ownerId"], CONFIG.agenda_owner_id)
            self.assertEqual(bob_ram.created[-1][0]["ownerId"], CONFIG.agenda_owner_id)
            self.assertNotEqual(self.ram.created[-1][0]["id"], bob_ram.created[-1][0]["id"])


if __name__ == "__main__":
    unittest.main()
