import importlib.util
from pathlib import Path
from types import SimpleNamespace as Obj
import unittest

spec = importlib.util.spec_from_file_location("seed", Path(__file__).resolve().parents[1] / "scripts" / "seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class Missing(Exception):
    status_code = 404


class Fake:
    def __init__(self):
        self.items = {}
        self.fail_id = None
        self.updates = []

    def get_long_term_memory(self, memory_id):
        if memory_id not in self.items:
            raise Missing()
        return self.items[memory_id]

    def bulk_create_long_term_memories(self, memories):
        for r in memories:
            if r["id"] != self.fail_id:
                self.items[r["id"]] = Obj(**r, session_id=None)
        return Obj(created=[r["id"] for r in memories if r["id"] != self.fail_id],
                   errors=[Obj(id=self.fail_id)] if self.fail_id else [])

    def update_long_term_memory(self, memory_id, **fields):
        self.updates.append(memory_id)
        self.items[memory_id].__dict__.update(fields)

    def search_long_term_memory(self, request):
        return Obj(items=list(self.items.values()))


class SeedTests(unittest.TestCase):
    def test_idempotency_and_preserve_live_change(self):
        client = Fake()
        seed.seed(client, "northstar-pilot-qa")
        first = next(iter(client.items.values()))
        first.text = "Updated live"
        result = seed.seed(client, "northstar-pilot-qa")
        self.assertEqual(result["created"], 0)
        self.assertEqual(first.text, "Updated live")
        self.assertEqual(len(client.items), 6)

    def test_reset_only_known_fixtures(self):
        client = Fake()
        seed.seed(client, "northstar-pilot-qa")
        client.items["unrelated"] = Obj(text="Keep this")
        seed.seed(client, "northstar-pilot-qa", reset=True)
        self.assertEqual(len(client.updates), 6)
        self.assertNotIn("unrelated", client.updates)

    def test_partial_failures_are_reported_and_only_missing_retried(self):
        client = Fake()
        client.fail_id = seed.records("northstar-pilot-qa")[0]["id"]
        result = seed.seed(client, "northstar-pilot-qa")
        self.assertEqual(result["failed_ids"], [client.fail_id])
        self.assertEqual(len(client.items), 5)
        client.fail_id = None
        self.assertEqual(seed.seed(client, "northstar-pilot-qa")["created"], 1)

    def test_namespace_specific_ids_and_verification(self):
        qa = {r["id"] for r in seed.records("northstar-pilot-qa")}
        demo = {r["id"] for r in seed.records("northstar-pilot-demo")}
        self.assertFalse(qa & demo)
        client = Fake()
        seed.seed(client, "northstar-pilot-qa")
        self.assertEqual(len(seed.verify(client, "northstar-pilot-qa")["verified_ids"]), 6)

    def test_unavailable_backend_does_not_trigger_writes(self):
        client = Fake()
        def fail(**kwargs):
            raise ConnectionError("unavailable")
        client.get_long_term_memory = fail
        with self.assertRaises(ConnectionError):
            seed.seed(client, "northstar-pilot-qa")
        self.assertFalse(client.items)


if __name__ == "__main__":
    unittest.main()
