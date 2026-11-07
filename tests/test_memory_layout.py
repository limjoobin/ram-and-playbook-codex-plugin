"""Compact (default) and expanded RAM storage layouts for management records."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins" / "redis-shared-memory-editor" / "server"))

from admin_bootstrap.bundle import Bundle  # noqa: E402
from admin_bootstrap.context_pipeline import expected_observations  # noqa: E402
from ram_plugin.config import Config, PluginError, load_config  # noqa: E402
from ram_plugin.layout import (  # noqa: E402
    COMPACT_FIELDS,
    FILTER_FIELDS,
    decode_record,
    encode_filter,
    encode_record,
)
from ram_plugin.management import PluginService  # noqa: E402
from ram_plugin.ram import RAMClient  # noqa: E402
from reconciliation.job import ReconciliationJob  # noqa: E402


BUNDLE = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")
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
SETTINGS = {
    "IRIS_AGENT_MEMORY_URL": "https://memory.example.test",
    "IRIS_AGENT_MEMORY_STORE_ID": "st_0123456789abcdef0123456789abcdef",
    "IRIS_AGENT_MEMORY_API_KEY": "placeholder",
    "RAM_NAMESPACE": "shared-team",
    "RAM_PARTICIPANT": "alice",
    "RAM_AGENDA_OWNER_ID": "ami-project-office",
    "IRIS_AGENT_PLAYBOOKS_URL": "https://playbook.example.test",
    "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID": "pb_" + "0" * 32,
    "IRIS_AGENT_PLAYBOOKS_API_KEY": "placeholder",
}


class StoreSDK:
    """An in-memory Agent Memory store speaking the generated SDK's shapes."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.namespaces = [{"namespaceId": "ns_shared", "name": "shared-team", "scope": "SHARED"}]

    def list_namespaces(self, **kwargs):
        scope = kwargs.get("scope")
        return {"items": [item for item in self.namespaces if scope in (None, item["scope"])]}

    def get_namespace(self, **kwargs):
        return {"namespace": next(n for n in self.namespaces if n["namespaceId"] == kwargs["namespace_id"])}

    def bulk_create_long_term_memories(self, **kwargs):
        created, errors = [], []
        for item in kwargs["memories"]:
            if item["memory_id"] in self.records:  # RAM never overwrites on create
                errors.append({"memoryId": item["memory_id"], "status": 409})
                continue
            # RAM stores the JSON it was given; a round trip must not depend on object identity.
            self.records[item["memory_id"]] = json.loads(json.dumps(item))
            created.append(item["memory_id"])
        return {"created": created, "errors": errors}

    def upsert_long_term_memory(self, **kwargs):
        kwargs.pop("timeout_ms", None)
        self.records[kwargs["memory_id"]] = json.loads(json.dumps(kwargs))
        return self._wire(self.records[kwargs["memory_id"]])

    @staticmethod
    def _wire(item: dict) -> dict:
        wire = {
            "memoryId": item["memory_id"],
            "text": item["text"],
            "ownerId": item.get("owner_id"),
            "memoryType": item.get("memory_type"),
            "topics": item.get("topics", []),
            "attributes": item.get("attributes", {}),
        }
        if item.get("namespace_id"):
            wire["namespaceId"] = item["namespace_id"]
        return wire

    def search_long_term_memory(self, **kwargs):
        clause = kwargs["request"].get("filter_", {})

        def matches(item: dict) -> bool:
            if "owner_id" in clause and item.get("owner_id") != clause["owner_id"]["eq"]:
                return False
            if "memory_type" in clause and item.get("memory_type") != clause["memory_type"]["eq"]:
                return False
            attributes = item.get("attributes", {})
            return all(
                attributes.get(name) == next(iter(value.values()))
                for name, value in clause.get("attributes", {}).items()
            )

        found = [self._wire(item) for item in self.records.values() if matches(item)]
        start = int(kwargs["request"].get("cursor") or 0)
        end = start + int(kwargs["request"].get("limit") or 100)
        page = {"items": found[start:end]}
        if end < len(found):
            page["nextCursor"] = str(end)
        return page

    def get_long_term_memory(self, **kwargs):
        return self._wire(self.records[kwargs["memory_id"]])


