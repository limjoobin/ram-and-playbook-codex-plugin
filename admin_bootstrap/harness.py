"""Explicit administrator bootstrap modes over a versioned context bundle."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Protocol, Sequence

from .bundle import Bundle, BundleError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPOSITORY_ROOT / "context-models" / "management-agenda" / "v1"
DEFAULT_CREDENTIAL_FILE = Path.home() / ".config" / "redis-shared-memory" / "editor.env"
DEFAULT_ATTESTATION = REPOSITORY_ROOT / ".bootstrap" / "attestation.json"
STAGE_ORDER = ("declarations", "playbook", "corpus", "projection")
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class BootstrapError(RuntimeError):
    """A safe administrator-facing bootstrap failure."""

    def __init__(self, code: str, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.report = report


class BootstrapAdapter(Protocol):
    def inspect(self, bundle: Bundle) -> dict[str, Any]: ...
    def apply_declarations(self, bundle: Bundle) -> None: ...
    def publish_playbook(self, bundle: Bundle) -> None: ...
    def ingest_corpus(self, bundle: Bundle) -> None: ...
    def wait_for_extraction(self, bundle: Bundle) -> None: ...
    def observations(self, bundle: Bundle) -> list[dict[str, Any]]: ...
    def apply_projections(self, bundle: Bundle, projections: tuple[Any, ...]) -> None: ...
    def verify(self, bundle: Bundle, projections: tuple[Any, ...]) -> dict[str, Any]: ...


def _hash_target(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _safe_targets(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise BootstrapError("adapter_contract_error", "Adapter target hashes are invalid.")
    targets: dict[str, str] = {}
    for name, digest in value.items():
        if not isinstance(name, str) or not name.endswith("Sha256") or not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest):
            raise BootstrapError("adapter_contract_error", "Adapter target hashes are invalid.")
        targets[name] = digest
    return targets


def _verification(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("passed"), bool):
        raise BootstrapError("adapter_contract_error", "Adapter verification result is invalid.")
    checks = value.get("checks", {})
    counts = value.get("counts", {})
    cases = value.get("retrievalCases", [])
    if (
        not isinstance(checks, dict)
        or any(not isinstance(k, str) or not isinstance(v, bool) for k, v in checks.items())
        or not isinstance(counts, dict)
        or any(not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) for k, v in counts.items())
        or not isinstance(cases, list)
    ):
        raise BootstrapError("adapter_contract_error", "Adapter verification result is invalid.")
    safe_cases: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("caseId"), str) or not isinstance(item.get("passed"), bool):
            raise BootstrapError("adapter_contract_error", "Adapter retrieval verification is invalid.")
        safe_cases.append({"caseId": item["caseId"], "passed": item["passed"]})
    if len({item["caseId"] for item in safe_cases}) != len(safe_cases):
        raise BootstrapError("adapter_contract_error", "Adapter retrieval verification is invalid.")
    return {
        "passed": value["passed"],
        "checks": dict(sorted(checks.items())),
        "counts": dict(sorted(counts.items())),
        "retrievalCases": safe_cases,
    }


def _checked_verification(bundle: Bundle, value: object) -> dict[str, Any]:
    result = _verification(value)
    expected_cases = bundle.verification_case_ids()
    case_results = {item["caseId"]: item["passed"] for item in result["retrievalCases"]}
    expectation_checks = {
        "expectedArtifactCount": result["counts"].get("artifactCount")
        == bundle.expected.get("artifactCount"),
        "minimumObservationCount": result["counts"].get("observationCount", -1)
        >= bundle.expected.get("minimumObservationCount", 0),
        "minimumProjectionCount": result["counts"].get("projectionCount", -1)
        >= bundle.expected.get("minimumProjectionCount", 0),
        "representativeRetrievalCases": set(case_results) == set(expected_cases)
        and all(case_results.values()),
    }
    result["checks"].update(expectation_checks)
    result["checks"] = dict(sorted(result["checks"].items()))
    result["passed"] = result["passed"] and all(result["checks"].values())
    return result


@dataclass
class BootstrapHarness:
    bundle: Bundle
    adapter: BootstrapAdapter
    attestation_path: Path

    def plan(self) -> dict[str, Any]:
        inspection = self.adapter.inspect(self.bundle)
        if not isinstance(inspection, dict):
            raise BootstrapError("adapter_contract_error", "Adapter inspection result is invalid.")
        targets = _safe_targets(inspection.get("targets"))
        services = inspection.get("services")
        current = inspection.get("components")
        capabilities = inspection.get("capabilities")
        if (
            not isinstance(services, dict)
            or any(not isinstance(k, str) or not isinstance(v, bool) for k, v in services.items())
            or not isinstance(current, dict)
            or not isinstance(capabilities, list)
            or any(stage not in STAGE_ORDER for stage in capabilities)
        ):
            raise BootstrapError("adapter_contract_error", "Adapter inspection result is invalid.")

        desired = self.bundle.desired()
        blockers = [
            {"code": "service_unavailable", "service": name}
            for name, available in sorted(services.items())
            if not available
        ]
        current_schema = inspection.get("schemaFingerprint")
        if current_schema is not None and (
            not isinstance(current_schema, str) or not HEX_DIGEST.fullmatch(current_schema)
        ):
            raise BootstrapError("adapter_contract_error", "Adapter schema fingerprint is invalid.")
        compatibility = "initial"
        if current_schema:
            if current_schema == self.bundle.schema_fingerprint:
                compatibility = "compatible"
            else:
                compatibility = "breaking"
                blockers.append(
                    {
                        "code": "breaking_schema_change",
                        "guidance": "Use a fresh test store or namespace, or run a separately approved migration; the validated corpus will not be changed in place.",
                    }
                )

        current_model_version = inspection.get("contextModelVersion")
        if current_model_version is not None and not isinstance(current_model_version, str):
            raise BootstrapError("adapter_contract_error", "Adapter model version is invalid.")

        normalized_current: dict[str, dict[str, str | None]] = {}
        actions: list[dict[str, str]] = []
        needed_stages: set[str] = set()
        any_current_component = False
        for name, component in self.bundle.components.items():
            raw = current.get(name, {})
            if not isinstance(raw, dict):
                raise BootstrapError("adapter_contract_error", "Adapter component state is invalid.")
            version = raw.get("version")
            digest = raw.get("digest")
            if version is not None and not isinstance(version, str):
                raise BootstrapError("adapter_contract_error", "Adapter component version is invalid.")
            if digest is not None and (not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest)):
                raise BootstrapError("adapter_contract_error", "Adapter component digest is invalid.")
            normalized_current[name] = {"version": version, "digest": digest}
            any_current_component = any_current_component or version is not None or digest is not None
            if (version is None) != (digest is None):
                blockers.append({"code": "current_component_unattested", "component": name})
                continue
            if version == component.version and digest == component.digest:
                continue
            if version == component.version and digest not in {None, component.digest}:
                blockers.append({"code": "version_digest_mismatch", "component": name})
                continue
            actions.append({"stage": component.stage, "component": name, "action": "apply"})
            needed_stages.add(component.stage)

        if any_current_component and current_schema is None:
            compatibility = "unknown"
            blockers.append(
                {
                    "code": "schema_fingerprint_unavailable",
                    "guidance": "Attest the current schema before deciding whether this update is compatible.",
                }
            )

        supported = set(capabilities)
        for stage in STAGE_ORDER:
            if stage in needed_stages and stage not in supported:
                blockers.append(
                    {
                        "code": "unsupported_mutation",
                        "stage": stage,
                        "guidance": "Provide a reviewed administrator adapter for the proven service operation before apply.",
                    }
                )

        status = "blocked" if blockers else ("no_changes" if not actions else "ready")
        return {
            "mode": "plan",
            "status": status,
            "currentContextModelVersion": current_model_version,
            "contextModelVersion": self.bundle.context_model_version,
            "bundleDigest": self.bundle.bundle_digest,
            "schemaCompatibility": compatibility,
            "schemaFingerprint": self.bundle.schema_fingerprint,
            "targets": targets,
            "services": dict(sorted(services.items())),
            "current": dict(sorted(normalized_current.items())),
            "desired": desired,
            "actions": sorted(actions, key=lambda item: (STAGE_ORDER.index(item["stage"]), item["component"])),
            "blockers": blockers,
        }

    def apply(self) -> dict[str, Any]:
        plan = self.plan()
        if plan["blockers"]:
            raise BootstrapError("apply_blocked", "Bootstrap apply is blocked by the plan.", plan)
        stages = {item["stage"] for item in plan["actions"]}
        if "declarations" in stages:
            self.adapter.apply_declarations(self.bundle)
        if "playbook" in stages:
            self.adapter.publish_playbook(self.bundle)
        if "corpus" in stages:
            self.adapter.ingest_corpus(self.bundle)

        self.adapter.wait_for_extraction(self.bundle)
        observations = self.adapter.observations(self.bundle)
        if not isinstance(observations, list) or any(not isinstance(item, dict) for item in observations):
            raise BootstrapError("adapter_contract_error", "Adapter observations are invalid.")
        try:
            projections = self.bundle.projector()(observations, self.bundle.projection_policy())
        except (KeyError, TypeError, ValueError) as error:
            raise BootstrapError("projection_failed", "The declared projection policy could not be applied.") from error
        if "projection" in stages or "corpus" in stages:
            self.adapter.apply_projections(self.bundle, projections)

        post_plan = self.plan()
        verification = _checked_verification(
            self.bundle, self.adapter.verify(self.bundle, projections)
        )
        post_state_matches = post_plan["status"] == "no_changes"
        verification["checks"]["postApplyState"] = post_state_matches
        verification["checks"] = dict(sorted(verification["checks"].items()))
        verification["passed"] = verification["passed"] and post_state_matches
        attestation = self._attestation(
            plan["targets"], verification, post_plan["current"]
        )
        self._write_attestation(attestation)
        return {
            "mode": "apply",
            "status": "applied" if verification["passed"] else "applied_unverified",
            "plan": plan,
            "postApplyPlan": post_plan,
            "verification": verification,
            "attestation": attestation,
        }

    def verify(self) -> dict[str, Any]:
        plan = self.plan()
        checks = {
            "services": all(plan["services"].values()),
            "components": not plan["actions"] and not plan["blockers"],
        }
        projections: tuple[Any, ...] = ()
        adapter_verification = {
            "passed": False,
            "checks": {},
            "counts": {},
            "retrievalCases": [],
        }
        if checks["services"] and checks["components"]:
            observations = self.adapter.observations(self.bundle)
            if not isinstance(observations, list) or any(
                not isinstance(item, dict) for item in observations
            ):
                raise BootstrapError("adapter_contract_error", "Adapter observations are invalid.")
            try:
                projections = self.bundle.projector()(
                    observations, self.bundle.projection_policy()
                )
            except (KeyError, TypeError, ValueError) as error:
                raise BootstrapError(
                    "projection_failed",
                    "The declared projection policy could not be applied.",
                ) from error
            adapter_verification = _checked_verification(
                self.bundle, self.adapter.verify(self.bundle, projections)
            )
        passed = all(checks.values()) and adapter_verification["passed"]
        return {
            "mode": "verify",
            "status": "passed" if passed else "failed",
            "passed": passed,
            "checks": checks,
            "plan": plan,
            "verification": adapter_verification,
        }

    def _attestation(
        self,
        targets: dict[str, str],
        verification: dict[str, Any],
        current: dict[str, dict[str, str | None]],
    ) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "contextModelVersion": self.bundle.context_model_version,
            "bundleDigest": self.bundle.bundle_digest,
            "schemaFingerprint": self.bundle.schema_fingerprint,
            "components": current,
            "targets": targets,
            "corpusVersion": self.bundle.components["corpus"].version,
            "verification": verification,
        }

    def _write_attestation(self, value: dict[str, Any]) -> None:
        path = self.attestation_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".bootstrap-", delete=False
        ) as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            temporary = Path(output.name)
        temporary.chmod(0o600)
        temporary.replace(path)


class ConfiguredServicesAdapter:
    """Read-only preflight for the reviewed plugin configuration.

    The current plugin exposes no reviewed control-plane or Playbook publication
    credentials. Mutations therefore remain deliberate contract blockers.
    """

    def __init__(self, credential_file: Path) -> None:
        server_root = REPOSITORY_ROOT / "plugins" / "redis-shared-memory-editor" / "server"
        sys.path.insert(0, str(server_root))
        from ram_plugin.credentials import load_credential_file
        from ram_plugin.playbook import PlaybookClient
        from ram_plugin.ram import RAMClient

        try:
            self.config = load_credential_file(credential_file)
        except Exception as error:
            code = getattr(error, "code", "configuration_invalid")
            message = str(error) if hasattr(error, "code") else "The external configuration could not be loaded."
            raise BootstrapError(str(code), message) from None
        self.ram = RAMClient(self.config)
        self.playbook = PlaybookClient(self.config)

    def inspect(self, bundle: Bundle) -> dict[str, Any]:
        services = {"ram": False, "playbook": False}
        try:
            self.ram.search(
                {"filter": {"namespace": {"eq": self.config.namespace}}, "limit": 1}
            )
            services["ram"] = True
        except Exception:
            pass
        try:
            inventory = set(self.playbook.inventory())
            services["playbook"] = {
                "discover_entries", "load_skill", "fetch_resource"
            } <= inventory
        except Exception:
            pass
        return {
            "targets": {
                "ramTargetSha256": _hash_target(self.config.endpoint, self.config.store_id),
                "namespaceSha256": _hash_target(self.config.namespace),
                "playbookTargetSha256": _hash_target(
                    self.config.playbook_url, self.config.playbook_id
                ),
            },
            "services": services,
            "schemaFingerprint": None,
            "components": {name: {"version": None, "digest": None} for name in bundle.components},
            "capabilities": [],
        }

    @staticmethod
    def _unsupported() -> None:
        raise BootstrapError(
            "unsupported_mutation",
            "This first adapter has no reviewed administrator mutation APIs.",
        )

    def apply_declarations(self, bundle: Bundle) -> None:
        self._unsupported()

    def publish_playbook(self, bundle: Bundle) -> None:
        self._unsupported()

    def ingest_corpus(self, bundle: Bundle) -> None:
        self._unsupported()

    def wait_for_extraction(self, bundle: Bundle) -> None:
        self._unsupported()

    def observations(self, bundle: Bundle) -> list[dict[str, Any]]:
        self._unsupported()
        return []

    def apply_projections(self, bundle: Bundle, projections: tuple[Any, ...]) -> None:
        self._unsupported()

    def verify(self, bundle: Bundle, projections: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "passed": False,
            "checks": {"administratorAdapterAvailable": False},
            "counts": {},
            "retrievalCases": [],
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "verify"))
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--credential-file", type=Path, default=DEFAULT_CREDENTIAL_FILE)
    parser.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument(
        "--confirm-admin",
        action="store_true",
        help="required for the only mutating mode: apply",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    if args.mode == "apply" and not args.confirm_admin:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "administrator_confirmation_required",
                    "message": "Re-run apply with --confirm-admin after reviewing plan output.",
                },
                indent=2,
            )
        )
        return 2
    try:
        bundle = Bundle.load(args.bundle)
        adapter = ConfiguredServicesAdapter(args.credential_file)
        harness = BootstrapHarness(bundle, adapter, args.attestation)
        result = getattr(harness, args.mode)()
    except (BootstrapError, BundleError) as error:
        payload: dict[str, Any] = {
            "status": "error",
            "code": getattr(error, "code", "bundle_invalid"),
            "message": str(error),
        }
        report = getattr(error, "report", None)
        if report is not None:
            payload["plan"] = report
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "unexpected_error",
                    "message": "Bootstrap could not be completed; review the local configuration and rerun plan without sharing credentials.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.mode == "verify" and not result["passed"]:
        return 1
    if args.mode == "apply" and not result["verification"]["passed"]:
        return 1
    return 0
