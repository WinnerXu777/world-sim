"""Food/water loop for roster residents on the real maps: thresholds send residents to the well/fire through the mover
(portals for the smith), the need resets, the routine resumes; rations back up missing sites; commission progress is kept."""
from authored_village import MAP_FILES, load_village_maps
import json
import math
import os
import unittest
from driver_pin import pin_anchor
import uuid
from pathlib import Path

from test_startup_preservation import backend
import genesis_config as cfg
from test_map_contract import AsyncRegistryIsolation
from systems.commission.config import COMMISSION_CONFIG
from systems.commission.engine import find_smith
from systems.movement.map_contract import load_from_environment
from systems.roster.driver import anchor_driven_slots, anchor_positions, map_id_at, roster_of, runtime
from systems.roster.load import DEFAULT_NEEDS, parse_roster
from systems.roster.validate import anchors_from_registry, validate_roster

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"
WELL, FIRE = (188.0, 148.0), (152.0, 192.0)


async def roster_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def residents(engine):
    out = {}
    for slot, uid in enumerate(engine._human_uid_by_slot):
        if uid:
            out[engine.resident_store.get(uid)["roster"]["key"]] = (slot, uid)
    return out


def position(engine, slot):
    return float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y])


def raw_roster(**needs):
    base = json.loads((ROOT / "world_data" / "rosters" / "starter_village.json").read_text(encoding="utf-8"))
    if needs:
        base["needs"] = needs
    return base


class NeedsFileTests(unittest.TestCase):
    def test_defaults_when_the_block_is_missing_and_the_shipped_roster_names_the_well_and_the_fire(self):
        data = raw_roster()
        roster, issues = parse_roster({k: v for k, v in data.items() if k != "needs"})
        self.assertEqual((roster.needs, issues), (DEFAULT_NEEDS, []))
        shipped, _ = parse_roster(data)
        self.assertEqual((shipped.needs["threshold"], shipped.needs["water"]["anchor"], shipped.needs["food"]["anchor"]),
                         (30.0, "village:use_well", "village:use_campfire"))

    def test_bad_values_are_reported_one_by_one(self):
        for bad in ({"threshold": 2}, {"threshold": "x"}, {"ration": -1}, {"trip_timeout_ticks": 5}, {"water": {"ticks": 0}},
                    {"water": {"anchor": 3}}, {"food": []}, {"fire": {}}):
            roster, issues = parse_roster(raw_roster(**bad))
            self.assertIsNone(roster, bad)
            self.assertTrue(any(i.path.startswith("needs") for i in issues), (bad, [str(i) for i in issues]))
        bad_resident = raw_roster()
        bad_resident["residents"][0]["needs_sites"] = "yes"
        self.assertIsNone(parse_roster(bad_resident)[0])

    def test_site_anchors_must_exist_on_the_loaded_maps(self):
        load_village_maps()
        try:
            anchors = anchors_from_registry("starter_village")
            roster, _ = parse_roster(raw_roster())
            self.assertEqual([i for i in validate_roster(roster, anchors) if i.severity == "error"], [])
            bad, _ = parse_roster(raw_roster(water={"anchor": "village:no_such_well"}))
            self.assertTrue(any(i.path == "needs.water.anchor" for i in validate_roster(bad, anchors)))
            free, _ = parse_roster(raw_roster(water={"anchor": None}, food={"anchor": None}))
            self.assertEqual([i for i in validate_roster(free, anchors) if i.severity == "error"], [])
        finally:
            from systems.movement.map_contract import clear_map_contracts
            clear_map_contracts()


class NeedsLoopTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)

    def need(self, engine, slot, kind):
        return float(engine.state.h_tensor[slot, cfg.THIRST if kind == "water" else cfg.HUNGER])

    async def test_a_thirsty_resident_walks_to_the_well_stands_there_drinks_and_goes_back(self):
        engine = await roster_world()
        slot, uid = residents(engine)["gatherer"]
        engine.state.h_tensor[slot, cfg.THIRST] = 31.0
        reached, drank_at = None, None
        for tick in range(1500):
            engine.step()
            if reached is None and math.hypot(*(a - b for a, b in zip(position(engine, slot), WELL))) <= 3.0:
                reached = tick
            if reached is not None and drank_at is None and self.need(engine, slot, "water") == 0.0:
                drank_at = tick
                break
        self.assertIsNotNone(reached, "never reached the well")
        self.assertIsNotNone(drank_at)
        self.assertGreaterEqual(drank_at - reached, 39)  # he stood there the whole drink time
        self.assertEqual(runtime(engine).trips, {})

    async def test_hunger_goes_to_the_campfire(self):
        engine = await roster_world()
        slot, uid = residents(engine)["builder"]
        engine.state.h_tensor[slot, cfg.HUNGER] = 30.5
        goal = None
        for _ in range(1500):
            engine.step()
            if runtime(engine).trips.get(uid):
                goal = runtime(engine).goal_key.get(uid)
            if self.need(engine, slot, "food") == 0.0:
                break
        self.assertEqual(goal, "food")
        self.assertEqual(self.need(engine, slot, "food"), 0.0)

    async def test_the_smith_crosses_the_portal_to_the_well_and_back_and_a_working_order_loses_nothing(self):
        saved = dict(COMMISSION_CONFIG)
        COMMISSION_CONFIG.update(work_ticks_per_time_unit=20, forge_wait_ticks=30)  # 30 work ticks instead of 900
        try:
            engine = await roster_world()
            people = residents(engine)
            smith_id, _ = find_smith(engine)
            smith_slot = engine._human_slot_for_id(smith_id)
            customer_slot, customer_id = people["iven"]
            claim = engine.player_control.claim_target(engine, controller_id="cust", target_kind="human", target_id=customer_id)
            env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
            sx, sy = position(engine, smith_slot)
            engine.state.h_tensor[customer_slot, cfg.X], engine.state.h_tensor[customer_slot, cfg.Y] = sx + 9.0, sy + 3.0
            payload = {**env, "command_id": str(uuid.uuid4())}
            self.assertEqual(engine.command_inbox.submit(engine, "commission_request", payload)["status"], "received")
            engine.step()
            self.assertTrue(engine.command_inbox.result(payload["command_id"])["accepted"])
            orders = lambda: list(engine.inventory_state["work_orders"]["orders"].values())
            for _ in range(200):
                if orders()[0]["state"] == "working" and orders()[0]["progress_ticks"] >= 3:
                    break
                engine.step()
            order = orders()[0]
            progress_when_thirsty = order["progress_ticks"]
            self.assertTrue(0 < progress_when_thirsty < 30)
            engine.state.h_tensor[smith_slot, cfg.THIRST] = 31.0
            visited_village, seen = False, []
            for _ in range(2500):
                engine.step()
                order = orders()[0]
                if runtime(engine).trips.get(smith_id) and map_id_at(engine, position(engine, smith_slot)) == "starter_village":
                    visited_village = True
                    seen.append(order["progress_ticks"])  # paused while he is away: not lost, not failed
                if order["state"] == "ready":
                    break
            self.assertTrue(visited_village, "the smith never left the smithy for the well")
            self.assertGreater(len(seen), 50)
            self.assertEqual(len(set(seen)), 1)
            self.assertGreaterEqual(seen[0], progress_when_thirsty)
            self.assertLess(seen[0], order["work_ticks"])
            self.assertEqual(order["state"], "ready")  # finished after he walked back to the forge
            self.assertEqual(order["progress_ticks"], order["work_ticks"])
            self.assertLess(self.need(engine, smith_slot, "water"), 1.0)  # reset to 0 at the well, a little thirst since
        finally:
            COMMISSION_CONFIG.clear()
            COMMISSION_CONFIG.update(saved)

    async def test_no_site_means_a_free_ration_on_the_spot(self):
        engine = await roster_world()
        slot, uid = residents(engine)["elsa"]
        roster, _ = roster_of(engine, uid)
        roster["needs_sites"] = False
        engine.state.h_tensor[slot, cfg.THIRST] = 31.0
        engine.state.h_tensor[slot, cfg.HUNGER] = 40.0
        before = getattr(runtime(engine), "rations", 0)
        engine.step()
        self.assertEqual(runtime(engine).trips.get(uid), None)
        self.assertEqual(getattr(runtime(engine), "rations", 0) - before, 2)
        self.assertLess(self.need(engine, slot, "water"), 7.0)  # 31 - 25 (+ one tick of thirst)
        self.assertLess(self.need(engine, slot, "food"), 16.0)
        roster["needs"] = {**roster["needs"], "water": {"anchor": None, "ticks": 40}}
        roster["needs_sites"] = True
        engine.state.h_tensor[slot, cfg.THIRST] = 31.0
        engine.step()
        self.assertLess(self.need(engine, slot, "water"), 7.0)  # a site-less map entry rations too

    async def test_an_unreachable_site_falls_back_to_the_ration_instead_of_waiting_forever(self):
        engine = await roster_world()
        slot, uid = residents(engine)["smith"]  # the forge, the portal and the walk to the well take more than 100 ticks
        roster, _ = roster_of(engine, uid)
        roster["needs"] = {**roster["needs"], "trip_timeout_ticks": 100}
        engine.state.h_tensor[slot, cfg.THIRST] = 31.0
        before = getattr(runtime(engine), "trip_timeouts", 0)
        for _ in range(130):
            engine.step()
        self.assertEqual(getattr(runtime(engine), "trip_timeouts", 0) - before, 1)
        self.assertLess(self.need(engine, slot, "water"), 10.0)
        self.assertEqual(runtime(engine).trips, {})

    async def test_everyone_stays_bounded_over_several_cycles(self):
        engine = await roster_world()
        people = residents(engine)
        for slot, _ in people.values():
            engine.state.h_tensor[slot, cfg.THIRST] = 29.5
            engine.state.h_tensor[slot, cfg.HUNGER] = 29.5
        peaks = {key: 0.0 for key in people}
        done_before = getattr(runtime(engine), "trips_done", 0)
        for _ in range(3000):
            engine.step()
            for key, (slot, _) in people.items():
                peaks[key] = max(peaks[key], self.need(engine, slot, "water"), self.need(engine, slot, "food"))
        for key, peak in peaks.items():
            self.assertLess(peak, 36.0, (key, peaks))
        self.assertGreaterEqual(getattr(runtime(engine), "trips_done", 0) - done_before, 8)  # 5 residents x 2 needs, some twice
        self.assertEqual(getattr(runtime(engine), "trip_blocked", 0), 0)
        self.assertTrue(bool((engine.state.h_tensor[[s for s, _ in people.values()], cfg.HP] >= 99.9).all()))

    async def test_a_possessed_resident_is_not_sent_anywhere(self):
        engine = await roster_world()
        slot, uid = residents(engine)["iven"]
        engine.player_control.claim_target(engine, controller_id="p", target_kind="human", target_id=uid)
        engine.state.h_tensor[slot, cfg.THIRST] = 45.0
        start = position(engine, slot)
        for _ in range(60):
            engine.step()
        self.assertEqual(position(engine, slot), start)
        self.assertNotIn(uid, runtime(engine).trips)  # (he stands beside the well, so the engine's own drink instinct still applies)


    async def test_a_possessed_resident_needs_no_ration_for_a_long_session_and_is_an_ordinary_resident_afterwards(self):
        # ``instinct_incarnation_stabilize`` pins a controlled human's HP at 100 and hunger/thirst at 0 every tick, so a player who stays in
        # one body can neither starve nor die of thirst. 1500 ticks at needs_scale 1.0 are more than 60 game minutes of needs at 0.015.
        engine = await roster_world()
        slot, uid = residents(engine)["builder"]
        engine.player_control.claim_target(engine, controller_id="p", target_kind="human", target_id=uid)
        engine.player_control.clock = lambda: 0.0  # the possession does not lapse (it normally does after 5 s without input)
        roster, _ = roster_of(engine, uid)
        roster["needs_scale"] = 1.0
        h = engine.state.h_tensor
        peak = 0.0
        for _ in range(1500):
            engine.step()
            peak = max(peak, float(h[slot, cfg.HUNGER]), float(h[slot, cfg.THIRST]))
            self.assertEqual(float(h[slot, cfg.HP]), 100.0)
        self.assertEqual(peak, 0.0)
        self.assertNotIn(uid, runtime(engine).trips)  # nobody drives him
        engine.player_control.release_target(engine, controller_id="p")
        roster["needs_scale"] = 0.015
        for _ in range(40):
            engine.step()
        self.assertEqual(anchor_driven_slots(engine).count(slot), 1)  # driven again, with the needs he had (0)
        self.assertLess(float(h[slot, cfg.THIRST]), 1.0)


class LegacyTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_legacy_worlds_have_no_trips(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        for _ in range(20):
            engine.step()
        self.assertEqual(getattr(runtime(engine), "trips", {}), {})
        self.assertEqual(getattr(runtime(engine), "rations", 0), 0)


if __name__ == "__main__":
    unittest.main()