def _observations() -> list[dict]:
    return [
        {
            "id": record["id"],
            "text": record["text"],
            "ownerId": CONFIG.agenda_owner_id,
            "memoryType": "organizational_state",
            "topics": ["organizational-state"],
            "attributes": record["attributes"],
        }
        for record in expected_observations(BUNDLE)
    ]


class CodecTests(unittest.TestCase):
    def test_compact_round_trip_preserves_every_attribute(self):
        for logical in ("organizational_state", "organizational_state_projection"):
            record = _observations()[0] | {"memoryType": logical}
            stored = encode_record(record, "compact")
            self.assertEqual(stored["memoryType"], "organizational_state")
            self.assertLessEqual(set(stored["attributes"]), set(COMPACT_FIELDS))
            self.assertEqual(
                stored["attributes"]["record_kind"],
                "projection" if logical.endswith("projection") else "observation",
            )
            self.assertEqual(decode_record(stored), record)

    def test_expanded_layout_and_other_types_are_untouched(self):
        record = _observations()[0]
        self.assertIs(encode_record(record, "expanded"), record)
        semantic = {"id": "fact-1", "text": "A team fact", "memoryType": "semantic"}
        self.assertIs(encode_record(semantic, "compact"), semantic)
        self.assertIs(decode_record(record), record)  # an expanded record reads as-is

    def test_decode_accepts_wrapped_or_serialized_details_and_keeps_filter_fields(self):
        stored = {
            "memoryType": "organizational_state",
            "attributes": {
                "schema_version": {"string": "organizational-state-projection-v1"},
                "state_kind": "decision",
                "details": json.dumps({"subject": "Scope", "state_kind": "ignored"}),
            },
        }
        decoded = decode_record(stored)
        self.assertEqual(decoded["memoryType"], "organizational_state_projection")
        self.assertEqual(decoded["attributes"]["subject"], "Scope")
        self.assertEqual(decoded["attributes"]["state_kind"], "decision")
        wrapped = dict(stored, attributes=dict(stored["attributes"], details={"object": {"impact": "High"}}))
        self.assertEqual(decode_record(wrapped)["attributes"]["impact"], "High")

    def test_compact_filters_map_the_type_and_refuse_details_attributes(self):
        projection = {"memoryType": {"eq": "organizational_state_projection"}, "attributes": {"state_kind": {"string": "risk"}}}
        self.assertEqual(encode_filter(projection, "compact")["memoryType"], {"eq": "organizational_state"})
        self.assertEqual(encode_filter(projection, "expanded"), projection)
        with self.assertRaises(ValueError):
            encode_filter({"memoryType": {"eq": "organizational_state"}, "attributes": {"subject": {"string": "x"}}}, "compact")
        self.assertEqual(len(COMPACT_FIELDS), 9)
        self.assertEqual(FILTER_FIELDS, COMPACT_FIELDS[:7])


class ConfigTests(unittest.TestCase):
    def test_layout_defaults_to_compact_and_expanded_is_opt_in(self):
        self.assertEqual(CONFIG.memory_layout, "compact")
        self.assertEqual(load_config(SETTINGS).memory_layout, "compact")
        self.assertEqual(load_config(SETTINGS | {"RAM_MEMORY_LAYOUT": "Expanded"}).memory_layout, "expanded")
        with self.assertRaises(PluginError) as invalid:
            load_config(SETTINGS | {"RAM_MEMORY_LAYOUT": "flat"})
        self.assertEqual(invalid.exception.code, "configuration_invalid")


