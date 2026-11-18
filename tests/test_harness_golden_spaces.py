"""1008 P3: the spaces golden (EDEN_SPACES=1 with EDEN_PERCEPTION_BOUNDED=1, tests/golden/trace_seed1008_spaces.json) differs from the default
golden in exactly two fields at every checkpoint, ``h_sha256`` and ``m_sha256`` (the new H_SPACE / M_SPACE columns hold the smith's
and the interiors' space ids), and a fresh run reproduces it. Record with ``tools/golden_trace.py --spaces --record``.

Measured when recorded (extract of 3febf2e): bounded perception alone (EDEN_PERCEPTION_BOUNDED=1) reproduces the default golden
including both hashes; with the two space columns zeroed the spaces run's hashes equal the default golden's at ticks 0, 1, 20, 100, 300, 600."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import golden_trace  # noqa: E402


def load(spaces):
    return json.loads(golden_trace.golden_path(golden_trace.DEFAULT_SEED, False, spaces).read_text(encoding="utf-8"))


class SpacesGoldenTests(unittest.TestCase):
    def setUp(self):
        self.base, self.on = load(False), load(True)

    def test_same_run_shape(self):
        for key in ("schema", "seed", "ticks"):
            self.assertEqual(self.base[key], self.on[key], key)
        self.assertEqual([c["tick"] for c in self.base["checkpoints"]], [c["tick"] for c in self.on["checkpoints"]])

    def test_every_field_is_identical_except_the_two_tensor_hashes(self):
        for a, b in zip(self.base["checkpoints"], self.on["checkpoints"]):
            self.assertEqual({k for k in a if a[k] != b[k]}, {"h_sha256", "m_sha256"}, a["tick"])

    def test_the_golden_compares_equal_to_the_default_under_the_tolerant_comparison(self):
        self.assertEqual(golden_trace.compare(self.base, self.on, strict=False), [])


class SpacesGoldenRunTests(unittest.TestCase):
    def test_fresh_spaces_run_matches_its_golden(self):
        command = [sys.executable, str(ROOT / "tools" / "golden_trace.py"), "--spaces", "--check"]
        if os.environ.get("EDEN_GOLDEN_STRICT") == "1":
            command.append("--strict")
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, "spaces golden trace drifted:\n" + "\n".join(
            line for line in done.stdout.splitlines() if not line.startswith(("[MemoryLightRAG]", "[Genesis]")))[-3000:] + done.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
