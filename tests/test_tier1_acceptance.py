"""Smoke test of ``model_server/tier1_acceptance.py``: a short run in a fresh process (the module boots its own headless engine, so it cannot run inside
a process that already imported ``map_test``). The one-game-day run with its pass criteria is a manual script (see 1008_agent_driver_design.md)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceSmoke(unittest.TestCase):
    def run_tier1(self, kind):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{kind}.json"
            env = {**os.environ, "EDEN_ROSTER_DRIVER": "anchor"}
            done = subprocess.run([sys.executable, "-m", "model_server.tier1_acceptance", "--tier1", kind, "--ticks", "150", "--json", str(out)],
                                  cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300)
            self.assertTrue(out.exists(), done.stderr[-2000:])
            return json.loads(out.read_text(encoding="utf-8"))

    def test_a_short_run_reports_every_figure_and_the_two_providers_agree(self):
        rules, matrix = self.run_tier1("rules"), self.run_tier1("matrix")
        for result in (rules, matrix):
            self.assertEqual(result["ticks"], 150)
            for key in ("commission", "needs", "idle", "failures", "budget", "verdict"):
                self.assertIn(key, result)
            self.assertEqual(result["failures"]["tier1_errors"], 0)
            self.assertEqual(result["idle"]["longest_run"], 0)
            self.assertGreater(result["budget"]["decisions"], 0)
            self.assertEqual(result["driver_status"]["prior"], 100.0)
        self.assertEqual(rules["final_positions"], matrix["final_positions"])             # prior 100: the matrix reproduces the rules
        self.assertEqual(rules["budget"]["decisions"], matrix["budget"]["decisions"])
        self.assertGreater(matrix["budget"]["warm_ms"], 0.0)                               # only the matrix has something to warm


if __name__ == "__main__":
    unittest.main()
