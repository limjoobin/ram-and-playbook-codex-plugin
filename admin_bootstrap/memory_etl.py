"""Bounded orchestration for submitting the versioned corpus through RAM MemoryETL."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable

from .context_pipeline import MemoryETLDocument


class MemoryETLError(RuntimeError):
    """A sanitized corpus-ingestion failure."""


REHYDRATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _idempotency_key(base_key: str, rehydration_id: str | None) -> str:
    if rehydration_id is None:
        return base_key
    if not REHYDRATION_ID.fullmatch(rehydration_id):
        raise MemoryETLError(
            "rehydration_id must be 1-128 letters, digits, periods, colons, underscores, or hyphens"
        )
    return hashlib.sha256(
        f"{base_key}\0{rehydration_id}".encode("utf-8")
    ).hexdigest()


def _submission(
    document: MemoryETLDocument, rehydration_id: str | None
) -> tuple[str, bytes, str]:
    key = _idempotency_key(document.idempotency_key, rehydration_id)
    if rehydration_id is None:
        return document.revision, document.content, key

    suffix = hashlib.sha256(rehydration_id.encode("utf-8")).hexdigest()[:12]
    revision = f"{document.revision}-rehydration-{suffix}"
    _, separator, body = document.content.partition(b"\n\n")
    if not separator:
        raise MemoryETLError("document source envelope is missing")
    envelope = dict(document.source_envelope)
    envelope["source_revision"] = revision
    prefix = (
        "[RAM_SOURCE_ENVELOPE] "
        + json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        + "\n\n"
    ).encode("utf-8")
    return revision, prefix + body, key


def _value(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _processing_state(payload: dict[str, Any]) -> Any:
    ingestion = payload.get("ingestion")
    if isinstance(ingestion, dict):
        payload = ingestion
    status = payload.get("status")
    if isinstance(status, dict):
        return _value(status, "processing", "processingState", "processing_state", "state")
    return _value(payload, "processingState", "processing_state", "processing", "status", "state")


def _output_items(payload: dict[str, Any]) -> Any:
    for container_name in ("ingestion", "outputs"):
        container = payload.get(container_name)
        if isinstance(container, dict):
            payload = container
            break
    return _value(
        payload,
        "items",
        "memories",
        "memoryIds",
        "memory_ids",
        "outputs",
    )


def ingest_documents(
    ram: Any,
    documents: tuple[MemoryETLDocument, ...],
    *,
    owner_id: str,
    extractor_id: str,
    timeout_seconds: int = 600,
    poll_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    rehydration_id: str | None = None,
) -> dict[str, Any]:
    """Submit each immutable revision once, wait, and return only safe metadata."""

    if not owner_id or not extractor_id:
        raise MemoryETLError("owner_id and extractor_id are required")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise MemoryETLError("timeout_seconds must be from 1 to 3600")
    if poll_seconds <= 0 or poll_seconds > 60:
        raise MemoryETLError("poll_seconds must be greater than 0 and no more than 60")

    deadline = time.monotonic() + timeout_seconds
    results: list[dict[str, Any]] = []
    for document in documents:
        revision, content, idempotency_key = _submission(
            document, rehydration_id
        )
        response = ram.create_document_ingestion(
            document_id=document.document_id,
            revision=revision,
            content=content,
            media_type=document.media_type,
            owner_id=owner_id,
            extractor_id=extractor_id,
            idempotency_key=idempotency_key,
            timeout_ms=30_000,
        )
        ingestion_id = _value(response, "ingestionId", "ingestion_id", "id")
        if not isinstance(ingestion_id, str) or not ingestion_id:
            raise MemoryETLError("RAM did not return a document-ingestion identity")

        while True:
            status = ram.get_document_ingestion(ingestion_id, timeout_ms=30_000)
            state = _processing_state(status)
            if not isinstance(state, str):
                raise MemoryETLError("RAM returned an invalid document-ingestion state")
            normalized = state.casefold()
            if normalized in {"succeeded", "completed", "success"}:
                break
            if normalized in {"failed", "partial", "cancelled", "canceled"}:
                raise MemoryETLError(
                    f"MemoryETL did not complete successfully for {document.document_id}"
                )
            if normalized not in {"accepted", "pending", "queued", "running", "processing"}:
                raise MemoryETLError("RAM returned an unknown document-ingestion state")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MemoryETLError("MemoryETL did not finish before the bounded timeout")
            sleep(min(poll_seconds, remaining))

        outputs = ram.list_document_ingestion_outputs(ingestion_id, timeout_ms=30_000)
        items = _output_items(outputs)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise MemoryETLError("RAM returned invalid document-ingestion outputs")
        results.append(
            {
                "documentId": document.document_id,
                "revision": revision,
                "status": "succeeded",
                "outputCount": len(items),
                # The SDK returns ID strings; accept {"memoryId": ...} objects too.
                "memoryIds": [
                    item if isinstance(item, str) else str(item.get("memoryId") or item.get("memory_id") or "")
                    for item in items
                    if isinstance(item, str) or isinstance(item, dict)
                ],
            }
        )
    return {
        "ok": True,
        "status": "succeeded",
        "artifactCount": len(results),
        "artifacts": results,
        "intentionalRehydration": rehydration_id is not None,
        "nextStep": "Run scripts/reconcile_management_state.py --apply after extracted observations are visible.",
    }
