from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_ROOT))

from admin_bootstrap.reset_store import apply_reset, plan_reset  # noqa: E402
from ram_plugin.config import Config  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    personal_namespace="private-user",
    participant="user",
    api_key="secret",
    agenda_owner_id="ami-project-office",
    playbook_mcp_url="https://playbook.example.test/v1/playbooks/shared/mcp",
    playbook_api_key="secret",
)


class FakeRAM:
    def __init__(self) -> None:
        self.memories = {f"memory-{index}" for index in range(205)}
        self.sessions = {"session-a", "session-b"}
        self.deleted_batches: list[list[str]] = []

    def search(self, request, timeout_ms=None):
        values = sorted(self.memories)
        offset = int(request.get("pageToken", "0"))
        page = values[offset : offset + 100]
        result = {"items": [{"id": value} for value in page]}
        if offset + 100 < len(values):
            result["nextPageToken"] = str(offset + 100)
        return result

    def bulk_delete_long_term_memories(self, memory_ids, timeout_ms=None):
        self.deleted_batches.append(list(memory_ids))
        deleted = [value for value in memory_ids if value in self.memories]
        self.memories.difference_update(deleted)
        return {"deleted": deleted, "errors": []}

    def list_sessions(self, page_token=None, timeout_ms=None):
        return {"items": sorted(self.sessions), "total": len(self.sessions)}

    def delete_session(self, session_id, timeout_ms=None):
        self.sessions.discard(session_id)
        return {}


class ResetStoreTests(unittest.TestCase):
    def test_plan_returns_only_safe_target_and_counts(self):
        result = plan_reset(CONFIG, FakeRAM())

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["longTermMemoryCount"], 205)
        self.assertEqual(result["sessionCount"], 2)
        self.assertEqual(len(result["targetSha256"]), 64)
        self.assertNotIn(CONFIG.endpoint, str(result))
        self.assertNotIn(CONFIG.store_id, str(result))

    def test_apply_batches_deletes_and_verifies_empty(self):
        ram = FakeRAM()

        result = apply_reset(CONFIG, ram)

        self.assertEqual(result["status"], "emptied")
        self.assertEqual(result["deletedLongTermMemoryCount"], 205)
        self.assertEqual(result["deletedSessionCount"], 2)
        self.assertEqual([len(batch) for batch in ram.deleted_batches], [100, 100, 5])
        self.assertFalse(ram.memories)
        self.assertFalse(ram.sessions)

        repeated = apply_reset(CONFIG, ram)
        self.assertEqual(repeated["deletedLongTermMemoryCount"], 0)
        self.assertEqual(repeated["deletedSessionCount"], 0)

    def test_cli_requires_explicit_destructive_confirmation(self):
        process = subprocess.run(
            [sys.executable, "scripts/reset_demo_ram.py", "--apply"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(process.returncode, 2)
        self.assertIn("--confirm-empty-store", process.stderr)


if __name__ == "__main__":
    unittest.main()
