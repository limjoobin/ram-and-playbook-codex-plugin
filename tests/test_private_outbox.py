"""Hook-queued private events: fast stdlib hooks, delivery by the MCP server."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "redis-shared-memory-editor" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ram_plugin.promotion import (  # noqa: E402
    HookCapture,
    OutboxDelivery,
    PrivateEventOutbox,
    PromotionLedger,
    PromotionService,
)
from test_promotion import CONFIG, FakePromotionRAM, prompt, stop  # noqa: E402


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class FailingRAM(FakePromotionRAM):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def add_session_event(self, **values):
        raise self.error


class ConflictRAM(FakePromotionRAM):
    """RAM that already holds the event under this key, so a redelivery returns 409."""

    def __init__(self, stored: FakePromotionRAM) -> None:
        super().__init__()
        self.stored = stored

    def add_session_event(self, **values):
        wrapped = Exception("SDK wrapper")  # the SDK may re-raise from the HTTP error
        wrapped.__cause__ = StatusError(409)
        raise wrapped

    def get_session(self, session_id, timeout_ms=None, include_summarised=False):
        # The stored event is already folded into the session summary, so RAM
        # returns it only when summarised events are requested.
        events = self.stored.sessions.get(session_id, []) if include_summarised else []
        return {"sessionId": session_id, "events": events}


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = PromotionLedger(Path(self.directory.name) / "promotion" / "events.jsonl")
        self.outbox = PrivateEventOutbox(self.ledger)
        self.capture = HookCapture(CONFIG, None, self.ledger, outbox=self.outbox)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def queued(self) -> list[Path]:
        return sorted(self.outbox.directory.glob("*.json"))

    def test_hook_queues_privately_without_calling_ram(self):
        result = self.capture.process(prompt())
        self.assertIn("explicit confirmation", result["hookSpecificOutput"]["additionalContext"])
        self.capture.process(prompt())  # duplicate delivery folds into one queued event
        self.assertEqual(len(self.queued()), 1)
        self.assertEqual(self.outbox.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.queued()[0].stat().st_mode & 0o777, 0o600)
        request = json.loads(self.queued()[0].read_text())["request"]
        self.assertEqual(request["namespace"], CONFIG.personal_namespace)
        self.assertEqual(request["actor_id"], CONFIG.participant)
        self.assertNotEqual(request["namespace"], CONFIG.namespace)

    def test_drain_delivers_once_with_the_idempotency_key_and_records_the_event(self):
        self.capture.process(prompt())
        self.capture.process(stop())
        ram = FakePromotionRAM()
        self.assertEqual(self.outbox.drain(ram, CONFIG), 2)
        self.assertEqual(self.queued(), [])
        self.assertEqual([call["role"] for call in ram.calls], ["USER", "ASSISTANT"])
        self.assertTrue(all(call["idempotency_key"].startswith("hook-") for call in ram.calls))
        recorded = [event for event in self.ledger.events() if event["kind"] == "ram_private_event"]
        self.assertEqual(len(recorded), 2)
        self.assertEqual(self.outbox.drain(ram, CONFIG), 0)

    def test_transient_failure_keeps_the_event_queued(self):
        self.capture.process(prompt())
        self.capture.process(stop())
        self.assertEqual(self.outbox.drain(FailingRAM(StatusError(503)), CONFIG), 0)
        self.assertTrue(self.outbox.blocked)
        self.assertEqual(len(self.queued()), 2)
        self.assertEqual(self.outbox.drain(FakePromotionRAM(), CONFIG), 2)
        self.assertFalse(self.outbox.blocked)

    def test_permanent_rejection_is_set_aside_not_retried(self):
        self.capture.process(prompt())
        self.assertEqual(self.outbox.drain(FailingRAM(StatusError(400)), CONFIG), 0)
        self.assertFalse(self.outbox.blocked)
        self.assertEqual(self.queued(), [])
        self.assertEqual(len(list((self.outbox.directory / "rejected").iterdir())), 1)
        kinds = [event["kind"] for event in self.ledger.events()]
        self.assertIn("ram_private_event_rejected", kinds)

    def test_duplicate_hook_delivery_never_changes_the_queued_body(self):
        self.capture.process(prompt())
        first = self.queued()[0].read_text()
        self.capture.process(prompt())
        self.assertEqual(self.queued()[0].read_text(), first)
        claimed = self.queued()[0]
        os.replace(claimed, claimed.with_name(f"{claimed.name}.inflight-{os.getpid()}"))
        self.capture.process(prompt())  # an attempt is in flight under this key
        self.assertEqual(self.queued(), [])

    def test_conflict_resolves_to_the_event_ram_already_stored(self):
        self.capture.process(prompt())
        request = json.loads(self.queued()[0].read_text())["request"]
        stored = FakePromotionRAM()
        earlier = stored.add_session_event(**{**request, "created_at": "2026-01-01T00:00:00Z"})
        self.assertEqual(self.outbox.drain(ConflictRAM(stored), CONFIG), 1)
        self.assertFalse(self.outbox.blocked)
        self.assertEqual(self.queued(), [])
        self.assertFalse((self.outbox.directory / "rejected").exists())
        recorded = [e["payload"]["ram_event_id"] for e in self.ledger.events() if e["kind"] == "ram_private_event"]
        self.assertEqual(recorded, [earlier["event"]["eventId"]])

    def test_unresolved_conflict_stays_queued_for_retry(self):
        self.capture.process(prompt())
        self.assertEqual(self.outbox.drain(ConflictRAM(FakePromotionRAM()), CONFIG), 0)
        self.assertTrue(self.outbox.blocked)
        self.assertEqual(len(self.queued()), 1)
        self.assertFalse((self.outbox.directory / "rejected").exists())

    def test_wrapped_permanent_rejection_is_set_aside(self):
        self.capture.process(prompt())
        wrapped = Exception("SDK wrapper")
        wrapped.__cause__ = StatusError(422)
        self.assertEqual(self.outbox.drain(FailingRAM(wrapped), CONFIG), 0)
        self.assertFalse(self.outbox.blocked)
        self.assertEqual(len(list((self.outbox.directory / "rejected").iterdir())), 1)

    def test_events_from_another_configuration_are_left_for_their_owner(self):
        self.capture.process(prompt())
        other = replace(CONFIG, participant="bob", personal_namespace="private-bob")
        ram = FakePromotionRAM()
        self.assertEqual(self.outbox.drain(ram, other), 0)
        self.assertEqual(ram.calls, [])
        self.assertEqual(len(self.queued()), 1)

    def test_a_dead_servers_claim_is_reclaimed(self):
        self.capture.process(prompt())
        queued = self.queued()[0]
        dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        os.replace(queued, queued.with_name(f"{queued.name}.inflight-{int(dead.stdout)}"))
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.outbox.drain(FakePromotionRAM(), CONFIG), 1)

    def test_background_delivery_thread_delivers_and_stops_cleanly(self):
        import time

        ram = FakePromotionRAM()
        delivery = OutboxDelivery(self.outbox, ram, CONFIG, interval=0.01)
        delivery.start()
        try:
            self.capture.process(prompt())
            deadline = time.monotonic() + 5
            while self.queued() and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            delivery.stop()
            delivery.join(timeout=5)
        self.assertFalse(delivery.is_alive())
        self.assertEqual(self.queued(), [])
        self.assertEqual(len(ram.calls), 1)

    def test_promotion_delivers_queued_events_before_reading_provenance(self):
        self.capture.process(prompt())
        self.capture.process(stop())
        ram = FakePromotionRAM()
        service = PromotionService(CONFIG, ram, self.ledger, self.outbox)
        candidates = service.candidate_list()["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["source_private_event_ids"]), 2)
        self.assertEqual(self.queued(), [])


class HookProcessTests(unittest.TestCase):
    def test_hook_process_is_stdlib_only_and_never_loads_the_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "editor.env"
            credential.write_text(
                "\n".join(
                    [
                        "IRIS_AGENT_MEMORY_URL=https://ram.example.invalid",
                        "IRIS_AGENT_MEMORY_STORE_ID=st_example",
                        "IRIS_AGENT_MEMORY_API_KEY=placeholder-value",
                        "RAM_NAMESPACE=team-shared",
                        "RAM_PARTICIPANT=alice",
                        "RAM_AGENDA_OWNER_ID=ami-project-office",
                        "IRIS_AGENT_PLAYBOOKS_URL=https://playbook.example.invalid",
                        "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID=pb_" + "0" * 32,
                        "IRIS_AGENT_PLAYBOOKS_API_KEY=placeholder-value",
                        f"RAM_CAPTURE_FOLDERS={Path(directory) / 'project'}",
                    ]
                )
                + "\n"
            )
            credential.chmod(0o600)
            (Path(directory) / "project" / "src").mkdir(parents=True)
            script = ROOT / "plugins" / "redis-shared-memory-editor" / "hooks" / "capture.py"
            probe = (
                "import runpy, sys\n"
                f"sys.argv = [{str(script)!r}]\n"
                "try:\n"
                f"    runpy.run_path({str(script)!r}, run_name='__main__')\n"
                "finally:\n"
                "    loaded = sorted(m for m in sys.modules if m.split('.')[0] in "
                "{'redis_agent_memory', 'redis_iris', 'redis_agent_playbook', 'httpx', 'pydantic'})\n"
                "    sys.stderr.write(repr(loaded))\n"
            )
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": directory,
                "REDIS_SHARED_MEMORY_CONFIG": str(credential),
                "PLUGIN_DATA": str(Path(directory) / "data"),
            }
            outbox = Path(directory) / "data" / "promotion" / "outbox"

            def run(cwd: str | None, session: str) -> None:
                payload = {"hook_event_name": "UserPromptSubmit", "session_id": session, "turn_id": "t", "prompt": "hello"}
                if cwd is not None:
                    payload["cwd"] = cwd
                process = subprocess.run(
                    [sys.executable, "-I", "-c", probe],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=10,
                    check=True,
                )
                self.assertEqual(json.loads(process.stdout), {"continue": True})
                self.assertEqual(process.stderr, "[]")

            # Plugins are installed account-wide: other projects record nothing.
            run(str(Path(directory) / "elsewhere"), "other-project")
            run(None, "no-folder")
            self.assertFalse(outbox.exists() and list(outbox.glob("*.json")))
            run(str(Path(directory) / "project" / "src"), "this-project")
            self.assertEqual(len(list(outbox.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
