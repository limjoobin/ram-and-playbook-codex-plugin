"""Seed, verify, or explicitly reset only the six Northstar fixture IDs."""
import argparse
import getpass
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import uuid
from urllib.parse import urlparse

from redis_agent_memory import AgentMemory

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "northstar.json"


def records(namespace):
    return [dict(id="fixture-" + str(uuid.uuid5(uuid.NAMESPACE_URL, namespace.lower() + "/" + f["key"])),
                 text=f["fact"], namespace=namespace, owner_id="northstar-demo",
                 memory_type="semantic", topics=["northstar-pilot", "fixture", f["key"]])
            for f in json.loads(FIXTURES.read_text())]


def error_code(exc):
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return {401: "authentication_failed", 403: "access_denied", 404: "not_found", 429: "rate_limited"}.get(status, "request_failed")


def seed(client, namespace, reset=False):
    wanted = records(namespace)
    missing = []
    # Finish preflight before any writes; never mistake a connectivity failure for absence.
    existing = {}
    for record in wanted:
        try:
            item = client.get_long_term_memory(memory_id=record["id"])
            if (item.namespace or "").lower() != namespace.lower():
                raise ValueError("Fixture ID belongs to a different namespace; no writes performed.")
            existing[record["id"]] = item
        except Exception as exc:
            if error_code(exc) != "not_found":
                raise
            missing.append(record)
    failures = []
    if missing:
        result = client.bulk_create_long_term_memories(memories=missing)
        failures = [r["id"] for r in missing if r["id"] not in result.created]
        failures += [e.id for e in (result.errors or []) if e.id not in failures]
    if reset:
        for record in wanted:
            if record["id"] in existing:
                client.update_long_term_memory(memory_id=record["id"], text=record["text"],
                    namespace=namespace, owner_id=existing[record["id"]].owner_id,
                    session_id=existing[record["id"]].session_id or "", topics=record["topics"])
    return {"created": len(missing) - len(failures), "preserved": len(existing) if not reset else 0,
            "reset": len(existing) if reset else 0, "failed_ids": failures}


def verify(client, namespace, expected_baseline=False, timeout=30):
    wanted = records(namespace)
    current = []
    for record in wanted:
        item = client.get_long_term_memory(memory_id=record["id"])
        if (item.namespace or "").lower() != namespace.lower():
            raise ValueError("Fixture namespace mismatch.")
        if expected_baseline and item.text != record["text"]:
            raise ValueError("Reset did not restore a fixture.")
        current.append(item)
    deadline = time.monotonic() + timeout
    pending = {r.id for r in current}
    while True:
        result = client.search_long_term_memory(request={"filter": {"namespace": {"eq": namespace}}, "limit": 100})
        visible = {r.id: r.text for r in result.items}
        pending = {r.id for r in current if visible.get(r.id) != r.text}
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return {"verified_ids": [r.id for r in current if r.id not in pending], "search_pending_ids": sorted(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "verify", "reset"])
    parser.add_argument("--namespace", choices=["northstar-pilot-demo", "northstar-pilot-qa"], default="northstar-pilot-demo")
    args = parser.parse_args()
    endpoint, store_id = os.getenv("RAM_ENDPOINT", ""), os.getenv("RAM_STORE_ID", "")
    url = urlparse(endpoint)
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment:
        parser.error("Set RAM_ENDPOINT to your HTTPS endpoint without credentials or query parameters.")
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", store_id):
        parser.error("Set RAM_STORE_ID to the demo store ID.")
    key = os.getenv("RAM_API_KEY") or getpass.getpass("RAM API key (hidden): ")
    if not key.strip():
        parser.error("RAM API key is required.")
    logger = logging.getLogger("ram-seed-quiet")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    try:
        with AgentMemory(endpoint, store_id=store_id, api_key=key, timeout_ms=8000,
                         retry_config=None, debug_logger=logger) as client:
            summary = {} if args.action == "verify" else seed(client, args.namespace, args.action == "reset")
            if summary.get("failed_ids"):
                print(json.dumps({"namespace": args.namespace, **summary, "message": "Some fixtures failed. Successful records remain stored; seed again to create only the missing records."}, indent=2))
                return 1
            summary.update(verify(client, args.namespace, args.action == "reset"))
            print(json.dumps({"namespace": args.namespace, **summary}, indent=2))
            return 1 if summary.get("failed_ids") or summary["search_pending_ids"] else 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": error_code(exc), "message": "Seed/verification did not finish. Check settings and run verify before retrying. No raw API error is printed."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
