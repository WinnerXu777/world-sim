"""Published examples stay valid and in sync; a short Gate A run (real headless engine in a subprocess, mock server in another process,
faults injected, server killed mid-run). The full 30-game-minute run is `python -m model_server.gate_a --compare --ticks 36000`."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from model_server import contract as c
from model_server import examples
from model_server import gate_a


class ExamplesTests(unittest.TestCase):
    def test_committed_examples_match_what_the_mock_produces(self):
        built = examples.build()
        self.assertEqual(sorted(built), sorted(p.stem for p in examples.HERE.glob("*.json")))
        for name, pair in built.items():
            on_disk = (examples.HERE / f"{name}.json").read_bytes().decode("utf-8").replace("\r\n", "\n")
            self.assertEqual(on_disk, examples.render(pair), f"{name}: regenerate with python -m model_server.examples --write")

    def test_every_example_pair_validates_against_the_contract(self):
        for name, pair in examples.build().items():
            with self.subTest(name=name):
                request = c.parse_envelope(pair["request"])
                self.assertEqual(c.parse_response(pair["response"], request).provider_mode, "mock")

    def test_every_role_and_mode_has_an_example(self):
        seen = {(role, req["payload"].get("mode")) for role, req in examples.EXAMPLES.values()}
        self.assertIn(("decide", None), seen)
        for role, mode in (("resident", "urgent_react"), ("resident", "resident_reasoning"), ("dialogue", "talk_reply"), ("world", "decree")):
            self.assertIn((role, mode), seen)


class GateAShortRunTests(unittest.TestCase):
    def run_gate(self, models, ticks=500):
        out = ROOT / ".runtime" / f"test-gate-a-{models}.json"
        out.parent.mkdir(exist_ok=True)
        proc = subprocess.run([sys.executable, "-m", "model_server.gate_a", "--ticks", str(ticks), "--models", models, "--speed", "3",
                               "--json", str(out)], cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True,
                              text=True, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads(out.read_text(encoding="utf-8"))

    def test_models_off_makes_zero_network_calls_with_the_real_engine(self):
        result = self.run_gate("off")
        failed = [(n, d) for n, ok, d in gate_a.verdict(result) if not ok]
        self.assertEqual(failed, [])
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["model_routes"], ["/control/models", "/model_status"])   # the map_test hook is in place
        self.assertTrue(result["map_test_plane_present"])

    def test_faults_end_as_fallbacks_and_nothing_reaches_the_tick(self):
        result = self.run_gate("on", ticks=900)
        self.assertEqual(result["errors"], [])
        self.assertGreater(result["network_calls"], 0)
        hits = result["server_fault_hits"] or {}
        self.assertGreaterEqual(len([k for k, v in hits.items() if v]), 3, hits)
        self.assertGreater(result["decision_modes"].get("fallback", 0), 0)
        self.assertGreater(result["followup_modes"].get("mock", 0), 0)
        self.assertGreater(result["traffic"]["stale_applied_refused"], 0)


if __name__ == "__main__":
    unittest.main()
