"""Agent-mode twin of ``tests/test_actions_roster.py`` (D-008): the same 8 residents of the real Stage 1 engine, every one bound to ``driver == "agent"``.
The roster originals record what an *anchor-driven* resident can do; here the world alone judges legality (no ``roster_driven`` demotion), the
walking verbs queue tasks the task system carries out (the agent driver yields while a task is queued or active), and eat / drink at a site start the
needs loop's own trip (``site_trip``). Measured behaviour, same method as the originals; the originals are unchanged."""
from authored_village import load_village_maps
import random
import unittest

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_actions_roster import RosterCase
import genesis_config as cfg
from harness.adapter import EngineWorld
from systems.actions import ActionRunner, EngineRecordOps
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.affordance import EngineServices
from systems.roster.driver import runtime


class AgentRosterCase(RosterCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for human_id in self.keys.values():
            self.record(human_id)["roster"]["driver"] = "agent"
        self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        self.runner = ActionRunner(self.world, self.services, record_ops=EngineRecordOps(self.engine))     # default affordance engine: judged per resident


class SameAsRosterOnAgentResidents(AgentRosterCase):
    def test_eat_from_the_pack_is_immediate(self):
        u = self.keys["iven"]
        self.h[self.slot(u), cfg.HUNGER] = 80.0
        r = self.runner.run(u, "eat", {})
        self.assertTrue(r.ok, r.code)
        self.assertAlmostEqual(self.col(u, cfg.HUNGER), 60.0, places=3)

    def test_sleep_uses_the_routine_route_and_the_agent_driver_walks_home(self):
        u = self.keys["gatherer"]
        a = self.anchor(u, "work")
        self.put(u, *self.stand_near(a.x, a.y))
        before = self.dist_to(u, "sleep")
        r = self.runner.run(u, "sleep", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((r.ops[0]["kind"], r.ops[0]["routine"]), ("set_routine", "sleep"))
        self.assertEqual(self.routine(u)["source"], "action")
        self.step(100)
        self.assertLess(self.dist_to(u, "sleep"), before * 0.6)             # walked by the agent driver (Tier 1 reads the routine the action set), no task
        self.assertEqual(self.tasks(u), [])
        self.step(250)
        self.assertNotEqual(self.routine(u).get("source"), "action")         # the schedule refreshed its own routine

    def test_go_to_work_uses_the_routine_route(self):
        u = self.keys["builder"]
        s = self.anchor(u, "sleep")
        self.put(u, s.x, s.y)
        self.assertGreater(self.dist_to(u, "work"), 30)
        r = self.runner.run(u, "go_to_work", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((r.ops[0]["kind"], r.ops[0]["routine"]), ("set_routine", "work_site"))
        self.assertEqual(self.routine(u)["kind"], "work_site")
        self.step(100)
        self.assertLess(self.dist_to(u, "work"), 5.0)
        self.assertEqual(self.tasks(u), [])

    def test_flee_to_and_seek_shelter_use_the_return_home_routine(self):
        for verb, key in (("flee_to", "builder"), ("seek_shelter", "gatherer")):
            u = self.keys[key]
            a = self.anchor(u, "work")
            self.put(u, a.x, a.y)
            self.h[self.slot(u), cfg.THREAT] = 80.0
            before = self.dist_to(u, "sleep")
            r = self.runner.run(u, verb, {})
            self.assertTrue(r.ok, (verb, r.code, r.detail))
            self.assertEqual(self.routine(u)["kind"], "return_home", verb)
            self.step(80)
            self.assertLess(self.dist_to(u, "sleep"), before - 15, verb)

    def test_craft_store_fetch_and_give_work_as_for_an_anchor_resident(self):
        smith = self.keys["smith"]
        forge = [e for e in self.services.entities() if e.kind == "forge"][0]
        self.put(smith, *self.stand_near(forge.x, forge.y))
        r = self.runner.run(smith, "craft", {"recipe": "sword"})
        self.assertTrue(r.ok, (r.code, r.detail))
        giver, taker = self.keys["rhea"], self.keys["nessa"]
        x, y = self.stand_near(100.0, 150.0)
        self.put(giver, x, y)
        self.put(taker, *self.stand_near(x + 6, y))
        r = self.runner.run(giver, "give_item", {"target": taker, "item": "rations", "qty": 1})
        self.assertTrue(r.ok, (r.code, r.detail))


class NoLongerDemotedOnAgentResidents(AgentRosterCase):
    def test_eat_and_drink_at_a_site_start_the_needs_trip(self):
        smith, iven = self.keys["smith"], self.keys["iven"]
        state = runtime(self.engine)
        self.h[self.slot(smith), cfg.HUNGER] = 60.0
        self.h[self.slot(iven), cfg.THIRST] = 60.0
        eat = self.runner.run(smith, "eat", {"place": "village:use_campfire"})
        drink = self.runner.run(iven, "drink", {"place": "village:use_well"})
        self.assertTrue(eat.ok, (eat.code, eat.detail))
        self.assertTrue(drink.ok, (drink.code, drink.detail))
        self.assertEqual((eat.ops[0]["kind"], drink.ops[0]["kind"]), ("site_trip", "site_trip"))
        self.assertEqual(self.tasks(smith) + self.tasks(iven), [])                           # no task: the needs loop's trip, not a legacy task
        self.step(360)
        self.assertLess(self.col(smith, cfg.HUNGER), 10.0)
        self.assertLess(self.col(iven, cfg.THIRST), 10.0)
        self.assertGreaterEqual(state.trips_done, 2)

    def test_work_gather_and_follow_are_judged_by_the_world_not_refused_as_roster_driven(self):
        builder, gatherer = self.keys["builder"], self.keys["gatherer"]
        a = self.anchor(builder, "work")
        self.put(builder, a.x, a.y)
        node = [e for e in self.services.entities() if e.id == "village:wood_pile"][0]
        self.put(gatherer, *self.stand_near(node.x, node.y))
        x, y = self.stand_near(156.0, 150.0)
        self.put(builder, x, y)
        self.put(gatherer, *self.stand_near(x + 40, y))
        codes = (self.runner.run(builder, "work_shift", {}).code, self.runner.run(gatherer, "gather_resource", {"source": node.id}).code,
                 self.runner.run(builder, "follow", {"target": gatherer}).code)
        for code in codes:
            self.assertNotEqual(code, "illegal:roster_driven")
            self.assertNotEqual(code, "refused:roster_driven")

    def test_greet_and_chat_queue_the_talk_task_for_an_agent_resident(self):
        a_, b_ = self.keys["elsa"], self.keys["orrin"]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        self.put(b_, *self.stand_near(x + 8, y))
        r = self.runner.run(a_, "greet", {"target": b_})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertAlmostEqual(self.record(a_)["relationships"][b_]["closeness"], 0.02)
        self.assertEqual([k for k, _ in self.tasks(a_)], ["talk_to_target"])                   # an anchor-driven resident gets event + closeness only; here the task is queued
        driver = self.engine.__dict__["_agent_driver"]
        yielded = driver.yielded
        self.step(3)
        self.assertGreater(driver.yielded, yielded, "the agent driver must yield while the task owns the resident's movement")


class BatchOneOnAgentResidents(AgentRosterCase):
    def test_attack_avoid_and_explore_are_not_roster_driven_refusals(self):
        a_, b_ = self.keys["elsa"], self.keys["orrin"]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        self.put(b_, *self.stand_near(x + 8, y))
        for verb, args in (("attack", {"target": b_}), ("avoid", {"target": b_}), ("explore_toward", {"heading": "N"})):
            r = self.runner.run(a_, verb, args, proposer="rules")
            self.assertNotIn("roster_driven", r.code, (verb, r.code))

    def test_explore_toward_walks_an_agent_resident_to_its_point(self):
        """The anchor twin pins ``move_to_place`` as inert. For an agent resident the driver yields and the task system walks it to the point
        (``_handle_move_to_place`` honours an explicit ``target_place`` x/y, 1008_actions.md 10.11), then the task completes and the driver takes over."""
        a_ = self.keys["elsa"]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        verdict = self.runner.aff.legal(a_, "explore_toward", {"heading": "N"})
        self.assertTrue(verdict.ok, verdict.reason)
        gx, gy = verdict.detail["to"]
        r = self.runner.run(a_, "explore_toward", {"heading": "N"})
        self.assertTrue(r.ok, (r.code, r.detail))
        driver = self.engine.__dict__["_agent_driver"]
        yielded = driver.yielded
        self.step(10)
        self.assertEqual(driver.yielded - yielded, 10)
        self.assertEqual(self.tasks(a_), [("move_to_place", "active")])
        start = ((x - gx) ** 2 + (y - gy) ** 2) ** 0.5
        mid = ((self.pos(a_)[0] - gx) ** 2 + (self.pos(a_)[1] - gy) ** 2) ** 0.5
        self.assertLess(mid, start - 5.0, "it walks toward the point")
        for _ in range(60):
            self.step(5)
            if not self.tasks(a_):
                break
        self.assertEqual(self.tasks(a_), [], "the task completes on arrival")
        px, py = self.pos(a_)
        self.assertLess(((px - gx) ** 2 + (py - gy) ** 2) ** 0.5, 6.0, "and it stands at the point")
        self.step(1)
        self.assertIsNotNone(driver.last_goal.get(a_), "the driver takes the resident back")

    def test_move_to_place_without_a_point_target_is_unchanged(self):
        """A ``move_to_place`` task that names a place tag (or nothing) keeps the legacy resolution: ``_point_target`` is None for it."""
        from systems.tasks.families.occupation import _point_target
        self.assertIsNone(_point_target({"target_kind": "place", "target_id": "village:use_well", "target_place": {}}))
        self.assertIsNone(_point_target({"target_kind": "place", "target_place": {"x": 1.0, "y": 2.0}}))        # x/y without target_kind point: ignored as before
        self.assertIsNone(_point_target({"target_kind": "point", "target_place": {}}))
        self.assertIsNone(_point_target({"target_kind": "point", "target_place": {"x": "a", "y": 2}}))
        self.assertEqual(_point_target({"target_kind": "point", "target_place": {"x": 3, "y": 4.5}}), (3.0, 4.5))


if __name__ == "__main__":
    unittest.main()
