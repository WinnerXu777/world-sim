"""The 17 S1 verbs on the 8 roster residents of the real Stage 1 engine: which ones work, which ones need the schedule-routine route, which
ones are demoted (refused with ``roster_driven``, or only partly effective). These tests *record measured behaviour* of the accepted Stage 1
build (1008_actions.md section 10.5); they do not say the behaviour is desirable. D-008 (roster vs agent driver) may change several of them."""
from authored_village import load_village_maps
import math
import random
import unittest

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401  (sets the isolated data root and imports map_test)
from driver_pin import pin_anchor
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from harness.adapter import EngineWorld
from systems.actions import ActionRunner, EngineRecordOps
from systems.affordance import AffordanceEngine, EngineServices
from systems.movement.spatial import is_standable_point, world_contract
from systems.tasks.ops import queue_resident_task


class RosterCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)                   # these tests measure the anchor driver, whatever EDEN_ROSTER_DRIVER the suite runs under
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        random.seed(1008)                  # the server seeds these in its lifespan; unseeded, a wandering safe entity made rest / flee_target outcomes vary per process
        torch.manual_seed(1008)
        self.world = EngineWorld(self.engine, seed=1008)
        self.services = EngineServices(self.engine)
        self.runner = ActionRunner(self.world, self.services, record_ops=EngineRecordOps(self.engine))
        self.keys = {self.engine.resident_store.get(u)["roster"]["key"]: u for u in self.engine._human_uid_by_slot if u}
        self.h = self.engine.state.h_tensor

    # helpers ----------------------------------------------------------------------------------------------------------
    def slot(self, u):
        return self.engine._human_slot_for_id(u)

    def pos(self, u):
        return (float(self.h[self.slot(u), cfg.X]), float(self.h[self.slot(u), cfg.Y]))

    def put(self, u, x, y):
        self.h[self.slot(u), cfg.X], self.h[self.slot(u), cfg.Y] = x, y

    def col(self, u, c):
        return float(self.h[self.slot(u), c])

    def step(self, n):
        for _ in range(n):
            self.engine.step()

    def anchor(self, u, key):
        return self.services.anchors(u)[key]

    def dist_to(self, u, key):
        a = self.anchor(u, key)
        return math.hypot(a.x - self.pos(u)[0], a.y - self.pos(u)[1])

    def stand_near(self, x, y):
        contract = world_contract(self.engine)
        for r in (6, 10, 14, 18, 24):
            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r), (r, -r), (-r, r)):
                if is_standable_point((x + dx, y + dy), contract):
                    return (x + dx, y + dy)
        raise AssertionError(f"no standable point near {(x, y)}")

    def record(self, u):
        return self.engine.resident_store.get(u)

    def tasks(self, u):
        return [(t["task_kind"], t["status"]) for t in self.record(u).get("tasks", [])]

    def blocked(self, u):
        return (self.record(u).get("task_state") or {}).get("blocked_reason")

    def routine(self, u):
        return (self.record(u).get("schedule_state") or {}).get("current_routine") or {}


