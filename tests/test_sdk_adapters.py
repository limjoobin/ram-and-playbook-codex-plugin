"""Contract tests for the redis-iris SDK adapters (RAMClient and PlaybookClient)."""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(SERVER_ROOT))

from ram_plugin.agenda import REQUIRED_RESOURCES, SKILL_KEY, _load_policy  # noqa: E402
from ram_plugin.config import Config, PluginError, public_error  # noqa: E402
from ram_plugin.playbook import PlaybookClient  # noqa: E402
from ram_plugin.ram import RAMClient  # noqa: E402


CONFIG = Config(
    endpoint="https://memory.example.test",
    store_id="st_0123456789abcdef0123456789abcdef",
    namespace="shared-team",
    personal_namespace="private-alice",
    participant="alice",
    api_key="ram-secret",
    agenda_owner_id="ami-project-office",
    playbook_url="https://playbook.example.test",
    playbook_id="pb_0123456789abcdef0123456789abcdef",
    playbook_api_key="playbook-secret",
)


class StatusError(Exception):
    def __init__(self, status_code: int, problem_type: str | None = None) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        self.data = SimpleNamespace(type=problem_type)


class FakeMemorySDK:
    """Records calls and returns camelCase wire dicts like the generated client."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.namespaces = [
            {"namespaceId": "ns_shared", "name": "Shared-Team", "scope": "SHARED"},
        ]

    def _call(self, name, **kwargs):
        self.calls.append((name, kwargs))

    def names(self):
        return [name for name, _ in self.calls]

    def list_namespaces(self, **kwargs):
        self._call("list_namespaces", **kwargs)
        scope = kwargs.get("scope")
        items = [item for item in self.namespaces if scope in (None, item["scope"])]
        return {"items": items}

    def create_namespace(self, **kwargs):
        self._call("create_namespace", **kwargs)
        request = kwargs["request"]
        created = {
            "namespaceId": f"ns_{request['name']}",
            "name": request["name"],
            "scope": request["scope"],
        }
        self.namespaces.append(created)
        return {"namespace": created}

    def get_namespace(self, **kwargs):
        self._call("get_namespace", **kwargs)
        for item in self.namespaces:
            if item["namespaceId"] == kwargs["namespace_id"]:
                return {"namespace": item}
        raise StatusError(404)

    def search_long_term_memory(self, **kwargs):
        self._call("search", **kwargs)
        return {
            "items": [
                {
                    "memoryId": "memory-1",
                    "text": "Yellow case",
                    "ownerId": "ami-project-office",
                    "memoryType": "organizational_state",
                    "namespaceId": "ns_shared",
                    "attributes": {"schema_version": "v3"},
                    "sources": [{"sourceId": "doc-1", "kind": "DOCUMENT"}],
                },
                {"memoryId": "memory-2", "text": "Unnamespaced"},
            ],
            "nextCursor": "cursor-2",
        }

    def get_long_term_memory(self, **kwargs):
        self._call("get", **kwargs)
        return {"memoryId": kwargs["memory_id"], "text": "x", "namespaceId": "ns_shared"}

    def bulk_create_long_term_memories(self, **kwargs):
        self._call("create", **kwargs)
        return {"created": [item["memory_id"] for item in kwargs["memories"]]}

    def update_long_term_memory(self, **kwargs):
        self._call("update", **kwargs)
        return {"memoryId": kwargs["memory_id"], "text": kwargs.get("text")}

    def list_memory_source_evidence(self, **kwargs):
        self._call("evidence", **kwargs)
        return {"source": {"sourceId": kwargs["source_id"], "evidenceNextCursor": "e-2"}}

    def add_session_event(self, **kwargs):
        self._call("add_session_event", **kwargs)
        return {"event": {"eventId": "event-1", "sessionId": kwargs["session_id"]}}

    def list_document_ingestion_outputs(self, **kwargs):
        self._call("outputs", **kwargs)
        if kwargs.get("cursor") is None:
            return {"items": [{"memoryId": "a"}], "nextCursor": "page-2"}
        return {"items": [{"memoryId": "b"}]}

    def create_document_ingestion(self, **kwargs):
        self._call("ingest", **kwargs)
        return SimpleNamespace(result={"ingestion": {"ingestionId": "ing-1"}})


class RAMAdapterTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeMemorySDK()
        self.ram = RAMClient(CONFIG, client=self.sdk)

    def test_search_translates_request_and_records(self):
        result = self.ram.search(
            {
                "text": "colour",
                "similarityThreshold": 0.4,
                "limit": 5,
                "pageToken": "cursor-1",
                "filterOp": "all",
                "filter": {
                    "ownerId": {"eq": "ami-project-office"},
                    "memoryType": {"eq": "organizational_state"},
                    "attributes": {"state_kind": {"string": "decision"}},
                },
            }
        )
        request = [kwargs for name, kwargs in self.sdk.calls if name == "search"][0]
        self.assertEqual(
            request["request"],
            {
                "query": "colour",
                "min_score": 0.4,
                "limit": 5,
                "cursor": "cursor-1",
                "filter_": {
                    "owner_id": {"eq": "ami-project-office"},
                    "memory_type": {"eq": "organizational_state"},
                    "attributes": {"state_kind": {"string": "decision"}},
                    "op": "ALL",
                },
            },
        )
        first, second = result["items"]
        self.assertEqual(first["id"], "memory-1")
        self.assertEqual(first["namespace"], "Shared-Team")
        self.assertNotIn("memoryId", first)
        self.assertNotIn("namespaceId", first)
        self.assertEqual(first["sources"][0]["sourceId"], "doc-1")
        self.assertNotIn("namespace", second)
        self.assertEqual(result["nextPageToken"], "cursor-2")

    def test_namespace_filter_resolves_by_name_without_creating(self):
        self.ram.search({"filter": {"namespace": {"eq": "shared-team"}}, "limit": 1})
        self.assertEqual(
            self.sdk.calls[-1][1]["request"]["filter_"]["namespace_id"], {"eq": "ns_shared"}
        )
        self.sdk.calls.clear()
        self.assertEqual(
            self.ram.search({"filter": {"namespace": {"eq": "missing"}}, "limit": 1}),
            {"items": []},
        )
        self.assertNotIn("create_namespace", self.sdk.names())
        self.assertNotIn("search", self.sdk.names())
        with self.assertRaises(PluginError):
            self.ram.search({"filter": {"namespace": {"ne": "shared-team"}}})

    def test_create_maps_record_and_creates_shared_namespace_once(self):
        record = {
            "id": "observation-1",
            "text": "Completed",
            "namespace": "new-team",
            "ownerId": "ami-project-office",
            "memoryType": "organizational_state",
            "topics": ["organizational-state"],
            "attributes": {"schema_version": "v3"},
            "sessionId": "",
        }
        self.assertEqual(self.ram.create([record])["created"], ["observation-1"])
        self.ram.create([dict(record, id="observation-2")])
        creates = [kwargs for name, kwargs in self.sdk.calls if name == "create_namespace"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["request"], {"name": "new-team", "scope": "SHARED"})
        sent = [kwargs for name, kwargs in self.sdk.calls if name == "create"][0]["memories"][0]
        self.assertEqual(
            sent,
            {
                "memory_id": "observation-1",
                "text": "Completed",
                "owner_id": "ami-project-office",
                "memory_type": "organizational_state",
                "topics": ["organizational-state"],
                "attributes": {"schema_version": "v3"},
                "namespace_id": "ns_new-team",
            },
        )

    def test_session_events_use_a_personal_namespace_owned_by_the_participant(self):
        self.ram.add_session_event(
            session_id="session-1",
            actor_id="alice",
            namespace="private-alice",
            role="user",
            text="I completed the trend report.",
            created_at="2026-10-27T09:15:00Z",
            metadata={"kind": "hook_prompt"},
            idempotency_key="key-1",
        )
        created = [kwargs for name, kwargs in self.sdk.calls if name == "create_namespace"][0]
        self.assertEqual(
            created["request"],
            {"name": "private-alice", "scope": "PERSONAL", "owner_id": "alice"},
        )
        event = [kwargs for name, kwargs in self.sdk.calls if name == "add_session_event"][0]
        self.assertEqual(event["role"], "USER")
        self.assertEqual(event["namespace_id"], "ns_private-alice")
        self.assertEqual(event["content"], [{"text": "I completed the trend report."}])
        self.assertIsInstance(event["created_at"], datetime)
        self.assertEqual(event["idempotency_key"], "key-1")

    def test_update_evidence_and_ingestion_shapes(self):
        self.ram.update(
            "memory-1",
            {"text": "New", "namespace": "shared-team", "sessionId": "", "ownerId": "alice"},
        )
        update = [kwargs for name, kwargs in self.sdk.calls if name == "update"][0]
        self.assertEqual(update["namespace_id"], "ns_shared")
        self.assertNotIn("session_id", update)
        self.assertEqual(update["owner_id"], "alice")

        evidence = self.ram.evidence("memory-1", "doc-1", limit=10, page_token="e-1")
        self.assertEqual(evidence["evidenceNextPageToken"], "e-2")
        call = [kwargs for name, kwargs in self.sdk.calls if name == "evidence"][0]
        self.assertEqual(call["cursor"], "e-1")

        ingestion = self.ram.create_document_ingestion(
            document_id="doc",
            revision="r1",
            content=b"hello",
            media_type="text/markdown",
            owner_id="ami-project-office",
            extractor_id="ext",
            idempotency_key="idem",
        )
        self.assertEqual(ingestion["ingestionId"], "ing-1")
        sent = [kwargs for name, kwargs in self.sdk.calls if name == "ingest"][0]
        self.assertEqual(base64.b64decode(sent["content"]), b"hello")
        outputs = self.ram.list_document_ingestion_outputs("ing-1")
        self.assertEqual([item["memoryId"] for item in outputs["items"]], ["a", "b"])

    def test_sdk_errors_map_to_public_codes(self):
        self.assertEqual(public_error(StatusError(401))["code"], "authentication_failed")
        self.assertEqual(public_error(StatusError(404))["code"], "not_found")
        problem = public_error(StatusError(424, "/errors/database-out-of-memory"))
        self.assertEqual(problem["dependency_type"], "database_out_of_memory")

        class ReadTimeout(Exception):
            pass

        ReadTimeout.__module__ = "httpx._exceptions"
        self.assertEqual(public_error(ReadTimeout())["code"], "timeout")

        class ConnectError(Exception):
            pass

        ConnectError.__module__ = "httpx._exceptions"
        self.assertEqual(public_error(ConnectError())["code"], "network_error")


def _resource(path: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        resource_id=f"res-{path}",
        path=path,
        mime_type="text/markdown",
        size_bytes=len(text),
        uri=f"playbook://skills/ent_1/versions/3/{path}",
        digest="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )


class FakePlaybookSDK:
    def __init__(self, tamper: bool = False) -> None:
        self.tamper = tamper
        self.calls: list[tuple[str, tuple, dict]] = []
        self.resources = [_resource(path, f"# {path}\n") for path in REQUIRED_RESOURCES]
        self.client = SimpleNamespace(get_playbook_health=self._health)
        self.health_error: Exception | None = None

    def _health(self):
        if self.health_error:
            raise self.health_error
        return {"status": "ok"}

    def _entry(self, pinned: bool) -> SimpleNamespace:
        return SimpleNamespace(
            entry_id="ent_1",
            entry_type="skill",
            entry_key=SKILL_KEY,
            version=3,
            score=0.9,
            intents=("agenda",),
            faq=None,
            skill=SimpleNamespace(name=SKILL_KEY, description="Agenda", uri="playbook://skills/ent_1"),
            pinned=pinned,
        )

    def discover(self, question, **kwargs):
        self.calls.append(("discover", (question,), kwargs))
        return SimpleNamespace(
            pinned=(self._entry(True),) if kwargs.get("pin") else (),
            discovered=(self._entry(False),),
            truncated=False,
        )

    def skill(self, ref, *, version=None):
        self.calls.append(("skill", (ref,), {"version": version}))
        return SimpleNamespace(
            entry_id="ent_1",
            entry_key=SKILL_KEY,
            version=version,
            name=SKILL_KEY,
            description="Agenda",
            instructions="Prepare the agenda from current state.",
            resources=tuple(self.resources),
        )

    def skill_resource(self, ref, resource_id, *, max_bytes=None):
        self.calls.append(("skill_resource", (resource_id,), {"max_bytes": max_bytes}))
        resource = next(item for item in self.resources if item.resource_id == resource_id)
        data = resource.text.encode()
        if self.tamper:
            data += b"tampered"
        return SimpleNamespace(data=data, mime_type="text/markdown; charset=utf-8")


class PlaybookAdapterTests(unittest.TestCase):
    def test_discover_load_and_fetch_feed_the_agenda_attestation(self):
        sdk = FakePlaybookSDK()
        playbook = PlaybookClient(CONFIG, client=sdk)
        policy = _load_policy(playbook)
        self.assertEqual(policy["entry_id"], "ent_1")
        self.assertEqual(policy["version"], 3)
        self.assertEqual(set(policy["resources"]), set(REQUIRED_RESOURCES))
        discover = [call for call in sdk.calls if call[0] == "discover"][0]
        self.assertEqual(discover[2]["pin"], [SKILL_KEY])
        fetched = [call for call in sdk.calls if call[0] == "skill_resource"]
        self.assertEqual(len(fetched), len(REQUIRED_RESOURCES))
        self.assertTrue(all(call[2]["max_bytes"] for call in fetched))

    def test_entries_list_pinned_first(self):
        playbook = PlaybookClient(CONFIG, client=FakePlaybookSDK())
        result = playbook.call(
            "discover_entries",
            {"query": "agenda", "limit": 5, "pinned_entries": [{"entry_key": SKILL_KEY}]},
        )
        self.assertEqual([entry["pinned"] for entry in result["entries"]], [True, False])
        self.assertEqual(result["entries"][0]["entry_key"], SKILL_KEY)

    def test_fetch_requires_a_listed_resource_and_a_matching_digest(self):
        playbook = PlaybookClient(CONFIG, client=FakePlaybookSDK(tamper=True))
        with self.assertRaises(PluginError) as unlisted:
            playbook.call("fetch_resource", {"uri": "playbook://anything"})
        self.assertEqual(unlisted.exception.code, "playbook_resource_unlisted")
        loaded = playbook.call("load_skill", {"entry_id": "ent_1", "version": 3})
        uri = loaded["content"]["resources"][0]["uri"]
        with self.assertRaises(PluginError) as mismatch:
            playbook.call("fetch_resource", {"uri": uri})
        self.assertEqual(mismatch.exception.code, "playbook_digest_mismatch")

    def test_only_reviewed_operations_and_sanitized_errors(self):
        sdk = FakePlaybookSDK()
        playbook = PlaybookClient(CONFIG, client=sdk)
        with self.assertRaises(PluginError) as denied:
            playbook.call("propose_skill", {})
        self.assertEqual(denied.exception.code, "playbook_operation_denied")
        self.assertEqual(
            playbook.inventory(), ["discover_entries", "fetch_resource", "load_skill"]
        )
        sdk.health_error = StatusError(401)
        with self.assertRaises(PluginError) as raised:
            playbook.inventory()
        self.assertEqual(raised.exception.code, "playbook_authentication_failed")
        self.assertNotIn(CONFIG.playbook_api_key, str(raised.exception))
        sdk.health_error = StatusError(503)
        with self.assertRaises(PluginError) as unavailable:
            playbook.inventory()
        self.assertEqual(unavailable.exception.code, "playbook_unavailable")


if __name__ == "__main__":
    unittest.main()
