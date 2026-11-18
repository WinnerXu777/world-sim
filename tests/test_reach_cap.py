"""EDEN_REACH_MAX_DISTANCE: the verb-side cap on the path-search request (default off: nothing changes)."""
import sys
import os
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_affordance_unit import box, contract, make  # noqa: E402
from systems.affordance import StaticServices  # noqa: E402


class Cap(unittest.TestCase):
    def walled(self, *boxes):
        return make(services=StaticServices(contract=contract(*boxes)), humans={"h_a": (50, 50), "h_b": (140, 50)})

    def ask(self, env):
        with unittest.mock.patch.dict(os.environ, env):
            if not env:
                os.environ.pop("EDEN_REACH_MAX_DISTANCE", None)
            world, services, engine = self.walled(box("w", 93, 0, 97, 80))
            verdict = engine.legal("h_a", "chat", {"target": "h_b"})
            return verdict, engine.reach.stats

    def test_unset_or_zero_is_todays_search(self):
        for env in ({}, {"EDEN_REACH_MAX_DISTANCE": "0"}, {"EDEN_REACH_MAX_DISTANCE": "junk"}):
            verdict, stats = self.ask(env)
            self.assertTrue(verdict.ok, env)
            self.assertEqual((verdict.reachability, stats["path_searches"], stats["too_far"]), ("exact", 1, 0), env)

    def test_a_far_goal_is_not_searched_and_is_marked_approx(self):
        verdict, stats = self.ask({"EDEN_REACH_MAX_DISTANCE": "50"})
        self.assertEqual((verdict.ok, verdict.reason, verdict.reachability), (False, "unreachable", "approx"))
        self.assertEqual((stats["path_searches"], stats["too_far"]), (0, 1))

    def test_a_goal_inside_the_cap_is_searched_as_before(self):
        verdict, stats = self.ask({"EDEN_REACH_MAX_DISTANCE": "200"})
        self.assertEqual((verdict.ok, verdict.reachability, stats["path_searches"]), (True, "exact", 1))

    def test_a_clear_straight_line_is_never_capped(self):
        with unittest.mock.patch.dict(os.environ, {"EDEN_REACH_MAX_DISTANCE": "10"}):
            world, services, engine = self.walled()
            verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertTrue(verdict.ok)
        self.assertEqual(engine.reach.stats["too_far"], 0)


if __name__ == "__main__":
    unittest.main()
