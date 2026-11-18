"""1008 WS-D P5 proof 1-3: the window walk. A scripted resident walks east 5000 units, south 1500 and back west 1500 over seed 1008 (inline generation,
``workers=0``, so a chunk is ready the tick it is asked for). Checkpoints every 100 ticks are compared with ``tests/golden/trace_window_walk.json``
(regenerate: ``WINDOW_WALK_WRITE=1 python -m unittest test_harness_window_walk``), and the same walk started with another window origin must give the same
discrete state and the same absolute entities (origin invariance); a save taken mid-walk and restored continues identically."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
from test_harness_window_saves import SaveFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import window_trace  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402
import map_geo  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "trace_window_walk.json"
STEP = 4.0                                                 # units per tick
ROUTE = (("east", 5000.0), ("south", 1500.0), ("west", 1500.0))
START = (520.0, 520.0)                                    # absolute, inside chunk (2, 2)
EVERY = 100


def route_ticks():
    return [(name, int(length / STEP)) for name, length in ROUTE]


class WalkMixin:
    def start_walk(self, origin):
        """Place the walker at ``START`` (absolute) under a window whose origin is ``origin``."""
        if tuple(origin) != (0, 0):
            self.manager.frame.origin = tuple(origin)
            self.manager._publish()
        ox, oy = self.manager.frame.origin
        self.place_human(0, START[0] - ox * 256.0, START[1] - oy * 256.0)
        self.void_hits = 0
        self.points = []

    def step_walk(self):
        h = self.engine.state.h_tensor
        self.engine.tick += 1
        self.manager.tick()
        if window_trace.inside_void(self.manager, float(h[0, cfg.X]), float(h[0, cfg.Y])):
            self.void_hits += 1

    def walk(self, segments, record):
        h = self.engine.state.h_tensor
        for name, ticks in segments:
            dx, dy = {"east": (STEP, 0.0), "south": (0.0, STEP), "west": (-STEP, 0.0)}[name]
            for _ in range(ticks):
                h[0, cfg.X] += dx
                h[0, cfg.Y] += dy
                self.step_walk()
                if self.engine.tick % EVERY == 0:
                    record.append(window_trace.checkpoint(self.manager, self.engine.tick, self.void_hits))


class WalkTests(WalkMixin, WindowFixture):
    def run_walk(self, origin):
        self.start_walk(origin)
        record = []
        self.walk(route_ticks(), record)
        return record

    async def test_the_walk_matches_the_golden_trace(self):
        record = self.run_walk((0, 0))
        self.assertEqual(len(record), 20)
        self.assertGreater(record[-1]["epoch"], 0, "the walk crosses several re-bases")
        self.assertEqual(max(c["void_hits"] for c in record), 0, "the walker never stands in a void box")
        self.assertLessEqual(max(c["rows"] for c in record), 800)
        if os.environ.get("WINDOW_WALK_WRITE") == "1":
            GOLDEN.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(record, golden)

    async def test_the_same_walk_twice_is_identical(self):
        first = self.run_walk((0, 0))
        self.tearDownWalk()
        self.assertEqual(self.run_walk((0, 0)), first)

    async def test_origin_invariance(self):
        a = self.run_walk((0, 0))
        self.tearDownWalk()
        b = self.run_walk((1, -1))
        self.assertEqual(len(a), len(b))
        for left, right in zip(a, b):
            for key in window_trace.DISCRETE:
                self.assertEqual(left[key], right[key], (left["tick"], key))

    def tearDownWalk(self):
        """Back to an empty world for a second run in the same test (same engine, same service)."""
        self.manager.close = lambda: None
        self.engine.reset_world()
        map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
        from harness import window_manager
        self.manager = window_manager.WindowManager(self.engine, self.service)


class SaveMidWalkTests(WalkMixin, SaveFixture):
    async def test_a_save_taken_mid_walk_continues_identically(self):
        self.start_walk((0, 0))
        record = []
        total = route_ticks()
        self.walk([total[0]], record)                                 # east: several re-bases
        saved = self.payload()
        rest = [total[1], total[2]]
        tail_a = []
        self.walk(rest, tail_a)
        self.restore(codec.loads(codec.dumps(saved)))
        self.manager = self.engine._window
        self.engine.tick = int(saved["engine"]["tick"])
        self.void_hits = 0
        tail_b = []
        self.walk(rest, tail_b)
        for left, right in zip(tail_a, tail_b):
            for key in window_trace.DISCRETE:
                if key == "void_hits":
                    continue
                self.assertEqual(left[key], right[key], (left["tick"], key))
            self.assertEqual((left["origin"], left["epoch"]), (right["origin"], right["epoch"]))
        self.assertEqual(len(tail_a), len(tail_b))


if __name__ == "__main__":
    unittest.main()
