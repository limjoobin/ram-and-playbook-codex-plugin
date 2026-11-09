"""Management records live in one shared namespace, each owned by its author."""

from __future__ import annotations

from dataclasses import replace
import filecmp
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_memory_layout import BUNDLE, CONFIG, RAMStatusError, StoreSDK, _observations  # noqa: E402
from ram_plugin.config import load_config  # noqa: E402
from ram_plugin.management import PluginService  # noqa: E402
from ram_plugin.ram import RAMClient  # noqa: E402
from ram_plugin.reconcile import ReconciliationJob as PluginJob  # noqa: E402
from reconciliation.job import ReconciliationJob, adopt_unnamespaced, move_into_namespace  # noqa: E402

PLUGIN = SERVER_ROOT / "ram_plugin"


def json_copy(value):
    import json

    return json.loads(json.dumps(value))
MODEL = ROOT / "context-models" / "management-agenda" / "v1"


def _store(layout: str = "compact") -> tuple[StoreSDK, RAMClient, object]:
    sdk = StoreSDK()
    config = replace(CONFIG, memory_layout=layout)
    return sdk, RAMClient(config, client=sdk), config


class BundledProjectorTests(unittest.TestCase):
    def test_plugin_copies_are_identical_to_the_context_model(self):
        for name in ("projector.py", "projection-policy.json"):
            self.assertTrue(filecmp.cmp(PLUGIN / name, MODEL / name, shallow=False), name)

    def test_plugin_job_and_admin_job_build_the_same_projections(self):
        for job_type in ("plugin", "admin"):
            sdk, ram, config = _store()
            ram.create(_observations())
            job = PluginJob(config, ram) if job_type == "plugin" else ReconciliationJob(config, ram, BUNDLE)
            first = job.run(apply=True)
            self.assertEqual(first["status"], "applied", job_type)
            self.assertEqual(job.run(apply=True)["status"], "no_changes", job_type)


