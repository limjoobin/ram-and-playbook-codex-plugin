#!/usr/bin/env python3
"""Run the fixed offline quality gate for the installable plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SERVER = ROOT / "plugins" / "redis-shared-memory-editor" / "server"
sys.path.insert(0, str(PLUGIN_SERVER))

from ram_plugin.agenda import REQUIRED_RESOURCES  # noqa: E402
from ram_plugin.config import Config  # noqa: E402
from ram_plugin.management import PluginService  # noqa: E402


CASES_PATH = Path(__file__).with_name("cases.json")
RESULTS_PATH = Path(__file__).with_name("results.json")
REQUIRED_ITEM_FIELDS = {
    "title",
    "management_question",
    "why_now",
    "current_state",
    "owner",
    "requested_decision",
    "timebox_minutes",
    "confidence",
    "evidence_references",
}
CONFIG = Config(
    endpoint="https://memory.evaluation.invalid",
    store_id="evaluation-store",
    namespace="evaluation-namespace",
    participant="evaluation-user",
    api_key="not-a-real-key",
    agenda_owner_id="ami-project-office",
    playbook_mcp_url="https://playbook.evaluation.invalid/v1/playbooks/evaluation/mcp",
    playbook_api_key="not-a-real-key",
)


def _record(case: dict[str, Any], role: str = "creates") -> dict[str, Any]:
    case_id = case["id"]
    suffix = "conflict" if role == "contradicts" else "current"
    observed = "2026-10-21T09:00:00Z" if role == "contradicts" else "2026-10-20T09:00:00Z"
    return {
        "id": f"memory-{case_id}-{suffix}",
        "text": case["subject"],
        "ownerId": "ami-project-office",
        "memoryType": "organizational_state",
        "namespace": None,
        "sources": [{"sourceId": f"source-{case_id}-{suffix}"}],
        "attributes": {
            "schema_version": "organizational-state-v2",
            "state_id": f"state-{case_id}",
            "state_kind": case["state_kind"],
            "lifecycle_status": case.get("lifecycle_status", "open"),
            "evidence_role": role,
            "subject": case["subject"],
            "project_id": "project-ami-es2002",
            "accountable_entity_id": case.get("owner", "employee-laura-project-manager"),
            "observed_at": observed,
            "event_sequence": 1,
            "source_offset_ms": 0,
            "due_at": "2026-11-05",
            "requested_decision": case["requested_decision"],
            "impact": case["impact"],
            "supersedes_state_ids": [],
            "source_artifact_id": f"artifact-{case_id}-{suffix}",
            "source_revision": "1",
            "evidence_locator": "paragraph-1",
        },
    }


class EvaluationRAM:
    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.records = [_record(case)]
        if case.get("conflict"):
            self.records.append(_record(case, "contradicts"))
        current = self.records[-1]
        attributes = current["attributes"]
        conflicts = [
            item["id"]
            for item in self.records
            if item["attributes"]["evidence_role"] == "contradicts"
        ]
        self.projections = [
            {
                "id": f"projection-{case['id']}",
                "text": case["subject"],
                "ownerId": "ami-project-office",
                "memoryType": "organizational_state_projection",
                "namespace": None,
                "attributes": {
                    "schema_version": "organizational-state-projection-v1",
                    "state_id": f"state-{case['id']}",
                    "state_kind": case["state_kind"],
                    "lifecycle_status": case.get("lifecycle_status", "open"),
                    "subject": case["subject"],
                    "project_id": "project-ami-es2002",
                    "project_step_id": "",
                    "meeting_id": "",
                    "accountable_entity_id": case.get("owner", "employee-laura-project-manager"),
                    "related_entity_ids": [],
                    "valid_at": attributes["observed_at"],
                    "event_sequence": 1,
                    "source_offset_ms": 0,
                    "due_at": "2026-11-05",
                    "resolved_at": "",
                    "requested_decision": case["requested_decision"],
                    "impact": case["impact"],
                    "conflict_status": "unresolved" if conflicts else "none",
                    "supporting_memory_ids": [item["id"] for item in self.records],
                    "conflicting_memory_ids": conflicts,
                    "observation_count": len(self.records),
                    "current_memory_id": current["id"],
                    "resolution_policy_id": "evaluation-policy-v1",
                },
            }
        ]

    def search(self, request: dict[str, Any], timeout_ms: int | None = None) -> dict[str, Any]:
        return {"items": list(self.projections)}

    def get(self, memory_id: str) -> dict[str, Any]:
        return next(item for item in self.records if item["id"] == memory_id)

    def evidence(
        self,
        memory_id: str,
        source_id: str,
        limit: int = 100,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        passages = (
            [{"text": f"Verified source passage for {self.case['id']}"}]
            if self.case.get("evidence_available", True)
            else []
        )
        return {
            "source": {
                "sourceId": source_id,
                "kind": "document",
                "identity": {"documentId": f"artifact-{self.case['id']}", "revision": "1"},
                "evidence": passages,
            }
        }


class EvaluationPlaybook:
    def __init__(self, contract: dict[str, Any]) -> None:
        self.contract = contract
        self.resources = {
            path: f"Fixed evaluation resource for {path}.\n" for path in REQUIRED_RESOURCES
        }

    def inventory(self) -> list[str]:
        return ["discover_entries", "load_skill", "fetch_resource"]

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "discover_entries":
            return {
                "discoveredEntries": [
                    {
                        "entryKey": "prepare-management-review-agenda",
                        "entryId": self.contract["entry_id"],
                        "version": self.contract["version"],
                        "contentDigest": self.contract["digest"],
                    }
                ]
            }
        if tool == "load_skill":
            return {
                "entryId": self.contract["entry_id"],
                "version": self.contract["version"],
                "contentDigest": self.contract["digest"],
                "content": {
                    "format": "skill",
                    "manifest": {"name": "prepare-management-review-agenda"},
                    "instructions": "Apply only the linked runtime policy resources.",
                    "resources": [
                        {
                            "path": path,
                            "uri": f"playbook://evaluation/{path}",
                            "digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                        }
                        for path, text in self.resources.items()
                    ],
                },
            }
        if tool == "fetch_resource":
            path = arguments["uri"].removeprefix("playbook://evaluation/")
            text = self.resources[path]
            return {
                "uri": arguments["uri"],
                "digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                "text": text,
            }
        raise AssertionError(f"unexpected Playbook tool: {tool}")


def _metric(value: float | int, threshold: float | int, passed: bool) -> dict[str, Any]:
    return {"value": value, "threshold": threshold, "passed": passed}


def evaluate(cases_path: Path = CASES_PATH) -> tuple[dict[str, Any], float]:
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    expected_positive = sum(bool(case["expected_agenda"]) for case in cases)
    predicted = 0
    true_positive = 0
    recalled = 0
    supported = 0
    stale_inclusions = 0
    attestations = 0
    abstentions = 0
    serialized_characters = 0
    case_results: list[dict[str, Any]] = []

    started = time.perf_counter()
    for case in cases:
        service = PluginService(
            CONFIG,
            EvaluationRAM(case),
            EvaluationPlaybook(fixture["playbook"]),
            object(),
        )
        state = service.ram_search_state(project_id="project-ami-es2002", limit=20)
        state_ids = [item["state_id"] for item in state["states"][:20]]
        target_state_id = f"state-{case['id']}"
        retrieved = target_state_id in state_ids
        recalled += int(retrieved)

        agenda = service.agenda_prepare(
            fixture["meeting_date"],
            lookback_days=30,
            max_items=8,
        )
        items = agenda["agenda_items"]
        predicted += len(items)
        expected_title = case["subject"]
        matched = sum(item.get("title") == expected_title for item in items)
        if case["expected_agenda"]:
            true_positive += matched
        elif case["category"] == "stale_conflict":
            stale_inclusions += len(items)
        if case["category"] == "insufficient_evidence" and not items:
            abstentions += 1
        supported += sum(
            set(item) == REQUIRED_ITEM_FIELDS and bool(item.get("evidence_references"))
            for item in items
        )
        attested = (
            agenda["playbook"]["entry_id"] == fixture["playbook"]["entry_id"]
            and agenda["playbook"]["version"] == fixture["playbook"]["version"]
            and agenda["playbook"]["digest"] == fixture["playbook"]["digest"]
        )
        attestations += int(attested)
        serialized_characters += len(json.dumps(agenda, sort_keys=True, separators=(",", ":")))
        case_results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "retrieved_at_20": retrieved,
                "agenda_item_count": len(items),
                "expected_agenda": case["expected_agenda"],
                "playbook_attested": attested,
            }
        )
    elapsed_ms = (time.perf_counter() - started) * 1000

    count = len(cases)
    recall_at_20 = recalled / count
    precision = true_positive / predicted if predicted else 0.0
    agenda_recall = true_positive / expected_positive
    evidence_coverage = supported / predicted if predicted else 0.0
    attestation_rate = attestations / count
    metrics = {
        "ram_recall_at_20": _metric(recall_at_20, 0.85, recall_at_20 >= 0.85),
        "agenda_precision": _metric(precision, 0.80, precision > 0.80),
        "agenda_recall": _metric(agenda_recall, 0.80, agenda_recall > 0.80),
        "evidence_coverage": _metric(evidence_coverage, 1.0, evidence_coverage == 1.0),
        "stale_conflict_inclusions": _metric(stale_inclusions, 0, stale_inclusions == 0),
        "playbook_attestation": _metric(attestation_rate, 1.0, attestation_rate == 1.0),
        "insufficient_evidence_abstentions": _metric(abstentions, 2, abstentions == 2),
    }
    report = {
        "schema_version": 1,
        "case_count": count,
        "category_counts": {
            category: sum(case["category"] == category for case in cases)
            for category in ("normal", "stale_conflict", "insufficient_evidence")
        },
        "metrics": metrics,
        "overall_passed": all(metric["passed"] for metric in metrics.values()),
        "non_gating": {
            "estimated_tokens": (serialized_characters + 3) // 4,
            "wall_clock_latency_ms": None,
            "latency_note": "Measured and printed by each run; excluded from the committed deterministic report.",
        },
        "cases": case_results,
    }
    return report, elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the deterministic metrics to evaluation/results.json",
    )
    arguments = parser.parse_args()
    report, elapsed_ms = evaluate()
    if arguments.write:
        RESULTS_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    displayed = json.loads(json.dumps(report))
    displayed["non_gating"]["wall_clock_latency_ms"] = round(elapsed_ms, 3)
    print(json.dumps(displayed, indent=2))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
