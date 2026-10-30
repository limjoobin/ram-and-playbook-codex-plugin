"""Service-independent contracts for the management-agenda context pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .bundle import Bundle, BundleError


SOURCE_ENVELOPE_FIELDS = (
    "source_artifact_id",
    "source_revision",
    "observed_at",
    "event_sequence",
    "project_id",
    "meeting_id",
    "project_step_id",
)


@dataclass(frozen=True)
class MemoryETLDocument:
    """One deterministic document revision ready for a RAM ingestion adapter."""

    document_id: str
    revision: str
    media_type: str
    content: bytes
    idempotency_key: str
    source_envelope: dict[str, Any]

    def safe_summary(self) -> dict[str, Any]:
        return {
            "documentId": self.document_id,
            "revision": self.revision,
            "mediaType": self.media_type,
            "contentSha256": hashlib.sha256(self.content).hexdigest(),
            "byteCount": len(self.content),
            "idempotencyKeySha256": hashlib.sha256(
                self.idempotency_key.encode("utf-8")
            ).hexdigest(),
        }


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BundleError(f"invalid context-pipeline JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise BundleError(f"context-pipeline file must contain an object: {path.name}")
    return value


def _corpus_manifest(bundle: Bundle) -> dict[str, Any]:
    return _object(bundle.root / "corpus" / "manifest.json")


def _source_envelope(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_artifact_id": artifact["documentId"],
        "source_revision": artifact["revision"],
        "observed_at": artifact["observedAt"],
        "event_sequence": artifact["eventSequence"],
        "project_id": artifact["projectId"],
        "meeting_id": artifact["meetingId"],
        "project_step_id": artifact["projectStepId"],
    }


def ingestion_documents(bundle: Bundle) -> tuple[MemoryETLDocument, ...]:
    """Render source envelopes and immutable documents without service assumptions."""

    manifest = _corpus_manifest(bundle)
    rendered: list[MemoryETLDocument] = []
    for artifact in manifest["artifacts"]:
        envelope = _source_envelope(artifact)
        prefix = (
            "[RAM_SOURCE_ENVELOPE] "
            + json.dumps(envelope, sort_keys=True, separators=(",", ":"))
            + "\n\n"
        ).encode("utf-8")
        source = (bundle.root / artifact["path"]).read_bytes()
        content = prefix + source
        identity = {
            "contextModelVersion": bundle.context_model_version,
            "documentId": artifact["documentId"],
            "revision": artifact["revision"],
            "renderedContentSha256": hashlib.sha256(content).hexdigest(),
        }
        rendered.append(
            MemoryETLDocument(
                document_id=artifact["documentId"],
                revision=artifact["revision"],
                media_type=artifact["mediaType"],
                content=content,
                idempotency_key=hashlib.sha256(
                    json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest(),
                source_envelope=envelope,
            )
        )
    return tuple(rendered)


def expected_observations(bundle: Bundle) -> list[dict[str, Any]]:
    """Load deterministic expected extraction output for offline contract checks."""

    relative = _corpus_manifest(bundle)["expectedObservationsPath"]
    path = bundle.root / relative
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise BundleError("expected-observation fixture cannot be read") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise BundleError(
                f"expected-observation fixture has invalid JSON on line {number}"
            ) from error
        if not isinstance(record, dict):
            raise BundleError("expected-observation fixture records must be objects")
        records.append(record)
    if not records:
        raise BundleError("expected-observation fixture is empty")
    return records


def verify_context_pipeline(bundle: Bundle) -> dict[str, Any]:
    """Exercise corpus rendering, extraction contracts, and the real projector offline."""

    documents = ingestion_documents(bundle)
    observations = expected_observations(bundle)
    manifest = _corpus_manifest(bundle)
    envelopes = {
        artifact["documentId"]: _source_envelope(artifact)
        for artifact in manifest["artifacts"]
    }
    schema = _object(bundle.root / "memory-types" / "organizational-state.json")
    field_names = {
        field["name"] for field in schema["customMemoryType"]["fields"]
    }
    observation_ids: set[str] = set()
    for record in observations:
        memory_id = record.get("id")
        attributes = record.get("attributes")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or memory_id in observation_ids
            or not isinstance(attributes, dict)
            or set(attributes) != field_names
        ):
            raise BundleError("expected observation does not match the custom memory type")
        observation_ids.add(memory_id)
        artifact_id = attributes.get("source_artifact_id")
        if artifact_id not in envelopes:
            raise BundleError("expected observation references an unknown source artifact")
        envelope = envelopes[artifact_id]
        if any(attributes.get(name) != envelope[name] for name in SOURCE_ENVELOPE_FIELDS):
            raise BundleError("expected observation does not preserve its source envelope")
        if attributes.get("relations") != {"edges": []}:
            raise BundleError("document extraction must not invent cross-state relations")

    projections = bundle.projector()(observations, bundle.projection_policy())
    by_state = {item.attributes["state_id"]: item for item in projections}
    source_ids = {
        record["attributes"]["source_artifact_id"] for record in observations
    }
    cases = _object(bundle.root / bundle.expected["retrievalCasesPath"])["cases"]
    case_results: list[dict[str, Any]] = []
    for case in cases:
        passed = True
        expected_state = case.get("expectedStateId")
        expected_source = case.get("expectedSourceArtifactId")
        if isinstance(expected_state, str):
            passed = passed and expected_state in by_state
        if isinstance(expected_source, str):
            passed = passed and expected_source in source_ids
        case_results.append({"caseId": case["caseId"], "passed": passed})

    scope = by_state.get("project-ami-es2002-decision-product-scope")
    latest_state_wins = bool(
        scope
        and scope.attributes["lifecycle_status"] == "decided"
        and scope.attributes["current_memory_id"] == "fixture-final-multiple-devices"
        and scope.attributes["observation_count"] == 2
    )
    checks = {
        "bundleValidated": True,
        "sourceEnvelopesRendered": len(documents) == manifest["artifactCount"],
        "customMemoryContract": bool(observations),
        "documentRelationsRemainEmpty": True,
        "latestSourceStateWins": latest_state_wins,
        "representativeCases": all(item["passed"] for item in case_results),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "passed": all(checks.values()),
        "contextModelVersion": bundle.context_model_version,
        "bundleDigest": bundle.bundle_digest,
        "checks": checks,
        "counts": {
            "artifactCount": len(documents),
            "expectedObservationCount": len(observations),
            "projectionCount": len(projections),
        },
        "documents": [document.safe_summary() for document in documents],
        "retrievalCases": case_results,
    }
