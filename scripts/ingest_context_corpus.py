#!/usr/bin/env python3
"""Plan or submit the checked-in smoke corpus through RAM MemoryETL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "plugins" / "redis-shared-memory-editor" / "server"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config" / "redis-shared-memory" / "editor.env",
        help="private editor.env path",
    )
    parser.add_argument(
        "--extractor-id",
        required=True,
        help="RAM document extractor configured with the checked-in extraction prompt",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="submit the corpus; omission prints a credential-free plan",
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--rehydration-id",
        help=(
            "stable identifier for one intentional reprocessing after a store reset; "
            "reuse the same value when retrying that run"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(SERVER_ROOT))
    from admin_bootstrap.bundle import Bundle, BundleError
    from admin_bootstrap.context_pipeline import ingestion_documents
    from admin_bootstrap.memory_etl import MemoryETLError, ingest_documents
    from ram_plugin.credentials import load_credential_file
    from ram_plugin.ram import RAMClient

    try:
        bundle = Bundle.load(ROOT / "context-models" / "management-agenda" / "v1")
        documents = ingestion_documents(bundle)
        if not args.apply:
            result = {
                "ok": True,
                "status": "planned",
                "contextModelVersion": bundle.context_model_version,
                "artifactCount": len(documents),
                "documents": [document.safe_summary() for document in documents],
                "message": "No service write occurred. Re-run with --apply after reviewing the extractor and target configuration.",
            }
        else:
            config = load_credential_file(args.config)
            result = ingest_documents(
                RAMClient(config),
                documents,
                owner_id=config.agenda_owner_id,
                extractor_id=args.extractor_id,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
                rehydration_id=args.rehydration_id,
            )
    except (BundleError, MemoryETLError) as error:
        result = {"ok": False, "status": "failed", "message": str(error)}
    except Exception as error:
        status = getattr(error, "status_code", None)
        error_type = getattr(getattr(error, "data", None), "type", None)
        problem = f" ({error_type})" if isinstance(error_type, str) and error_type else ""
        if status == 409:
            message = (
                "RAM rejected the MemoryETL request as a conflict"
                f"{problem}. The idempotency key or immutable document revision is "
                "already reserved in this store."
            )
            result = {"ok": False, "status": "failed", "message": message}
        elif isinstance(status, int):
            message = (
                f"RAM rejected the MemoryETL request with HTTP status "
                f"{status}{problem}."
            )
            result = {"ok": False, "status": "failed", "message": message}
        else:
            result = {
                "ok": False,
                "status": "failed",
                "message": "Corpus ingestion failed. Check the private configuration, extractor, and RAM availability before retrying.",
            }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
