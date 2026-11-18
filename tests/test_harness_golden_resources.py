"""G-005: the flag-on golden (EDEN_MAP_RESOURCES=1, tests/golden/trace_seed1008_resources.json) differs from the default golden only in the
documented ways, and a fresh flag-on run reproduces it. Record with ``tools/golden_trace.py --resources --record``."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import golden_trace  # noqa: E402

# starter_village with the flag on: village:well becomes a well (type 23), four piles/patches become resource nodes (type 27); the five
# rows were inert M_MAP_OBJECT rows (type 26) with the flag off
TYPE_DELTA = {"23": 1, "26": -5, "27": 4}
UNCHANGED_RESIDENT_FIELDS = ("slot", "hp", "hunger", "thirst", "stamina", "mood", "goal", "at_anchor")


def load(resources):
    return json.loads(golden_trace.golden_path(golden_trace.DEFAULT_SEED, resources).read_text(encoding="utf-8"))


class ResourceGoldenTests(unittest.TestCase):
    def setUp(self):
        self.base, self.on = load(False), load(True)

    def test_same_run_shape(self):
        for key in ("schema", "seed", "ticks"):
            self.assertEqual(self.base[key], self.on[key], key)
        self.assertEqual([c["tick"] for c in self.base["checkpoints"]], [c["tick"] for c in self.on["checkpoints"]])

    def test_entity_count_and_types_differ_only_by_the_five_converted_rows(self):
        for a, b in zip(self.base["checkpoints"], self.on["checkpoints"]):
            self.assertEqual(a["entities"], b["entities"], a["tick"])
            delta = {t: b["entity_types"].get(t, 0) - a["entity_types"].get(t, 0) for t in set(a["entity_types"]) | set(b["entity_types"])}
            self.assertEqual({t: d for t, d in delta.items() if d}, TYPE_DELTA, a["tick"])

    def test_residents_needs_goals_and_anchors_are_identical_only_positions_move(self):
        moved = 0
        for a, b in zip(self.base["checkpoints"], self.on["checkpoints"]):
            self.assertEqual(a["humans"], b["humans"], a["tick"])
            self.assertEqual(sorted(a["residents"]), sorted(b["residents"]), a["tick"])
            for name, ra in a["residents"].items():
                rb = b["residents"][name]
                for field in UNCHANGED_RESIDENT_FIELDS:
                    self.assertEqual(ra[field], rb[field], f"tick {a['tick']} {name}.{field}")
                moved += (ra["x"], ra["y"]) != (rb["x"], rb["y"])
        self.assertGreater(moved, 0)                  # the known tick-600 position drift is real (see 1008_map_resources_design.md)

    def test_sums_differ_only_in_food_and_water(self):
        first = self.on["checkpoints"][0]["m_sums"]
        self.assertGreater(first["food"], self.base["checkpoints"][0]["m_sums"]["food"])
        self.assertGreater(first["water"], self.base["checkpoints"][0]["m_sums"]["water"])
        for a, b in zip(self.base["checkpoints"], self.on["checkpoints"]):
            for key in ("cx", "cy", "hp"):
                self.assertEqual(a["m_sums"][key], b["m_sums"][key], f"tick {a['tick']} {key}")


class ResourceGoldenRunTests(unittest.TestCase):
    def test_fresh_flag_on_run_matches_its_golden(self):
        command = [sys.executable, str(ROOT / "tools" / "golden_trace.py"), "--resources", "--check"]
        if os.environ.get("EDEN_GOLDEN_STRICT") == "1":
            command.append("--strict")
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, "flag-on golden trace drifted:\n" + "\n".join(
            line for line in done.stdout.splitlines() if not line.startswith(("[MemoryLightRAG]", "[Genesis]")))[-3000:] + done.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
