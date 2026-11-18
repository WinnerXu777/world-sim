"""1008 Gate E: window-mode movement. A contract built under ``EDEN_WINDOW`` carries ``static_revision`` (the walls' own stamp) and
``window_revision``; ``AnchorMover`` then keys its "no path" memo on the static stamp with a short TTL (a chunk integration changes
``revision`` every few ticks and used to defeat the memo) and spends at most ``PLAN_EXPANSION_BUDGET`` A* expansions per tick.
Contracts without ``static_revision`` (every non-window run) must behave exactly as before."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from systems.movement import anchor_mover, spatial  # noqa: E402
from systems.movement.anchor_mover import AnchorMover, NO_PATH_TTL_TICKS, PLAN_EXPANSION_BUDGET, WINDOW_NO_PATH_TTL_TICKS  # noqa: E402
from systems.movement.pathing import PathResult  # noqa: E402

R = 2.4
START, GOAL = (10.0, 40.0), (100.0, 40.0)


def room(gap, static="s1", window="w0"):
    """A wall at x 58..62 with a door of ``gap`` units; a window contract (static stamp + window stamp) when ``static`` is given."""
    mid = 40.0
    boxes = [{"id": "b0", "min": [58, 0], "max": [62, mid - gap / 2]}, {"id": "b1", "min": [58, mid + gap / 2], "max": [62, 80]}]
    contract = {"version": 1, "revision": f"{static}/{window}/{gap}", "actor_radius": R, "bounds": [0.0, 0.0, 120.0, 80.0], "boxes": boxes}
    if static is not None:
        contract.update(static_revision=static, window_revision=window)
    return contract


class NoPathMemoTests(unittest.TestCase):
    def test_a_window_revision_change_does_not_defeat_the_memo(self):
        mover = AnchorMover()
        for tick in range(WINDOW_NO_PATH_TTL_TICKS):
            result = mover.step("npc", START, GOAL, room(2.0, window=f"w{tick}"), tick=tick)    # a new integration every tick
            self.assertEqual(result.blocked, "no_path")
        self.assertEqual(mover.plan_calls, 1)
        mover.step("npc", START, GOAL, room(2.0, window="late"), tick=WINDOW_NO_PATH_TTL_TICKS)
        self.assertEqual(mover.plan_calls, 2)                                                    # expired: asked again

    def test_a_change_of_the_static_walls_drops_the_memo_at_once(self):
        mover = AnchorMover()
        mover.step("npc", START, GOAL, room(2.0, static="s1"), tick=0)
        self.assertEqual(mover.step("npc", START, GOAL, room(10.0, static="s2"), tick=1).blocked, "")
        self.assertEqual(mover.plan_calls, 2)

    def test_a_goal_that_an_integration_makes_reachable_is_reached_within_the_ttl(self):
        mover = AnchorMover()
        position, first_free, arrived_at = START, None, None
        for tick in range(WINDOW_NO_PATH_TTL_TICKS + 200):
            contract = room(2.0 if tick < 5 else 10.0, window="w0" if tick < 5 else "w1")        # the door opens at tick 5, static walls unchanged
            result = mover.step("npc", position, GOAL, contract, tick=tick)
            position = result.position
            if first_free is None and not result.blocked:
                first_free = tick
            if result.arrived:
                arrived_at = tick
                break
        self.assertIsNotNone(first_free)
        self.assertLessEqual(first_free, 5 + WINDOW_NO_PATH_TTL_TICKS)                          # max staleness: the TTL
        self.assertIsNotNone(arrived_at)

    def test_without_a_static_revision_nothing_changed(self):
        sealed = room(2.0, static=None)
        mover = AnchorMover()
        mover.step("npc", START, GOAL, sealed, tick=0)
        for tick in range(1, 30):
            self.assertEqual(mover.step("npc", START, GOAL, sealed, tick=tick).blocked, "no_path")
        self.assertEqual(mover.plan_calls, 1)
        changed = room(2.0, static=None)
        changed["revision"] = "other"
        mover.step("npc", START, GOAL, changed, tick=30)
        self.assertEqual(mover.plan_calls, 2)                                                    # any revision change re-asks, as before
        mover.step("npc", START, GOAL, changed, tick=30 + NO_PATH_TTL_TICKS)
        self.assertEqual(mover.plan_calls, 3)                                                    # and the TTL is the old 100


class ExpansionBudgetTests(unittest.TestCase):
    @staticmethod
    def hungry_planner(calls):
        def plan(start, goal, contract):
            calls.append((start, goal))
            return PathResult(None, "no_path", expansions=PLAN_EXPANSION_BUDGET // 3, spent=PLAN_EXPANSION_BUDGET)
        return plan

    def test_plans_over_the_budget_wait_for_the_next_tick(self):
        calls = []
        mover = AnchorMover(planner=self.hungry_planner(calls))
        contract = room(2.0)
        results = [mover.step(k, START, GOAL, contract, tick=7) for k in ("a", "b", "c")]
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0].blocked, "no_path")
        for deferred in results[1:]:
            self.assertEqual((deferred.blocked, deferred.position, deferred.moved, deferred.replanned, deferred.arrived), ("", START, 0.0, False, False))
        self.assertEqual(mover.deferred, 2)
        self.assertEqual(mover.step("a", START, GOAL, contract, tick=8).blocked, "no_path")     # memo, no new call
        self.assertEqual(mover.step("b", START, GOAL, contract, tick=8).blocked, "no_path")     # b's turn: it plans now
        self.assertEqual(mover.step("c", START, GOAL, contract, tick=8).blocked, "")            # c waits another tick
        self.assertEqual(mover.step("c", START, GOAL, contract, tick=9).blocked, "no_path")
        self.assertEqual(len(calls), 3)

    def test_the_budget_counts_work_not_time(self):
        calls = []
        cheap = lambda start, goal, contract: (calls.append(1), PathResult([goal], expansions=40, spent=40))[1]       # noqa: E731
        mover = AnchorMover(planner=cheap)
        for key in range(30):
            self.assertFalse(mover.step(key, START, (START[0], START[1] + 5.0 + key), room(10.0), tick=3).blocked)
        self.assertEqual((len(calls), mover.deferred), (30, 0))                                  # 30 x 40 expansions stay under the budget

    def test_outside_window_mode_every_plan_runs_in_its_tick(self):
        calls = []
        mover = AnchorMover(planner=self.hungry_planner(calls))
        for key in ("a", "b", "c"):
            self.assertEqual(mover.step(key, START, GOAL, room(2.0, static=None), tick=7).blocked, "no_path")
        self.assertEqual((len(calls), mover.deferred), (3, 0))

    def test_two_identical_runs_agree(self):
        def run():
            calls = []
            mover = AnchorMover(planner=self.hungry_planner(calls))
            trail = []
            for tick in range(6):
                for key in "abcd":
                    r = mover.step(key, START, GOAL, room(2.0, window=f"w{tick}"), tick=tick)
                    trail.append((tick, key, r.blocked, r.position))
            return trail, len(calls), mover.deferred
        self.assertEqual(run(), run())


class PathResultTests(unittest.TestCase):
    def test_plan_path_reports_the_work_of_every_attempt(self):
        from systems.movement.pathing import plan_path
        result = plan_path(START, GOAL, room(2.0, static=None))
        self.assertEqual(result.reason, "no_path")
        self.assertGreater(result.spent, result.expansions)                                       # three attempts, the last is not all of it
        self.assertEqual(plan_path(START, GOAL, room(10.0, static=None)).waypoints is not None, True)


class WorldContractKeysTests(unittest.TestCase):
    def engine(self, window):
        m = torch.zeros((8, 40))
        return mock.Mock(state=mock.Mock(m_tensor=m), _entity_uid_by_slot=[""] * 8, _map_name=None, world_epoch=1, _window_contract=window)

    def contract(self, window, on=True):
        with mock.patch("harness.numerics.window_enabled", return_value=on):
            return spatial.world_contract(self.engine(window))

    def test_window_keys_appear_only_with_a_window_part(self):
        off = self.contract(None)
        self.assertNotIn("static_revision", off)
        self.assertNotIn("window_revision", off)
        window = {"boxes": [], "bounds": None, "revision": "abc"}
        on = self.contract(window)
        self.assertEqual(on["window_revision"], "abc")
        self.assertEqual(len(on["static_revision"]), 16)
        self.assertEqual(set(on) - set(off), {"static_revision", "window_revision"})
        self.assertNotIn("static_revision", self.contract(window, on=False))                      # flag off: the window part is ignored

    def test_the_window_revision_moves_the_revision_but_not_the_static_stamp(self):
        a = self.contract({"boxes": [], "bounds": None, "revision": "one"})
        b = self.contract({"boxes": [], "bounds": None, "revision": "two"})
        self.assertEqual(a["static_revision"], b["static_revision"])
        self.assertNotEqual(a["revision"], b["revision"])
        self.assertEqual(a["revision"], self.contract({"boxes": [], "bounds": None, "revision": "one"})["revision"])

    def test_a_wall_in_the_tensor_moves_the_static_stamp(self):
        window = {"boxes": [], "bounds": None, "revision": "one"}
        before = self.contract(window)
        engine = self.engine(window)
        m = engine.state.m_tensor
        m[0, cfg.M_TYPE], m[0, cfg.M_HP], m[0, cfg.CX], m[0, cfg.CY], m[0, cfg.SCALE] = float(cfg.M_WALL), 10.0, 30.0, 30.0, 3.0
        engine._entity_uid_by_slot = ["w0"] + [""] * 7
        with mock.patch("harness.numerics.window_enabled", return_value=True):
            after = spatial.world_contract(engine)
        self.assertNotEqual(before["static_revision"], after["static_revision"])
        self.assertEqual(len(after["boxes"]), 1)


if __name__ == "__main__":
    unittest.main()
