"""Bounded orchestration for submitting the versioned corpus through RAM MemoryETL."""

from __future__ import annotations

import time
from typing import Any, Callable

from .context_pipeline import MemoryETLDocument


class MemoryETLError(RuntimeError):
    """A sanitized corpus-ingestion failure."""


def _value(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def ingest_documents(
    ram: Any,
    documents: tuple[MemoryETLDocument, ...],
    *,
    owner_id: str,
    extractor_id: str,
    timeout_seconds: int = 600,
    poll_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
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
        response = ram.create_document_ingestion(
            document_id=document.document_id,
            revision=document.revision,
            content=document.content,
            media_type=document.media_type,
            owner_id=owner_id,
            extractor_id=extractor_id,
            idempotency_key=document.idempotency_key,
            timeout_ms=30_000,
        )
        ingestion_id = _value(response, "ingestionId", "ingestion_id", "id")
        if not isinstance(ingestion_id, str) or not ingestion_id:
            raise MemoryETLError("RAM did not return a document-ingestion identity")

        while True:
            status = ram.get_document_ingestion(ingestion_id, timeout_ms=30_000)
            state = _value(status, "processingState", "processing_state", "status", "state")
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
        items = _value(outputs, "items", "outputs", "memories")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise MemoryETLError("RAM returned invalid document-ingestion outputs")
        results.append(
            {
                "documentId": document.document_id,
                "revision": document.revision,
                "status": "succeeded",
                "outputCount": len(items),
            }
        )
    return {
        "ok": True,
        "status": "succeeded",
        "artifactCount": len(results),
        "artifacts": results,
        "nextStep": "Run scripts/reconcile_management_state.py --apply after extracted observations are visible.",
    }