class ScopeTests(unittest.TestCase):
    def test_any_author_in_the_namespace_is_in_scope(self):
        sdk, ram, config = _store()
        records = _observations()
        records[0] = {**records[0], "ownerId": "bob"}
        ram.create(records)
        result = PluginJob(config, ram).run()
        self.assertEqual(result["observation_count"], len(records))

    def test_unnamespaced_records_are_out_of_scope_until_moved(self):
        sdk, ram, config = _store()
        records = _observations()
        legacy = {"ownerId": config.agenda_owner_id}
        ram.create([{**{key: value for key, value in item.items() if key != "namespace"}, **legacy} for item in records])
        # Another team's unnamespaced record in the same store stays where it is.
        stranger = {**{key: value for key, value in records[0].items() if key != "namespace"}, "id": "someone-else", "ownerId": "other-team"}
        ram.create([stranger])
        job = PluginJob(config, ram)
        self.assertEqual(job.run()["observation_count"], 0)

        planned = adopt_unnamespaced(config, ram, apply=False)
        self.assertEqual(planned["unnamespaced_count"], len(records))
        self.assertEqual(planned["moved_count"], 0)
        self.assertEqual(job.run()["observation_count"], 0)

        moved = adopt_unnamespaced(config, ram, apply=True)
        self.assertEqual(moved["moved_count"], len(records))
        self.assertEqual(len(moved["moved_observation_ids"]), len(records))
        self.assertTrue(job.wait_until_searchable(moved["moved_observation_ids"], timeout_seconds=0))
        self.assertEqual(job.run()["observation_count"], len(records))
        self.assertEqual(adopt_unnamespaced(config, ram, apply=True)["unnamespaced_count"], 0)
        self.assertNotIn("namespace_id", sdk.records["someone-else"])
        without_owner = replace(config, agenda_owner_id="")
        self.assertEqual(adopt_unnamespaced(without_owner, ram, apply=False)["unnamespaced_count"], 0)

    def test_moving_a_record_already_in_the_namespace_is_harmless(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        memory_id = _observations()[0]["id"]
        original = sdk.move_long_term_memories

        def move_reports_already_there(**kwargs):
            return {"moved": [], "errors": [{"memoryId": item, "status": 409} for item in kwargs["memory_ids"]]}

        sdk.move_long_term_memories = move_reports_already_there
        self.assertEqual(move_into_namespace(config, ram, [memory_id]), [memory_id])
        sdk.move_long_term_memories = original

    def test_state_search_filters_on_the_namespace(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        service = PluginService(config, ram, playbook=None, editor=None)
        current = service.ram_search_state(project_id="project-ami-es2002")
        self.assertTrue(current["states"])
        self.assertEqual(current["namespace"], config.namespace)
        self.assertEqual(current["diagnostics"]["out_of_scope_rejected"], 0)

    def test_projections_are_owned_by_whoever_rebuilt_them_and_not_rewritten_for_it(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        owners = {item["owner_id"] for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-")}
        self.assertEqual(owners, {config.participant})
        bob = replace(config, participant="bob", personal_namespace="private-bob")
        self.assertEqual(PluginJob(bob, RAMClient(bob, client=sdk)).run(apply=True)["status"], "no_changes")

    def test_old_settings_without_an_agenda_owner_still_load(self):
        settings = {
            "IRIS_AGENT_MEMORY_URL": "https://memory.example.test",
            "IRIS_AGENT_MEMORY_STORE_ID": "st_" + "0" * 32,
            "IRIS_AGENT_MEMORY_API_KEY": "placeholder",
            "RAM_NAMESPACE": "shared-team",
            "RAM_PARTICIPANT": "alice",
            "IRIS_AGENT_PLAYBOOKS_URL": "https://playbook.example.test",
            "IRIS_AGENT_PLAYBOOKS_PLAYBOOK_ID": "pb_" + "0" * 32,
            "IRIS_AGENT_PLAYBOOKS_API_KEY": "placeholder",
        }
        self.assertEqual(load_config(settings).participant, "alice")
        self.assertEqual(load_config({**settings, "RAM_AGENDA_OWNER_ID": "ami-project-office"}).participant, "alice")


class ConcurrentWriterTests(unittest.TestCase):
    def test_a_stale_replacement_is_retried_after_reading_again(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        stale = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        stale["text"] = "stale projection text"

        original = sdk.upsert_long_term_memory
        raced = []

        def upsert_once_stale(**kwargs):
            if not raced:
                raced.append(kwargs["memory_id"])
                # Another participant replaces it between our read and our write.
                sdk.records[kwargs["memory_id"]]["revision"] = "99"
            return original(**kwargs)

        sdk.upsert_long_term_memory = upsert_once_stale
        result = PluginJob(config, ram).run(apply=True, retry_delay_seconds=0)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(raced, [stale["memory_id"]])
        self.assertNotEqual(sdk.records[stale["memory_id"]]["text"], "stale projection text")

    def test_writers_that_never_settle_fail_with_a_stable_message(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        stale = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        stale["text"] = "stale projection text"

        def always_stale(**kwargs):
            raise RAMStatusError(412)

        sdk.upsert_long_term_memory = always_stale
        from ram_plugin.reconcile import ReconciliationError

        with self.assertRaisesRegex(ReconciliationError, "at the same time"):
            PluginJob(config, ram).run(apply=True, retry_delay_seconds=0)

    def _hide_projections_from_search(self, sdk):
        original = sdk.search_long_term_memory

        def search(**kwargs):
            page = original(**kwargs)
            page["items"] = [item for item in page["items"] if not str(item["memoryId"]).startswith("projection-")]
            return page

        sdk.search_long_term_memory = search

    def test_a_projection_search_has_not_returned_yet_is_replaced_not_failed(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        stale = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        stale["text"] = "stale projection text"
        self._hide_projections_from_search(sdk)  # search lags behind the earlier writes
        result = PluginJob(config, ram).run(apply=True, retry_delay_seconds=0)
        self.assertEqual(result["status"], "applied")
        self.assertNotEqual(sdk.records[stale["memory_id"]]["text"], "stale projection text")

    def test_a_projection_id_outside_the_namespace_fails_clearly(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        stale = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        stale.pop("namespace_id")
        stale["text"] = "stale projection text"
        from ram_plugin.reconcile import ReconciliationError

        with self.assertRaisesRegex(ReconciliationError, "outside the shared namespace"):
            PluginJob(config, ram).run(apply=True, retry_delay_seconds=0)

    def test_a_replacement_reads_the_revision_when_search_omits_it(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        stale = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        stale["text"] = "stale projection text"
        original_search, original_upsert = sdk.search_long_term_memory, sdk.upsert_long_term_memory
        revisions = []

        def search(**kwargs):
            page = original_search(**kwargs)
            for item in page["items"]:
                item.pop("revision", None)
            return page

        def upsert(**kwargs):
            revisions.append(kwargs.get("expected_revision"))
            return original_upsert(**kwargs)

        sdk.search_long_term_memory, sdk.upsert_long_term_memory = search, upsert
        self.assertEqual(PluginJob(config, ram).run(apply=True)["status"], "applied")
        self.assertEqual(revisions, ["1"])

    def test_a_run_behind_another_writer_does_not_undo_their_update(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        PluginJob(config, ram).run(apply=True)
        target = next(item for item in sdk.records.values() if str(item["memory_id"]).startswith("projection-"))
        # Another participant rebuilt it from an observation search has not returned to us.
        details_key = "supporting_memory_ids"
        attributes = target["attributes"]
        holder = attributes if details_key in attributes else attributes.get("details", {})
        holder = holder.get("object", holder) if isinstance(holder, dict) else holder
        holder[details_key] = list(holder[details_key]) + ["observation-not-yet-searchable"]
        before = json_copy(target)
        upserts = []
        original = sdk.upsert_long_term_memory
        sdk.upsert_long_term_memory = lambda **kwargs: upserts.append(kwargs) or original(**kwargs)
        PluginJob(config, ram).run(apply=True, retry_delay_seconds=0)
        # Two passes wait; only the last pass, which may be a deleted citation, writes.
        self.assertEqual(len(upserts), 1)
        self.assertNotEqual(before, sdk.records[target["memory_id"]])

    def test_refresh_reports_pending_when_the_observation_is_not_searchable(self):
        sdk, ram, config = _store()
        ram.create(_observations())
        result = PluginJob(config, ram).refresh_after_promotion("candidate-" + "c" * 48, timeout_seconds=0)
        self.assertEqual(result["projection_status"], "pending_reconciliation")
        self.assertEqual(result["projection_error"], "observation_not_yet_searchable")



class LegacyPromotionTests(unittest.TestCase):
    def test_a_retry_matches_a_promotion_written_under_the_former_shared_owner(self):
        from ram_plugin.promotion import PromotionService

        service = PromotionService(CONFIG, ram=None, ledger=None)
        expected = {"id": "observation-x", "text": "Done", "attributes": {"schema_version": "organizational-state-v3"}}
        stored = {**expected, "namespace": CONFIG.namespace, "memoryType": "organizational_state"}
        for owner, matches in ((CONFIG.participant, True), (CONFIG.agenda_owner_id, True), ("someone-else", False)):
            self.assertEqual(service._matches_observation({**stored, "ownerId": owner}, expected), matches, owner)


if __name__ == "__main__":
    unittest.main()
