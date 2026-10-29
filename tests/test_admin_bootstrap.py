from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from admin_bootstrap.bundle import Bundle  # noqa: E402
from admin_bootstrap.harness import BootstrapError, BootstrapHarness  # noqa: E402


BUNDLE_ROOT = ROOT / "context-models" / "management-agenda" / "v1"
TARGETS = {
    "ramTargetSha256": "1" * 64,
    "namespaceSha256": "2" * 64,
    "playbookTargetSha256": "3" * 64,
}


def observation(memory_id: str = "lcd-current", offset: int = 738_920) -> dict:
    return {
        "id": memory_id,
        "text": "Remove LCD display and advanced chip",
        "attributes": {
            "schema_version": "organizational-state-v2",
            "state_id": "project-ami-es2002-decision-remove-lcd-advanced-chip",
            "state_kind": "decision",
            "lifecycle_status": "decided",
            "evidence_role": "creates",
            "subject": "Remove LCD display and advanced chip",
            "project_id": "project-ami-es2002",
            "project_step_id": "project-step-ami-es2002-detailed-design",
            "meeting_id": "meeting-ami-es2002d-detailed-design",
            "accountable_entity_id": "",
            "related_entity_ids": [],
            "observed_at": "2004-12-13T00:00:00Z",
            "event_sequence": 4,
            "source_offset_ms": offset,
            "effective_at": "",
            "due_at": "",
            "resolved_at": "",
            "requested_decision": "",
            "impact": "",
            "supersedes_state_ids": [],
            "source_artifact_id": "ami-es2002d-transcript",
            "source_revision": "ami-v1",
            "evidence_locator": "00:12:18.920 Laura",
        },
    }


class FakeAdapter:
    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle
        self.context_model_version = None
        self.schema_fingerprint = None
        self.current = {
            name: {"version": None, "digest": None} for name in bundle.components
        }
        self.services = {"ram": True, "playbook": True}
        self.capabilities = ["declarations", "playbook", "corpus", "projection"]
        self.records = [observation()]
        self.calls: list[str] = []
        self.mutations: list[str] = []
        self.passed = True
        self.counts = {
            "artifactCount": bundle.expected["artifactCount"],
            "observationCount": len(self.records),
            "projectionCount": 1,
        }
        self.secret = "never-print-this-secret"

    def inspect(self, bundle: Bundle) -> dict:
        self.calls.append("inspect")
        return {
            "targets": TARGETS,
            "services": dict(self.services),
            "contextModelVersion": self.context_model_version,
            "schemaFingerprint": self.schema_fingerprint,
            "components": {name: dict(value) for name, value in self.current.items()},
            "capabilities": list(self.capabilities),
        }

    def _apply_stage(self, stage: str) -> None:
        self.calls.append(stage)
        self.mutations.append(stage)
        for name, component in self.bundle.components.items():
            if component.stage == stage:
                self.current[name] = {
                    "version": component.version,
                    "digest": component.digest,
                }
        if stage == "declarations":
            self.schema_fingerprint = self.bundle.schema_fingerprint
        self.context_model_version = self.bundle.context_model_version

    def apply_declarations(self, bundle: Bundle) -> None:
        self._apply_stage("declarations")

    def publish_playbook(self, bundle: Bundle) -> None:
        self._apply_stage("playbook")

    def ingest_corpus(self, bundle: Bundle) -> None:
        self._apply_stage("corpus")

    def wait_for_extraction(self, bundle: Bundle) -> None:
        self.calls.append("wait")

    def observations(self, bundle: Bundle) -> list[dict]:
        self.calls.append("observations")
        return list(self.records)

    def apply_projections(self, bundle: Bundle, projections: tuple) -> None:
        self.assert_projection_contract(projections)
        self._apply_stage("projection")

    @staticmethod
    def assert_projection_contract(projections: tuple) -> None:
        if not projections or projections[0].attributes["resolution_policy_id"] != "ami-es2002-state-families-v4":
            raise AssertionError("the authoritative projector was not used")

    def verify(self, bundle: Bundle, projections: tuple) -> dict:
        self.calls.append("verify")
        self.assert_projection_contract(projections)
        components_match = all(
            self.current[name]
            == {"version": component.version, "digest": component.digest}
            for name, component in bundle.components.items()
        )
        return {
            "passed": self.passed and components_match,
            "checks": {
                "componentDigests": components_match,
                "representativeRetrieval": self.passed,
            },
            "counts": {
                **self.counts,
                "observationCount": len(self.records),
                "projectionCount": len(projections),
            },
            "retrievalCases": [
                {"caseId": "final-lcd-removal", "passed": self.passed},
                {"caseId": "kickoff-product-scope", "passed": self.passed},
            ],
        }


class AdminBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = Bundle.load(BUNDLE_ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.attestation = Path(self.temporary.name) / "attestation.json"
        self.adapter = FakeAdapter(self.bundle)
        self.harness = BootstrapHarness(self.bundle, self.adapter, self.attestation)

    def test_bundle_digest_is_deterministic_and_covers_declared_material(self) -> None:
        second = Bundle.load(BUNDLE_ROOT)

        self.assertEqual(self.bundle.bundle_digest, second.bundle_digest)
        self.assertEqual(self.bundle.schema_fingerprint, second.schema_fingerprint)
        self.assertEqual(set(self.bundle.components), {
            "memoryTypes", "entityRegistry", "extractionPrompt", "playbook",
            "corpus", "projectionPolicy", "projectionImplementation",
        })
        corpus = json.loads((BUNDLE_ROOT / "corpus/manifest.json").read_text())
        self.assertEqual(corpus["artifactCount"], 2)

    def test_bundle_digest_covers_verification_expectations(self) -> None:
        copied = Path(self.temporary.name) / "bundle"
        shutil.copytree(BUNDLE_ROOT, copied)
        manifest_path = copied / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["expected"]["minimumObservationCount"] += 1
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        changed = Bundle.load(copied)

        self.assertNotEqual(changed.bundle_digest, self.bundle.bundle_digest)

    def test_plan_is_read_only_and_reports_current_and_desired_digests(self) -> None:
        plan = self.harness.plan()

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["schemaCompatibility"], "initial")
        self.assertIsNone(plan["current"]["memoryTypes"]["digest"])
        self.assertEqual(
            plan["desired"]["memoryTypes"]["digest"],
            self.bundle.components["memoryTypes"].digest,
        )
        self.assertFalse(self.adapter.mutations)
        self.assertFalse(self.attestation.exists())

    def test_apply_runs_the_proven_sequence_and_writes_secret_safe_attestation(self) -> None:
        result = self.harness.apply()

        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            self.adapter.mutations,
            ["declarations", "playbook", "corpus", "projection"],
        )
        self.assertLess(self.adapter.calls.index("corpus"), self.adapter.calls.index("wait"))
        self.assertLess(self.adapter.calls.index("wait"), self.adapter.calls.index("projection"))
        state = json.loads(self.attestation.read_text())
        self.assertEqual(state["contextModelVersion"], self.bundle.context_model_version)
        self.assertTrue(state["verification"]["passed"])
        self.assertEqual(state["targets"], TARGETS)
        serialized = json.dumps(result)
        self.assertNotIn(self.adapter.secret, serialized)
        self.assertNotIn(self.adapter.records[0]["text"], serialized)
        if os.name != "nt":
            self.assertEqual(self.attestation.stat().st_mode & 0o777, 0o600)

    def test_apply_is_idempotent_after_every_digest_matches(self) -> None:
        self.harness.apply()
        mutations = list(self.adapter.mutations)

        second = self.harness.apply()

        self.assertEqual(second["plan"]["status"], "no_changes")
        self.assertEqual(self.adapter.mutations, mutations)

    def test_verify_is_read_only(self) -> None:
        self.harness.apply()
        self.adapter.mutations.clear()
        self.attestation.unlink()

        result = self.harness.verify()

        self.assertTrue(result["passed"])
        self.assertFalse(self.adapter.mutations)
        self.assertFalse(self.attestation.exists())

    def test_same_declared_version_with_another_digest_is_blocked(self) -> None:
        component = self.bundle.components["memoryTypes"]
        self.adapter.current["memoryTypes"] = {
            "version": component.version,
            "digest": "f" * 64,
        }

        plan = self.harness.plan()

        self.assertIn("version_digest_mismatch", {item["code"] for item in plan["blockers"]})
        with self.assertRaisesRegex(BootstrapError, "blocked"):
            self.harness.apply()
        self.assertFalse(self.adapter.mutations)

    def test_partially_attested_current_component_is_blocked(self) -> None:
        component = self.bundle.components["memoryTypes"]
        self.adapter.current["memoryTypes"] = {
            "version": component.version,
            "digest": None,
        }

        plan = self.harness.plan()

        self.assertIn("current_component_unattested", {item["code"] for item in plan["blockers"]})
        self.assertIn("schema_fingerprint_unavailable", {item["code"] for item in plan["blockers"]})

    def test_breaking_schema_requires_a_fresh_target(self) -> None:
        self.adapter.schema_fingerprint = "e" * 64

        plan = self.harness.plan()

        self.assertEqual(plan["schemaCompatibility"], "breaking")
        guidance = " ".join(item.get("guidance", "") for item in plan["blockers"])
        self.assertIn("fresh test store or namespace", guidance)
        with self.assertRaises(BootstrapError):
            self.harness.apply()
        self.assertFalse(self.adapter.mutations)

    def test_compatible_new_versions_may_be_applied(self) -> None:
        self.adapter.schema_fingerprint = self.bundle.schema_fingerprint
        self.adapter.context_model_version = "management-agenda-bootstrap-v0"
        for name in self.adapter.current:
            self.adapter.current[name] = {"version": "old", "digest": "a" * 64}

        plan = self.harness.plan()

        self.assertEqual(plan["schemaCompatibility"], "compatible")
        self.assertEqual(plan["status"], "ready")

    def test_missing_reviewed_mutation_adapter_is_a_clear_blocker(self) -> None:
        self.adapter.capabilities = []

        plan = self.harness.plan()

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(
            {item.get("stage") for item in plan["blockers"] if item["code"] == "unsupported_mutation"},
            {"declarations", "playbook", "corpus", "projection"},
        )
        with self.assertRaises(BootstrapError):
            self.harness.apply()

    def test_failed_acceptance_is_attested_without_leaking_data(self) -> None:
        self.adapter.passed = False

        result = self.harness.apply()

        self.assertEqual(result["status"], "applied_unverified")
        self.assertFalse(result["attestation"]["verification"]["passed"])
        self.assertNotIn(self.adapter.records[0]["text"], self.attestation.read_text())

    def test_declared_count_expectations_cannot_be_bypassed_by_adapter_status(self) -> None:
        self.adapter.counts["artifactCount"] = 99

        result = self.harness.apply()

        self.assertEqual(result["status"], "applied_unverified")
        self.assertFalse(result["verification"]["checks"]["expectedArtifactCount"])

    def test_cli_requires_explicit_administrator_confirmation_before_loading_credentials(self) -> None:
        process = subprocess.run(
            [sys.executable, "scripts/admin_bootstrap.py", "apply"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(process.returncode, 2)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["code"], "administrator_confirmation_required")

    def test_cli_configuration_failure_is_machine_readable_and_sanitized(self) -> None:
        missing = Path(self.temporary.name) / "missing.env"

        process = subprocess.run(
            [
                sys.executable,
                "scripts/admin_bootstrap.py",
                "plan",
                "--credential-file",
                str(missing),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(process.returncode, 2)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["code"], "configuration_missing")
        self.assertEqual(process.stderr, "")

    def test_versioned_projector_preserves_event_ordering_policy(self) -> None:
        earlier = observation("lcd-basic", 74_700)
        earlier["attributes"]["state_id"] = "project-ami-es2002-decision-basic-lcd-interface"
        earlier["attributes"]["subject"] = "Basic LCD interface"
        projections = self.bundle.projector()(
            [observation(), earlier], self.bundle.projection_policy()
        )

        self.assertEqual(len(projections), 1)
        self.assertEqual(
            projections[0].attributes["state_id"],
            "project-ami-es2002-decision-lcd-interface",
        )
        self.assertEqual(projections[0].attributes["current_memory_id"], "lcd-current")


if __name__ == "__main__":
    unittest.main()
