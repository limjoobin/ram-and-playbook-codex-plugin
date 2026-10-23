from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import Config, PluginError, load_config, public_error  # noqa: E402
from ram_plugin.credentials import load_credential_file  # noqa: E402
from ram_plugin.mcp_server import TOOLS, call_tool  # noqa: E402
from ram_plugin.ram import RAMHTTPError, SharedMemory  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="qa-store",
    namespace="northstar-pilot-qa",
    participant="editor-user",
    api_key="test-secret-never-display",
)


class FakeRAM:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.creates = 0
        self.updates = 0
        self.fail_create_after_save = False

    def search(self, request, timeout_ms=None):
        namespace = request.get("filter", {}).get("namespace", {}).get("eq")
        return {"items": [record.copy() for record in self.records.values() if record.get("namespace") == namespace]}

    def get(self, memory_id):
        if memory_id not in self.records:
            raise RAMHTTPError(404)
        return self.records[memory_id].copy()

    def create(self, memories):
        self.creates += 1
        for memory in memories:
            self.records[memory["id"]] = {
                **memory,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
            }
        if self.fail_create_after_save:
            raise TimeoutError()
        return {"created": [memory["id"] for memory in memories], "errors": []}

    def update(self, memory_id, changes):
        self.updates += 1
        self.records[memory_id].update(changes)
        return self.records[memory_id].copy()


class PythonPluginTests(unittest.TestCase):
    def test_configuration_rejects_missing_and_credential_bearing_endpoint(self):
        with self.assertRaisesRegex(PluginError, "RAM_API_KEY"):
            load_config({})
        values = {
            "RAM_ENDPOINT": "https://user:password@example.test/path?secret=yes",
            "RAM_STORE_ID": "store",
            "RAM_NAMESPACE": "namespace",
            "RAM_PARTICIPANT": "participant",
            "RAM_API_KEY": "secret",
        }
        with self.assertRaisesRegex(PluginError, "without credentials"):
            load_config(values)

    def test_credential_file_must_be_private_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "editor.env"
            path.write_text(
                "RAM_ENDPOINT=https://example.test\n"
                "RAM_STORE_ID=store\nRAM_NAMESPACE=namespace\n"
                "RAM_PARTICIPANT=participant\nRAM_API_KEY=secret\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            with self.assertRaisesRegex(PluginError, "0600"):
                load_credential_file(path)
            path.chmod(0o600)
            self.assertEqual(load_credential_file(path).store_id, "store")
            path.write_text(path.read_text() + "UNEXPECTED=value\n", encoding="utf-8")
            with self.assertRaisesRegex(PluginError, "unexpected"):
                load_credential_file(path)
            if hasattr(os, "symlink"):
                link = Path(directory) / "link.env"
                link.symlink_to(path)
                with self.assertRaisesRegex(PluginError, "not a symlink"):
                    load_credential_file(link)

    def test_search_and_update_enforce_namespace(self):
        client = FakeRAM()
        client.records["inside"] = {
            "id": "inside",
            "text": "Pilot in Singapore",
            "namespace": CONFIG.namespace,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        service = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1)
        self.assertEqual(service.search("pilot")["memories"][0]["memory_id"], "inside")
        client.records["inside"]["namespace"] = "other"
        with self.assertRaisesRegex(PluginError, "outside"):
            service.update("inside", "Denied")
        self.assertEqual(client.updates, 0)

    def test_timeout_after_publish_reconciles_without_duplicate(self):
        client = FakeRAM()
        client.fail_create_after_save = True
        result = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1).publish("Approved fact")
        self.assertEqual(result["outcome"], "saved_and_searchable")
        self.assertEqual(client.creates, 1)

    def test_tool_contract_is_strict_and_errors_are_sanitized(self):
        self.assertEqual(
            [tool["name"] for tool in TOOLS],
            ["editor_status", "editor_search", "editor_publish", "editor_update"],
        )
        client = FakeRAM()
        service = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1)
        invalid = call_tool("editor_search", {"query": "pilot", "namespace": "other"}, lambda: service)
        self.assertTrue(invalid["isError"])
        self.assertEqual(client.creates + client.updates, 0)
        error = public_error(type("PrivateFailure", (Exception,), {"status_code": 424, "error_type": "/errors/resource-unavailable"})(CONFIG.api_key))
        self.assertNotIn(CONFIG.api_key, str(error))


if __name__ == "__main__":
    unittest.main()
