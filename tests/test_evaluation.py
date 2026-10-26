from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "evaluation" / "run.py"
SPEC = importlib.util.spec_from_file_location("plugin_evaluation", RUNNER)
assert SPEC and SPEC.loader
EVALUATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATION)


class EvaluationTests(unittest.TestCase):
    def test_fixed_quality_gate_passes_and_matches_committed_report(self):
        report, elapsed_ms = EVALUATION.evaluate()
        committed = json.loads((ROOT / "evaluation" / "results.json").read_text())
        self.assertEqual(report, committed)
        self.assertTrue(report["overall_passed"])
        self.assertGreaterEqual(elapsed_ms, 0)
        self.assertEqual(report["case_count"], 15)
        self.assertEqual(
            report["category_counts"],
            {"normal": 10, "stale_conflict": 3, "insufficient_evidence": 2},
        )
        self.assertTrue(all(metric["passed"] for metric in report["metrics"].values()))

    def test_report_is_deterministic_across_runs(self):
        first, _ = EVALUATION.evaluate()
        second, _ = EVALUATION.evaluate()
        self.assertEqual(first, second)
        self.assertIsNone(first["non_gating"]["wall_clock_latency_ms"])


if __name__ == "__main__":
    unittest.main()
