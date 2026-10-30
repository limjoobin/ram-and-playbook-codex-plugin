"""Load and deterministically attest a versioned context-model bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable


class BundleError(RuntimeError):
    """The committed context-model bundle is incomplete or inconsistent."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BundleError(f"invalid JSON bundle file: {path.name}") from error
    if not isinstance(value, dict):
        raise BundleError(f"bundle file must contain an object: {path.name}")
    return value


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    digest: str
    files: tuple[str, ...]
    stage: str

    def public(self) -> dict[str, str]:
        return {"version": self.version, "digest": self.digest, "stage": self.stage}


@dataclass(frozen=True)
class Bundle:
    root: Path
    context_model_version: str
    bundle_digest: str
    schema_fingerprint: str
    components: dict[str, Component]
    expected: dict[str, Any]
    manifest: dict[str, Any]

    @classmethod
    def load(cls, root: Path) -> "Bundle":
        root = root.resolve()
        manifest = _object(root / "manifest.json")
        if manifest.get("schemaVersion") != 1:
            raise BundleError("unsupported context-model manifest schema")
        model_version = manifest.get("contextModelVersion")
        definitions = manifest.get("components")
        if not isinstance(model_version, str) or not model_version or not isinstance(definitions, dict):
            raise BundleError("context-model manifest is incomplete")

        components: dict[str, Component] = {}
        for name, definition in definitions.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                raise BundleError("context-model component declaration is invalid")
            version = definition.get("version")
            files = definition.get("files")
            stage = definition.get("stage")
            if (
                not isinstance(version, str)
                or not version
                or not isinstance(files, list)
                or not files
                or not isinstance(stage, str)
                or stage not in {"declarations", "playbook", "corpus", "projection"}
            ):
                raise BundleError(f"component {name} is incomplete")
            inventory: list[dict[str, str]] = []
            resolved_files: list[str] = []
            for relative in files:
                if not isinstance(relative, str) or not relative:
                    raise BundleError(f"component {name} has an invalid file path")
                path = cls._file(root, relative)
                inventory.append({"path": relative, "sha256": _sha256(path.read_bytes())})
                resolved_files.append(relative)
            components[name] = Component(
                name=name,
                version=version,
                digest=_sha256(_canonical(inventory)),
                files=tuple(resolved_files),
                stage=stage,
            )

        required = {
            "memoryTypes",
            "entityRegistry",
            "extractionPrompt",
            "playbook",
            "corpus",
            "projectionPolicy",
            "projectionImplementation",
        }
        if set(components) != required:
            raise BundleError("context-model manifest has an unexpected component set")

        corpus_files, corpus_count = cls._validate_corpus(root)
        playbook_files = cls._validate_playbook(root)
        if set(components["playbook"].files) != playbook_files:
            raise BundleError("Playbook component inventory is incomplete")
        schema_fingerprint = cls._schema_fingerprint(root, manifest)
        expected = manifest.get("expected")
        if (
            not isinstance(expected, dict)
            or isinstance(expected.get("artifactCount"), bool)
            or not isinstance(expected.get("artifactCount"), int)
            or expected["artifactCount"] < 1
            or isinstance(expected.get("minimumObservationCount"), bool)
            or not isinstance(expected.get("minimumObservationCount"), int)
            or expected["minimumObservationCount"] < 0
            or isinstance(expected.get("minimumProjectionCount"), bool)
            or not isinstance(expected.get("minimumProjectionCount"), int)
            or expected["minimumProjectionCount"] < 0
            or not isinstance(expected.get("retrievalCasesPath"), str)
        ):
            raise BundleError("context-model verification expectations are missing")
        if expected["artifactCount"] != corpus_count:
            raise BundleError("expected artifact count differs from the corpus manifest")
        verification_path = expected["retrievalCasesPath"]
        cases = _object(cls._file(root, verification_path)).get("cases")
        if not isinstance(cases, list) or not cases:
            raise BundleError("verification cases are invalid")
        case_ids = [case.get("caseId") if isinstance(case, dict) else None for case in cases]
        if any(not isinstance(case_id, str) or not case_id for case_id in case_ids) or len(
            set(case_ids)
        ) != len(case_ids):
            raise BundleError("verification case identity is invalid")
        corpus_files.add(verification_path)
        if set(components["corpus"].files) != corpus_files:
            raise BundleError("corpus component inventory is incomplete")
        bundle_digest = _sha256(
            _canonical(
                {
                    "manifest": manifest,
                    "schemaFingerprint": schema_fingerprint,
                    "computedComponentDigests": {
                        name: item.digest
                        for name, item in sorted(components.items())
                    },
                }
            )
        )
        return cls(
            root=root,
            context_model_version=model_version,
            bundle_digest=bundle_digest,
            schema_fingerprint=schema_fingerprint,
            components=components,
            expected=expected,
            manifest=manifest,
        )

    @staticmethod
    def _file(root: Path, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise BundleError("bundle paths must stay inside the version directory")
        unresolved = root / candidate
        cursor = root
        for part in candidate.parts:
            cursor /= part
            if cursor.is_symlink():
                raise BundleError(f"bundle file is missing or unsafe: {relative}")
        path = unresolved.resolve()
        if root not in path.parents or not path.is_file():
            raise BundleError(f"bundle file is missing or unsafe: {relative}")
        return path

    @classmethod
    def _validate_corpus(cls, root: Path) -> tuple[set[str], int]:
        manifest = _object(cls._file(root, "corpus/manifest.json"))
        artifacts = manifest.get("artifacts")
        expected_observations = manifest.get("expectedObservationsPath")
        if manifest.get("schemaVersion") != 1 or not isinstance(artifacts, list) or not artifacts:
            raise BundleError("corpus manifest is incomplete")
        if not isinstance(expected_observations, str) or not expected_observations:
            raise BundleError("corpus expected-observation fixture is missing")
        if manifest.get("artifactCount") != len(artifacts):
            raise BundleError("corpus artifact count does not match its manifest")
        document_ids: set[str] = set()
        files = {"corpus/manifest.json", expected_observations}
        cls._file(root, expected_observations)
        envelope_fields = {
            "documentId", "revision", "projectId", "observedAt", "eventSequence",
            "meetingId", "projectStepId", "mediaType", "contentSha256", "byteCount",
        }
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise BundleError("corpus artifact declaration is invalid")
            relative = artifact.get("path")
            document_id = artifact.get("documentId")
            if not isinstance(relative, str) or not isinstance(document_id, str) or not document_id:
                raise BundleError("corpus artifact identity is missing")
            if not envelope_fields <= set(artifact):
                raise BundleError(f"corpus source envelope is incomplete: {document_id}")
            if (
                not isinstance(artifact.get("projectId"), str)
                or not artifact.get("projectId")
                or not isinstance(artifact.get("observedAt"), str)
                or isinstance(artifact.get("eventSequence"), bool)
                or not isinstance(artifact.get("eventSequence"), int)
                or not isinstance(artifact.get("meetingId"), str)
                or not isinstance(artifact.get("projectStepId"), str)
            ):
                raise BundleError(f"corpus source envelope is invalid: {document_id}")
            if document_id in document_ids:
                raise BundleError("corpus document identities must be unique")
            document_ids.add(document_id)
            files.add(relative)
            content = cls._file(root, relative).read_bytes()
            if artifact.get("contentSha256") != _sha256(content) or artifact.get("byteCount") != len(content):
                raise BundleError(f"corpus artifact digest mismatch: {document_id}")
        return files, len(artifacts)

    @classmethod
    def _validate_playbook(cls, root: Path) -> set[str]:
        manifest = _object(cls._file(root, "playbook/manifest.json"))
        resources = manifest.get("resources")
        intents = manifest.get("intents")
        if (
            manifest.get("schemaVersion") != 1
            or manifest.get("entryType") != "skill"
            or not isinstance(manifest.get("entryKey"), str)
            or not isinstance(manifest.get("version"), int)
            or not isinstance(resources, list)
            or not resources
            or not isinstance(intents, list)
            or not 1 <= len(intents) <= 5
            or any(not isinstance(intent, str) or not intent for intent in intents)
        ):
            raise BundleError("Playbook bundle manifest is incomplete")
        paths = {"playbook/manifest.json"}
        resource_paths: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                raise BundleError("Playbook resource declaration is invalid")
            relative = resource.get("path")
            digest = resource.get("sha256")
            if (
                not isinstance(relative, str)
                or relative in resource_paths
                or not isinstance(digest, str)
            ):
                raise BundleError("Playbook resource declaration is invalid")
            resource_paths.add(relative)
            paths.add(f"playbook/{relative}")
            content = cls._file(root, f"playbook/{relative}").read_bytes()
            if digest != _sha256(content):
                raise BundleError(f"Playbook resource digest mismatch: {relative}")
        return paths

    @classmethod
    def _schema_fingerprint(cls, root: Path, manifest: dict[str, Any]) -> str:
        schema_paths = manifest.get("breakingSchemaFiles")
        if not isinstance(schema_paths, list) or not schema_paths:
            raise BundleError("breaking schema files are not declared")
        contracts: list[dict[str, Any]] = []
        for relative in schema_paths:
            if not isinstance(relative, str):
                raise BundleError("breaking schema file path is invalid")
            schema = _object(cls._file(root, relative))
            memory_type = schema.get("customMemoryType")
            fields = memory_type.get("fields") if isinstance(memory_type, dict) else None
            if not isinstance(memory_type, dict) or not isinstance(fields, list):
                raise BundleError("memory-type schema is invalid")
            field_contract = []
            for field in fields:
                if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not isinstance(field.get("type"), str):
                    raise BundleError("memory-type field contract is invalid")
                field_contract.append({"name": field["name"], "type": field["type"]})
            contracts.append(
                {
                    "name": memory_type.get("name"),
                    "fields": field_contract,
                    "required": schema.get("requiredAfterNormalization", schema.get("requiredFields", [])),
                    "controlledValues": schema.get("controlledValues", {}),
                }
            )
        return _sha256(_canonical(contracts))

    def desired(self) -> dict[str, dict[str, str]]:
        return {name: item.public() for name, item in sorted(self.components.items())}

    def projection_policy(self) -> dict[str, Any]:
        return _object(self._file(self.root, "projection-policy.json"))

    def verification_case_ids(self) -> tuple[str, ...]:
        relative = self.expected.get("retrievalCasesPath")
        if not isinstance(relative, str):
            raise BundleError("verification case path is missing")
        value = _object(self._file(self.root, relative))
        cases = value.get("cases")
        if value.get("schemaVersion") != 1 or not isinstance(cases, list) or not cases:
            raise BundleError("verification cases are invalid")
        case_ids: list[str] = []
        for case in cases:
            case_id = case.get("caseId") if isinstance(case, dict) else None
            if not isinstance(case_id, str) or not case_id or case_id in case_ids:
                raise BundleError("verification case identity is invalid")
            case_ids.append(case_id)
        return tuple(case_ids)

    def projector(self) -> Callable[[list[dict[str, Any]], dict[str, Any]], tuple[Any, ...]]:
        path = self._file(self.root, "projector.py")
        module_name = f"_context_projector_{self.components['projectionImplementation'].digest}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise BundleError("projection implementation cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        assert isinstance(module, ModuleType)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        projector = getattr(module, "build_projections", None)
        if not callable(projector):
            raise BundleError("projection implementation has no build_projections function")
        return projector