class StoreRoundTripTests(unittest.TestCase):
    def _run(self, layout: str) -> tuple[StoreSDK, dict, dict]:
        sdk = StoreSDK()
        config = replace(CONFIG, memory_layout=layout)
        ram = RAMClient(config, client=sdk)
        ram.create(_observations())
        job = ReconciliationJob(config, ram, BUNDLE)
        return sdk, job.run(apply=True), job.run(apply=True)

    def test_both_layouts_reconcile_identically_and_idempotently(self):
        results = {}
        for layout in ("compact", "expanded"):
            sdk, first, second = self._run(layout)
            self.assertEqual(first["status"], "applied")
            self.assertEqual(second["status"], "no_changes")  # read-back equals what was written
            results[layout] = (first["projection_count"], first["observation_count"])
            types = {item["memory_type"] for item in sdk.records.values()}
            if layout == "compact":
                self.assertEqual(types, {"organizational_state"})
                for item in sdk.records.values():
                    self.assertLessEqual(set(item["attributes"]), set(COMPACT_FIELDS))
            else:
                self.assertEqual(types, {"organizational_state", "organizational_state_projection"})
        self.assertEqual(results["compact"], results["expanded"])

    def test_a_changed_projection_replaces_the_stored_one(self):
        for layout in ("compact", "expanded"):
            sdk, _, _ = self._run(layout)
            config = replace(CONFIG, memory_layout=layout)
            stale = next(
                item for item in sdk.records.values()
                if str(item["memory_id"]).startswith("projection-")
            )
            stale["text"] = "stale projection text"
            job = ReconciliationJob(config, RAMClient(config, client=sdk), BUNDLE)
            self.assertEqual(job.run(apply=True)["status"], "applied", layout)
            self.assertNotEqual(sdk.records[stale["memory_id"]]["text"], "stale projection text")
            self.assertEqual(job.run(apply=True)["status"], "no_changes", layout)

    def test_compact_store_serves_current_state_and_history(self):
        sdk, _, _ = self._run("compact")
        service = PluginService(CONFIG, RAMClient(CONFIG, client=sdk), playbook=None, editor=None)
        current = service.ram_search_state(state_kind="decision", project_id="project-ami-es2002")
        self.assertTrue(current["ok"])
        self.assertTrue(current["states"])
        self.assertTrue(all(state["state_kind"] == "decision" for state in current["states"]))
        history = service.ram_search_state(project_id="project-ami-es2002", view="history")
        self.assertEqual(len(history["observations"]), len(_observations()))

    def test_compact_store_resolves_one_state_by_id_across_pages(self):
        for layout in ("compact", "expanded"):
            sdk, _, _ = self._run(layout)
            config = replace(CONFIG, memory_layout=layout)
            service = PluginService(config, RAMClient(config, client=sdk), playbook=None, editor=None)
            states = service.ram_search_state(limit=100)["states"]
            target = states[-1]["state_id"]
            original = sdk.search_long_term_memory
            # Serve one record per page so the match is not on the first page.
            sdk.search_long_term_memory = lambda **kw: original(**{**kw, "request": {**kw["request"], "limit": 1}})
            state = service.current_state_by_id(target)
            sdk.search_long_term_memory = original
            self.assertEqual(state["state_id"], target, layout)
            with self.assertRaises(PluginError) as missing:
                service.current_state_by_id("project-ami-es2002-no-such-state")
            self.assertEqual(missing.exception.code, "state_not_found")

    def test_compact_search_on_a_details_attribute_is_a_contract_error(self):
        ram = RAMClient(CONFIG, client=StoreSDK())
        with self.assertRaises(PluginError) as raised:
            ram.search({"filter": {"memoryType": {"eq": "organizational_state"}, "attributes": {"subject": {"string": "x"}}}})
        self.assertEqual(raised.exception.code, "ram_contract_error")


if __name__ == "__main__":
    unittest.main()
