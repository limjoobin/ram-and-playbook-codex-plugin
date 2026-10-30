from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from admin_bootstrap.bundle import Bundle  # noqa: E402
from admin_bootstrap.context_pipeline import (  # noqa: E402
    expected_observations,
    ingestion_documents,
    verify_context_pipeline,
)
from admin_bootstrap.memory_etl import ingest_documents  # noqa: E402
from admin_bootstrap.memory_etl import MemoryETLError  # noqa: E402


BUNDLE_ROOT = ROOT / "context-models" / "management-agenda" / "v1"


class FakeMemoryETL:
    def __init__(self) -> None:
        self.submissions: list[dict] = []
        self.reads: dict[str, int] = {}

    def create_document_ingestion(self, **values):
        self.submissions.append(values)
        return {"ingestionId": f"ingestion-{len(self.submissions)}"}

    def get_document_ingestion(self, ingestion_id, timeout_ms=None):
        count = self.reads.get(ingestion_id, 0)
        self.reads[ingestion_id] = count + 1
        return {"processingState": "queued" if count == 0 else "succeeded"}

    def list_document_ingestion_outputs(self, ingestion_id, timeout_ms=None):
        return {"items": [{"memoryId": f"memory-{ingestion_id}"}]}


class CurrentContractMemoryETL(FakeMemoryETL):
    def get_document_ingestion(self, ingestion_id, timeout_ms=None):
        count = self.reads.get(ingestion_id, 0)
        self.reads[ingestion_id] = count + 1
        processing = "running" if count == 0 else "succeeded"
        return {"ingestion": {"ingestionId": ingestion_id, "status": {"processing": processing}}}

    def list_document_ingestion_outputs(self, ingestion_id, timeout_ms=None):
        return {"memoryIds": [f"memory-{ingestion_id}"]}


class ContextPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = Bundle.load(BUNDLE_ROOT)

    def test_offline_pipeline_exercises_extraction_contract_and_real_projector(self):
        result = verify_context_pipeline(self.bundle)

        self.assertTrue(result["passed"])
        self.assertEqual(result["counts"], {
            "artifactCount": 2,
            "expectedObservationCount": 3,
            "projectionCount": 2,
        })
        self.assertTrue(result["checks"]["latestSourceStateWins"])

    def test_memory_etl_documents_have_deterministic_source_envelopes(self):
        first = ingestion_documents(self.bundle)
        second = ingestion_documents(self.bundle)

        self.assertEqual(first, second)
        self.assertEqual(
            first[1].source_envelope["meeting_id"],
            "meeting-ami-es2002a-kickoff",
        )
        prefix, body = first[0].content.split(b"\n\n", 1)
        self.assertTrue(prefix.startswith(b"[RAM_SOURCE_ENVELOPE] "))
        self.assertIn(b"# Final report", body)

    def test_expected_observations_preserve_the_source_envelope(self):
        records = expected_observations(self.bundle)

        self.assertEqual(len(records), 3)
        self.assertTrue(
            all(record["attributes"]["relations"] == {"edges": []} for record in records)
        )

    def test_memory_etl_orchestration_waits_then_names_reconciliation_next(self):
        ram = FakeMemoryETL()

        result = ingest_documents(
            ram,
            ingestion_documents(self.bundle),
            owner_id="ami-project-office",
            extractor_id="organizational-state-documents",
            poll_seconds=0.01,
            sleep=lambda _: None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["artifactCount"], 2)
        self.assertEqual(len(ram.submissions), 2)
        self.assertTrue(
            all(item["idempotency_key"] for item in ram.submissions)
        )
        self.assertIn("reconcile_management_state.py --apply", result["nextStep"])

    def test_rehydration_id_scopes_idempotency_without_changing_documents(self):
        documents = ingestion_documents(self.bundle)
        first = FakeMemoryETL()
        retry = FakeMemoryETL()
        next_reset = FakeMemoryETL()

        for ram, rehydration_id in (
            (first, "reset-2032-07-19"),
            (retry, "reset-2032-07-19"),
            (next_reset, "reset-2032-07-20"),
        ):
            ingest_documents(
                ram,
                documents,
                owner_id="orion-project-office",
                extractor_id="organizational-state-documents",
                rehydration_id=rehydration_id,
                poll_seconds=0.01,
                sleep=lambda _: None,
            )

        first_keys = [item["idempotency_key"] for item in first.submissions]
        self.assertEqual(
            first_keys,
            [item["idempotency_key"] for item in retry.submissions],
        )
        self.assertNotEqual(
            first_keys,
            [item["idempotency_key"] for item in next_reset.submissions],
        )
        first_revisions = [item["revision"] for item in first.submissions]
        self.assertEqual(
            first_revisions,
            [item["revision"] for item in retry.submissions],
        )
        self.assertNotEqual(
            first_revisions,
            [item["revision"] for item in next_reset.submissions],
        )
        self.assertTrue(all("-rehydration-" in item for item in first_revisions))
        for submission in first.submissions:
            prefix = submission["content"].split(b"\n\n", 1)[0]
            self.assertIn(submission["revision"].encode("utf-8"), prefix)
        self.assertEqual(documents, ingestion_documents(self.bundle))

    def test_rehydration_id_is_bounded(self):
        with self.assertRaises(MemoryETLError):
            ingest_documents(
                FakeMemoryETL(),
                ingestion_documents(self.bundle),
                owner_id="orion-project-office",
                extractor_id="organizational-state-documents",
                rehydration_id="contains spaces",
            )

    def test_current_nested_memory_etl_contract_is_supported(self):
        ram = CurrentContractMemoryETL()

        result = ingest_documents(
            ram,
            ingestion_documents(self.bundle),
            owner_id="orion-project-office",
            extractor_id="organizational-state-documents",
            poll_seconds=0.01,
            sleep=lambda _: None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [artifact["outputCount"] for artifact in result["artifacts"]],
            [1, 1],
        )

    def test_validation_cli_is_offline_and_machine_readable(self):
        process = subprocess.run(
            [sys.executable, "scripts/validate_context_pipeline.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["counts"]["artifactCount"], 2)


if __name__ == "__main__":
    unittest.main()
