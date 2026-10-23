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
PLUGIN_ROOT = ROOT / "plugins" / "redis-shared-memory-editor"
SERVER_ROOT = PLUGIN_ROOT / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.config import Config, PluginError, VERSION, load_config, public_error  # noqa: E402
from ram_plugin.credentials import load_credential_file  # noqa: E402
from ram_plugin.mcp_server import TOOLS, call_tool  # noqa: E402
from ram_plugin.ram import RAMHTTPError, SharedMemory  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="shared-store",
    namespace="shared-namespace",
    participant="alice",
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
        return {
            "items": [
                record.copy()
                for record in self.records.values()
                if record.get("namespace") == namespace
            ]
        }

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


class PluginTests(unittest.TestCase):
    def test_marketplace_and_manifest_launch_python_plugin(self):
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        mcp = json.loads((PLUGIN_ROOT / "mcp.json").read_text())

        self.assertEqual(marketplace["name"], "redis-field-engineering")
        self.assertEqual(marketplace["plugins"][0]["name"], manifest["name"])
        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./plugins/redis-shared-memory-editor",
        )
        self.assertEqual(manifest["version"], VERSION)
        self.assertEqual(
            manifest["extensions"]["com.openai"]["interface"]["capabilities"],
            ["Read", "Write"],
        )
        self.assertNotIn("hooks", manifest["extensions"]["com.openai"])
        server = mcp["mcpServers"]["redis-shared-memory-editor"]
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["-I", "${PLUGIN_ROOT}/server/main.py"])

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

    def test_credential_file_is_private_and_accepts_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "editor.env"
            path.write_text(
                "# Shared connection\n"
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

    def test_users_share_namespace_with_distinct_attribution(self):
        client = FakeRAM()
        alice = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1)
        bob_config = replace(CONFIG, participant="bob", api_key="bob-secret")
        bob = SharedMemory(bob_config, client, visibility_ms=1, poll_ms=1)

        created = alice.publish("The support rotation starts on Monday.")
        memory_id = created["memory"]["memory_id"]
        self.assertTrue(memory_id.startswith("shared-"))
        self.assertEqual(created["contributor"], "alice")
        self.assertEqual(client.records[memory_id]["ownerId"], "alice")
        self.assertEqual(
            client.records[memory_id]["topics"],
            ["shared-memory", "explicit-shared-fact"],
        )
        shared_result = bob.search("rotation")["memories"][0]
        self.assertEqual(shared_result["memory_id"], memory_id)
        self.assertEqual(shared_result["contributor"], "alice")

    def test_search_and_update_enforce_namespace(self):
        client = FakeRAM()
        client.records["inside"] = {
            "id": "inside",
            "text": "Shared fact",
            "namespace": CONFIG.namespace,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        service = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1)
        self.assertEqual(service.search("fact")["memories"][0]["memory_id"], "inside")
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

    def test_tool_contract_is_write_capable_strict_and_sanitized(self):
        self.assertEqual(
            [tool["name"] for tool in TOOLS],
            ["editor_status", "editor_search", "editor_publish", "editor_update"],
        )
        self.assertEqual(
            [tool["annotations"]["readOnlyHint"] for tool in TOOLS],
            [True, True, False, False],
        )
        self.assertTrue(TOOLS[-1]["annotations"]["destructiveHint"])
        client = FakeRAM()
        service = SharedMemory(CONFIG, client, visibility_ms=1, poll_ms=1)
        invalid = call_tool(
            "editor_search",
            {"query": "fact", "namespace": "other"},
            lambda: service,
        )
        self.assertTrue(invalid["isError"])
        self.assertEqual(client.creates + client.updates, 0)
        private_failure = type(
            "PrivateFailure",
            (Exception,),
            {"status_code": 424, "error_type": "/errors/resource-unavailable"},
        )(CONFIG.api_key)
        self.assertNotIn(CONFIG.api_key, str(public_error(private_failure)))

    def test_stdio_server_lists_tools_without_third_party_packages(self):
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "editor_status", "arguments": {}},
            },
        ]
        with tempfile.TemporaryDirectory() as home:
            process = subprocess.run(
                [sys.executable, "-I", str(SERVER_ROOT / "main.py")],
                cwd=PLUGIN_ROOT,
                env={"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                input="".join(json.dumps(message) + "\n" for message in messages),
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["version"], VERSION)
        self.assertEqual(
            [tool["name"] for tool in responses[1]["result"]["tools"]],
            ["editor_status", "editor_search", "editor_publish", "editor_update"],
        )
        self.assertEqual(
            responses[2]["result"]["structuredContent"]["code"],
            "configuration_missing",
        )
        self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
