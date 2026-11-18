"""Golden-trace characterization (WS-H P0): the seeded headless world must not drift.

The reference lives in tests/golden/trace_seed<N>.json and is produced by ``tools/golden_trace.py --record``. A change
that alters simulation outcomes fails here; if the change is intended, re-record in the same commit and explain the diff.
The run happens in a subprocess because the legacy backend is a process-wide singleton with global RNGs.
"""
import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import golden_trace  # noqa: E402


class GoldenTraceFileTests(unittest.TestCase):
    def setUp(self):
        self.golden = json.loads(golden_trace.golden_path(golden_trace.DEFAULT_SEED).read_text(encoding="utf-8"))

    def test_golden_file_is_well_formed(self):
        self.assertEqual(self.golden["schema"], golden_trace.SCHEMA)
        ticks = [c["tick"] for c in self.golden["checkpoints"]]
        self.assertEqual(ticks, sorted(set(ticks)))
        self.assertEqual(ticks[0], 0)
        self.assertEqual(ticks[-1], self.golden["ticks"])
        for checkpoint in self.golden["checkpoints"]:
            self.assertEqual(len(checkpoint["h_sha256"]), 64)
            self.assertGreater(checkpoint["humans"], 0)

    def test_compare_accepts_identical_and_float_noise(self):
        self.assertEqual(golden_trace.compare(self.golden, copy.deepcopy(self.golden), strict=True), [])
        noisy = copy.deepcopy(self.golden)
        name = next(iter(noisy["checkpoints"][-1]["residents"]))
        noisy["checkpoints"][-1]["residents"][name]["x"] += golden_trace.TOLERANCE / 10
        self.assertEqual(golden_trace.compare(self.golden, noisy), [])

    def test_compare_detects_drift(self):
        moved = copy.deepcopy(self.golden)
        name = next(iter(moved["checkpoints"][-1]["residents"]))
        moved["checkpoints"][-1]["residents"][name]["x"] += 1.0
        self.assertTrue(any("x:" in p for p in golden_trace.compare(self.golden, moved)))
        goal = copy.deepcopy(self.golden)
        goal["checkpoints"][-1]["residents"][name]["goal"] = "not_a_goal"
        self.assertTrue(golden_trace.compare(self.golden, goal))
        rehashed = copy.deepcopy(self.golden)
        rehashed["checkpoints"][3]["m_sha256"] = "0" * 64
        self.assertEqual(golden_trace.compare(self.golden, rehashed), [])  # summaries still equal: tolerant mode passes
        self.assertTrue(golden_trace.compare(self.golden, rehashed, strict=True))  # strict mode fails on the exact hash


class GoldenTraceRunTests(unittest.TestCase):
    def test_fresh_seeded_run_matches_the_golden(self):
        command = [sys.executable, str(ROOT / "tools" / "golden_trace.py"), "--check"]
        if os.environ.get("EDEN_GOLDEN_STRICT") == "1":
            command.append("--strict")
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, "golden trace drifted:\n" + "\n".join(
            line for line in done.stdout.splitlines() if not line.startswith(("[MemoryLightRAG]", "[Genesis]")))[-3000:] + done.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