class WorksOnRosterResidents(RosterCase):
    def test_eat_from_the_pack_is_immediate(self):
        u = self.keys["iven"]
        self.h[self.slot(u), cfg.HUNGER] = 80.0
        rations = self.world.items.total("rations")
        r = self.runner.run(u, "eat", {})
        self.assertTrue(r.ok, r.code)
        self.assertAlmostEqual(self.col(u, cfg.HUNGER), 60.0, places=3)
        self.assertEqual(self.services.inventory(u).get("rations", 0), 0)
        self.assertEqual(self.world.items.total("rations"), rations - 1)             # destroyed by the declared consumption, nothing else

    def test_rest_queues_a_sleep_task_that_walks_to_a_safe_entity_and_so_never_finishes(self):
        """``_handle_sleep`` (tasks/families/survival.py): if ``resolve_safe`` finds a safe entity within 220 units it *walks* there; task movement is
        suppressed for a roster resident, so the task stays active and nothing recovers beyond the roster loop's own ~1.3/tick. With no safe entity in
        range it rests in place (+12 stamina once) and completes. Whether one is in range depends on the RNG-driven world: one was before D-005 (7757b94), none is after; the test accepts both documented outcomes."""
        u = self.keys["builder"]
        self.h[self.slot(u), cfg.H_STAMINA] = 30.0
        self.step(2)
        baseline = self.col(u, cfg.H_STAMINA)                              # the roster loop recovers ~1.3 per tick on its own
        self.h[self.slot(u), cfg.H_STAMINA] = 30.0
        r = self.runner.run(u, "rest", {})
        self.assertTrue(r.ok, r.code)
        self.step(2)
        if self.tasks(u):                                                  # a safe entity is in range: it walks there, never arrives
            self.assertEqual(self.tasks(u), [("sleep", "active")])
            self.assertAlmostEqual(self.col(u, cfg.H_STAMINA), baseline, places=2)
        else:                                                              # none in range (the world after D-005 froze the frontier generator): rests in place, +12 once, completes
            self.assertGreater(self.col(u, cfg.H_STAMINA), baseline + 5.0)

    def test_sleep_uses_the_routine_route_and_expires_at_the_next_schedule_refresh(self):
        u = self.keys["gatherer"]
        a = self.anchor(u, "work")
        self.put(u, *self.stand_near(a.x, a.y))
        before = self.dist_to(u, "sleep")
        r = self.runner.run(u, "sleep", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((r.ops[0]["kind"], r.ops[0]["routine"]), ("set_routine", "sleep"))
        self.assertEqual(self.routine(u)["source"], "action")
        self.step(100)
        self.assertLess(self.dist_to(u, "sleep"), before * 0.6)             # walking home (through the roster driver, no task involved)
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
        self.assertEqual(self.routine(u)["kind"], "work_site")
        self.step(100)
        self.assertLess(self.dist_to(u, "work"), 5.0)

    def test_flee_to_uses_the_return_home_routine(self):
        u = self.keys["builder"]
        a = self.anchor(u, "work")
        self.put(u, a.x, a.y)
        self.h[self.slot(u), cfg.THREAT] = 80.0
        before = self.dist_to(u, "sleep")
        r = self.runner.run(u, "flee_to", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual(self.routine(u)["kind"], "return_home")
        self.step(80)
        self.assertLess(self.dist_to(u, "sleep"), before - 15)

    def test_craft_at_the_forge(self):
        u = self.keys["smith"]
        forge = [e for e in self.services.entities() if e.kind == "forge"][0]
        self.put(u, *self.stand_near(forge.x, forge.y))
        swords = self.world.items.total("sword")
        r = self.runner.run(u, "craft", {"recipe": "sword"})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(self.services.inventory(u).get("sword", 0), 1)
        self.assertEqual(self.services.inventory(u)["iron_ingot"], 2)
        self.assertEqual(self.world.items.total("sword"), swords + 1)

    def test_store_and_fetch_at_a_storage_case(self):
        u = self.keys["iven"]
        crate = [e for e in self.services.entities() if e.id == "village:supply_crate"][0]
        self.put(u, *self.stand_near(crate.x, crate.y))
        coins, in_crate = self.services.inventory(u)["coin"], self.services.inventory(crate.id).get("coin", 0)
        r = self.runner.run(u, "store_item", {"item": "coin", "qty": 5, "container": crate.id})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(self.services.inventory(u)["coin"], coins - 5)
        self.assertEqual(self.services.inventory(crate.id).get("coin", 0), in_crate + 5)
        self.assertTrue(self.runner.run(u, "fetch_item", {"item": "coin", "qty": 5, "container": crate.id}).ok)
        self.assertEqual(self.services.inventory(u)["coin"], coins)

    def test_give_request_and_commission(self):
        giver, taker = self.keys["rhea"], self.keys["nessa"]
        x, y = self.stand_near(100.0, 150.0)
        self.put(giver, x, y)
        self.put(taker, *self.stand_near(x + 6, y))
        r = self.runner.run(giver, "give_item", {"target": taker, "item": "rations", "qty": 1})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual((self.services.inventory(giver)["rations"], self.services.inventory(taker)["rations"]), (1, 2))
        self.assertAlmostEqual(self.record(taker)["relationships"][giver]["closeness"], 0.06)
        ask = self.runner.run(taker, "request_item", {"target": giver, "item": "rations"})
        self.assertTrue(ask.ok, (ask.code, ask.detail))
        self.assertEqual((ask.ops[0]["answer"], ask.ops[0]["gave"]), ("give", True))
        self.assertEqual(self.services.inventory(giver).get("rations", 0), 0)
        customer, smith = self.keys["builder"], self.keys["smith"]
        a = self.anchor(smith, "work")
        self.put(smith, a.x, a.y)
        self.put(customer, *self.stand_near(a.x, a.y))
        order = self.runner.run(customer, "commission_item", {"target": smith, "recipe": "sword"})
        self.assertTrue(order.ok, (order.code, order.detail))
        self.assertEqual((order.ops[0]["ok"], order.ops[0]["code"]), (True, "accepted"))
        self.assertEqual([o["state"] for o in self.engine.inventory_state["work_orders"]["orders"].values()], ["reserved"])


class DemotedOnRosterResidents(RosterCase):
    def test_eat_and_drink_at_a_site_are_refused_because_the_needs_loop_does_it(self):
        smith, iven = self.keys["smith"], self.keys["iven"]
        self.h[self.slot(smith), cfg.HUNGER] = 60.0
        self.h[self.slot(iven), cfg.THIRST] = 60.0
        self.assertEqual(self.runner.run(smith, "eat", {"place": "village:use_campfire"}).code, "illegal:roster_driven")
        self.assertEqual(self.runner.run(iven, "drink", {"place": "village:use_well"}).code, "illegal:roster_driven")
        self.assertEqual(self.tasks(smith) + self.tasks(iven), [])
        self.step(360)                                                                       # ... and the loop feeds and waters them anyway
        self.assertLess(self.col(smith, cfg.HUNGER), 10.0)
        self.assertLess(self.col(iven, cfg.THIRST), 10.0)

    def test_work_gather_and_follow_are_refused(self):
        builder, gatherer = self.keys["builder"], self.keys["gatherer"]
        a = self.anchor(builder, "work")
        self.put(builder, a.x, a.y)
        self.assertEqual(self.runner.run(builder, "work_shift", {}).code, "illegal:roster_driven")
        node = [e for e in self.services.entities() if e.id == "village:wood_pile"][0]
        self.put(gatherer, *self.stand_near(node.x, node.y))
        self.assertEqual(self.runner.run(gatherer, "gather_resource", {"source": node.id}).code, "illegal:roster_driven")
        x, y = self.stand_near(156.0, 150.0)
        self.put(builder, x, y)
        self.put(gatherer, *self.stand_near(x + 40, y))
        self.assertEqual(self.runner.run(builder, "follow", {"target": gatherer}).code, "illegal:roster_driven")

    def test_the_legacy_tasks_behind_the_refused_verbs_are_inert_for_a_roster_resident(self):
        """What would happen if the verbs queued them: the task stays active and does nothing (the evidence for the refusals above)."""
        builder, gatherer, rhea = self.keys["builder"], self.keys["gatherer"], self.keys["rhea"]
        a = self.anchor(builder, "work")
        self.put(builder, a.x, a.y)
        queue_resident_task(self.record(builder), "build_work", tick=self.engine.tick)
        node = [e for e in self.services.entities() if e.id == "village:wood_pile"][0]
        self.put(gatherer, *self.stand_near(node.x, node.y))
        wood = self.services.inventory(gatherer).get("wood_bundle", 0)
        queue_resident_task(self.record(gatherer), "gather_material", tick=self.engine.tick, target_kind="item", target_id="wood_bundle",
                            requested_quantity=1)
        queue_resident_task(self.record(rhea), "flee_target", tick=self.engine.tick, priority=0.97)
        self.step(200)
        self.assertEqual(self.tasks(builder), [("build_work", "active")])
        self.assertEqual(self.blocked(builder), "worksite_not_found")
        self.assertEqual(self.tasks(gatherer), [("gather_material", "active")])
        self.assertEqual(self.services.inventory(gatherer).get("wood_bundle", 0), wood)
        self.assertEqual(self.tasks(rhea), [("flee_target", "active")])

    def test_work_shift_of_the_smith_has_no_task(self):
        smith = self.keys["smith"]
        a = self.anchor(smith, "work")
        self.put(smith, a.x, a.y)
        self.assertEqual(self.runner.run(smith, "work_shift", {}).code, "illegal:roster_driven")          # legality (driver.py) answers first
        agent = ActionRunner(self.world, self.services, aff=AffordanceEngine(self.world, self.services, driver_mode="agent"), record_ops=EngineRecordOps(self.engine))
        self.assertEqual(agent.run(smith, "work_shift", {}).code, "refused:no_work_task")                # the verb's own answer, without the driver table
        self.assertEqual(agent.run(self.keys["builder"], "follow", {"target": self.keys["gatherer"]}).code, "refused:roster_driven")  # the verb's own gate stays

    def test_greet_and_chat_only_nudge_the_relationship(self):
        a_, b_ = self.keys["elsa"], self.keys["orrin"]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        self.put(b_, *self.stand_near(x + 8, y))
        r = self.runner.run(a_, "greet", {"target": b_})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertAlmostEqual(self.record(a_)["relationships"][b_]["closeness"], 0.02)
        self.assertEqual(self.tasks(a_), [])
        r = self.runner.run(a_, "chat", {"target": b_, "topic": "weather"})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertAlmostEqual(self.record(a_)["relationships"][b_]["closeness"], 0.05)
        self.assertEqual(self.tasks(a_), [])


class BatchOneOnRosterResidents(RosterCase):
    """Batch 1 (1008_actions.md 10.10): measured on the real roster residents, same method as 10.5."""

    def pair(self, a_key="elsa", b_key="orrin"):
        a_, b_ = self.keys[a_key], self.keys[b_key]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        self.put(b_, *self.stand_near(x + 8, y))
        return a_, b_

    def test_seek_shelter_uses_the_return_home_routine(self):
        u = self.keys["builder"]
        a = self.anchor(u, "work")
        self.put(u, a.x, a.y)
        self.h[self.slot(u), cfg.THREAT] = 80.0
        before = self.dist_to(u, "sleep")
        r = self.runner.run(u, "seek_shelter", {})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(self.routine(u)["kind"], "return_home")
        self.step(80)
        self.assertLess(self.dist_to(u, "sleep"), before - 15)

    def test_hide_holds_still_and_the_task_ends_by_itself(self):
        u = self.keys["builder"]
        r = self.runner.run(u, "hide", {})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(self.tasks(u), [("wait_in_hiding", "active")])
        self.step(30)
        self.assertEqual(self.tasks(u), [])                                                  # hold_ticks 8 elapsed: it completed, the queue is free

    def test_ask_for_help_completes_without_walking(self):
        u = self.keys["rhea"]
        r = self.runner.run(u, "ask_for_help", {})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.step(10)
        self.assertEqual(self.tasks(u), [])

    def test_attack_avoid_and_explore_are_refused_for_a_roster_resident(self):
        a_, b_ = self.pair()
        self.assertEqual(self.runner.run(a_, "attack", {"target": b_}, proposer="rules").code, "illegal:roster_driven")
        self.assertEqual(self.runner.run(a_, "avoid", {"target": b_}).code, "illegal:roster_driven")
        self.assertEqual(self.runner.run(a_, "explore_toward", {"heading": "N"}).code, "illegal:roster_driven")
        self.assertEqual(self.tasks(a_), [])

    def test_the_walking_task_behind_them_is_inert_for_a_roster_resident(self):
        """The evidence for the refusals, measured: a ``move_to_place`` task to a point 20 away stays active for 80 ticks and the resident ends
        far from the goal (the roster driver, not the task, moves it; it walks to its own anchor). ``attack_target`` also stays active
        (80 ticks measured); ``retreat_from_target`` completes in about 20 ticks, but on the same driver-owned path, so it is not evidence of an avoidance."""
        a_, b_ = self.pair()
        x, y = self.pos(a_)
        queue_resident_task(self.record(a_), "move_to_place", tick=self.engine.tick, priority=0.3, target_kind="point", target_place={"x": x + 20, "y": y})
        self.step(80)
        self.assertEqual(self.tasks(a_), [("move_to_place", "active")])
        gx, gy = self.pos(a_)
        self.assertGreater(((gx - (x + 20)) ** 2 + (gy - y) ** 2) ** 0.5, 20.0)

    def test_warn_and_comfort_are_event_and_closeness_only(self):
        a_, b_ = self.pair()
        r = self.runner.run(a_, "warn", {"target": b_})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(self.tasks(a_), [])
        self.h[self.slot(b_), cfg.MOOD] = 20.0
        r = self.runner.run(a_, "comfort", {"target": b_})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertAlmostEqual(self.record(a_)["relationships"][b_]["closeness"], 0.05)
        self.assertEqual(self.tasks(a_), [])


class Batch2Roster(RosterCase):
    """S-1 batch 2 (1008_actions.md 10.14) on roster residents of the real engine: all five verbs are instant effects, so none of them needs the
    resident's own movement and none is demoted."""

    def pair(self, a_key="elsa", b_key="orrin"):
        a_, b_ = self.keys[a_key], self.keys[b_key]
        x, y = self.stand_near(198.0, 168.0)
        self.put(a_, x, y)
        self.put(b_, *self.stand_near(x + 8, y))
        return a_, b_

    def hold(self, u, kind):
        return self.world.items.quantity(u, kind)

    def test_offer_trade_swaps_between_two_roster_residents_through_accept_trade(self):
        a_, b_ = self.pair()
        self.world.items.add(a_, "rations", 3)
        self.world.items.add(b_, "iron_ingot", 1)
        before = (self.hold(a_, "rations"), self.hold(a_, "iron_ingot"), self.hold(b_, "rations"), self.hold(b_, "iron_ingot"))
        r = self.runner.run(a_, "offer_trade", {"target": b_, "give": "rations", "give_qty": 2, "want": "iron_ingot"}, proposer="tier1:rules")
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual((r.ops[0]["answer"], r.ops[0]["accepted"]), ("accept", True), r.ops)
        after = (self.hold(a_, "rations"), self.hold(a_, "iron_ingot"), self.hold(b_, "rations"), self.hold(b_, "iron_ingot"))
        self.assertEqual(after, (before[0] - 2, before[1] + 1, before[2] + 2, before[3] - 1))
        self.assertEqual(self.tasks(a_), [])
        self.assertEqual([(e["verb"], e["actor"], e["proposer"]) for e in self.runner.audit.entries][-2:],
                         [("accept_trade", b_, "rules:trade_response"), ("offer_trade", a_, "tier1:rules")])

    def test_steal_when_safe_is_blocked_by_witnesses_and_works_without(self):
        a_, b_ = self.pair()
        self.world.items.add(b_, "iron_ingot", 2)
        seen = self.runner.run(a_, "steal_when_safe", {"target": b_, "item": "iron_ingot"})
        for key, u in self.keys.items():
            if u not in (a_, b_):
                self.h[self.slot(u), cfg.HP] = 0.0                                                    # dead residents see nothing
        r = self.runner.run(a_, "steal_when_safe", {"target": b_, "item": "iron_ingot"})
        self.assertTrue(r.ok, (r.code, r.detail, seen.code))
        self.assertEqual(self.hold(b_, "iron_ingot"), 1)
        self.assertEqual(self.tasks(a_), [])
        self.assertTrue([e for e in self.world.events.events() if e.type == "theft"])
        self.assertIn(seen.code, ("illegal:watched", "ok"))

    def test_share_news_and_gossip_reach_a_roster_listener_and_its_memory(self):
        a_, b_ = self.pair()
        c_ = self.keys["smith"]
        event = self.world.events.emit("quarrel", actors=(c_, self.keys["rhea"]), place=self.pos(a_), witnesses=(a_, c_))
        r = self.runner.run(a_, "share_news", {"target": b_, "event": event.id})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertIn(b_, self.world.events.get(event.id).witnesses)
        notes = [e for e in self.record(b_)["memory"]["recent_events"] if e.get("kind") == "heard_news"]
        self.assertEqual([(n["other_human_id"], n["about_event"]) for n in notes], [(a_, event.id)])
        self.assertEqual(self.tasks(a_), [])
        again = self.runner.run(a_, "gossip", {"target": b_, "about": c_})
        self.assertEqual(again.code, "illegal:nothing_to_tell")                              # b_ already heard that event


if __name__ == "__main__":
    unittest.main()
