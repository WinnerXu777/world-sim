"""Anchor-driven NPC motion and schedule on the real maps (P3.5-P3.7): caps, no jitter, slide, anchors, needs scale."""
from authored_village import MAP_FILES, load_village_maps
import json
import math
import os
import unittest
from pathlib import Path

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, LEGACY_PLAYABLE_VILLAGE_CONTRACT, contract_without_epoch
from systems.movement.map_contract import load_from_environment
from systems.movement.spatial import is_standable_point, world_contract
from systems.roster.driver import (ROUTINE_ANCHOR, anchor_driven_slots, anchor_positions, goal_anchor_key, needs_scale_vector, age_scale_vector, map_id_at, roster_of, use_portal,
                                   runtime)
from systems.roster.motion import MAX_STEP_PER_TICK

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


async def roster_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def by_key(engine):
    out = {}
    for slot, uid in enumerate(engine._human_uid_by_slot):
        if uid:
            out[engine.resident_store.get(uid)["roster"]["key"]] = (slot, uid)
    return out


def pos(engine, slot):
    return (float(engine.state.h_tensor[slot, backend.X]), float(engine.state.h_tensor[slot, backend.Y]))


class MotionTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_displacement_never_exceeds_the_cap_and_nobody_is_embedded(self):
        engine = await roster_world()
        keys = by_key(engine)
        previous = {k: pos(engine, v[0]) for k, v in keys.items()}
        worst = 0.0
        for _ in range(500):
            engine.step()
            contract = world_contract(engine)
            for key, (slot, _) in keys.items():
                now = pos(engine, slot)
                worst = max(worst, math.hypot(now[0] - previous[key][0], now[1] - previous[key][1]))
                self.assertTrue(is_standable_point(now, contract), (key, now))
                previous[key] = now
        self.assertLessEqual(worst, MAX_STEP_PER_TICK + 1e-4)
        self.assertEqual(engine.pop_count, 8)  # no births on a roster map

    async def test_residents_reach_their_work_anchors_and_hold_still_without_jitter(self):
        engine = await roster_world()
        keys = by_key(engine)
        for _ in range(700):
            engine.step()
        reached = {k: runtime(engine).at_anchor.get(v[1]) for k, v in keys.items()}
        # the routine mix (schedule choices depend on seeded randomness) decides WHICH anchor, never whether they arrive
        arrived = [v for v in reached.values() if v in ("work", "talk", "sleep")]
        self.assertGreaterEqual(len(arrived), 4, reached)  # one resident may still be walking after a routine change
        history = {k: [] for k in reached}
        for _ in range(60):
            engine.step()
            for key in history:
                history[key].append(pos(engine, keys[key][0]))
        settled = {k: runtime(engine).at_anchor.get(v[1]) for k, v in keys.items()}
        for key, trail in history.items():
            if settled[key] != reached[key]:
                continue  # the routine changed during the window: that resident legitimately walked
            spread = max(math.hypot(p[0] - trail[0][0], p[1] - trail[0][1]) for p in trail)
            self.assertLessEqual(spread, 0.25, f"{key} jitters at its anchor")

    async def test_the_smith_lives_in_the_interior_and_never_leaves_it_by_himself(self):
        engine = await roster_world()
        smith = by_key(engine)["smith"][0]
        for _ in range(600):
            engine.step()
            x, y = pos(engine, smith)
            self.assertTrue(620 <= x <= 716 and 0 <= y <= 80, (x, y))

    async def test_schedule_blocks_send_residents_to_the_matching_anchor_kind(self):
        engine = await roster_world()
        keys = by_key(engine)
        for _ in range(60):
            engine.step()  # dawn: work routines
        day = {k: runtime(engine).goal_key.get(v[1]) for k, v in keys.items()}
        self.assertEqual((day["smith"], day["builder"]), ("work", "work"))
        engine.tick = 1830  # jump the clock into the night block (blocks are 600 ticks)
        for _ in range(40):
            engine.step()
        night = {k: runtime(engine).goal_key.get(v[1]) for k, v in keys.items()}
        self.assertEqual({night[k] for k in ("smith", "builder", "gatherer")}, {"sleep"})
        smith_roster, _ = roster_of(engine, keys["smith"][1])
        sleep = anchor_positions(engine, smith_roster)["sleep"]
        before = math.hypot(*(a - b for a, b in zip(pos(engine, keys["smith"][0]), sleep)))
        for _ in range(60):
            engine.step()
        after = math.hypot(*(a - b for a, b in zip(pos(engine, keys["smith"][0]), sleep)))
        self.assertLess(after, before)  # walking toward the bed, not away

    async def test_new_sleep_interiors_are_reached_through_paired_portals(self):
        engine = await roster_world()
        keys = by_key(engine)
        expected = {"iven": "village_lodge_interior", "elsa": "village_lodge_interior", "orrin": "village_lodge_interior",
                    "rhea": "west_cottage_interior", "nessa": "west_cottage_interior"}
        engine.tick = 1800  # the existing night block; this test exercises routing, not a live-clock recording
        for _ in range(500):
            engine.step()
        for key, target in expected.items():
            slot, uid = keys[key]
            self.assertEqual(map_id_at(engine, pos(engine, slot)), target, key)
            self.assertEqual(runtime(engine).at_anchor.get(uid), "sleep", key)
            self.assertGreaterEqual(engine._teleport_seq.get(uid, 0), 1, key)
            self.assertTrue(is_standable_point(pos(engine, slot), world_contract(engine)), key)

    async def test_the_routine_to_anchor_table(self):
        roster = {"anchors": {"spawn": "a", "work": "b", "talk": "c", "sleep": "d"}}
        self.assertEqual([goal_anchor_key(roster, kind) for kind in ("sleep", "work_site", "socialize", "wander_local", "rest")],
                         ["sleep", "work", "talk", "talk", "sleep"])
        self.assertEqual(goal_anchor_key({"anchors": {"spawn": "a", "work": "b"}}, "sleep"), "work")  # falls back
        self.assertIsNone(goal_anchor_key(roster, "unknown_routine"))
        self.assertEqual(goal_anchor_key(roster, "sleep", override="work"), "work")
        self.assertIn("visit_water", ROUTINE_ANCHOR)

    async def test_aging_is_scaled_by_the_roster_and_legacy_aging_is_unchanged(self):
        engine = await roster_world()
        scales = age_scale_vector(engine, engine.state.h_tensor)
        self.assertAlmostEqual(float(scales[0]), 0.05, places=6)
        before = engine.state.h_tensor[:8, backend.H_AGE].clone()
        for _ in range(200):
            engine.step()
        gained = float((engine.state.h_tensor[:8, backend.H_AGE] - before).mean())
        self.assertAlmostEqual(gained, 200 * 0.05 / backend.TICKS_PER_YEAR, delta=5e-4)  # float32 age near 40
        self.assertLess(gained, 200 / backend.TICKS_PER_YEAR / 10)
        self.assertIsNone(age_scale_vector(None, engine.state.h_tensor))

    async def test_survival_pacing_is_scaled_by_the_roster(self):
        engine = await roster_world()
        scales = needs_scale_vector(engine, engine.state.h_tensor)
        self.assertAlmostEqual(float(scales[0]), 0.015, places=6)
        before = engine.state.h_tensor[:8, backend.HUNGER].clone()
        for _ in range(100):
            engine.step()
        rate = float((engine.state.h_tensor[:8, backend.HUNGER] - before).mean()) / 100.0
        self.assertAlmostEqual(rate, 0.05 * 0.015, places=4)
        self.assertTrue(bool((engine.state.h_tensor[:8, backend.HP] >= 99.9).all()))

    async def test_a_resident_left_on_another_map_walks_to_the_portal_and_goes_home(self):
        from systems.movement.map_contract import find_portal
        engine = await roster_world()
        slot, uid = by_key(engine)["iven"]
        uses_before = getattr(runtime(engine), "portal_uses", 0)  # the runtime outlives worlds within a process
        inside = tuple(find_portal("starter_village", "village:portal_smith")["to"])
        self.assertTrue(use_portal(engine, slot, uid, inside))  # as if a released player left him in the smithy
        self.assertEqual(engine._teleport_seq[uid], 1)
        self.assertEqual(map_id_at(engine, pos(engine, slot)), "smith_interior")
        for _ in range(1500):
            engine.step()
            if map_id_at(engine, pos(engine, slot)) == "starter_village":
                break
        self.assertEqual(map_id_at(engine, pos(engine, slot)), "starter_village")
        self.assertEqual(engine._teleport_seq[uid], 2)
        self.assertEqual(runtime(engine).portal_uses - uses_before, 2)

    async def test_controlled_residents_are_not_driven(self):
        engine = await roster_world()
        keys = by_key(engine)
        slot, uid = keys["iven"]
        engine.player_control.claim_target(engine, controller_id="p", target_kind="human", target_id=uid)
        self.assertNotIn(slot, anchor_driven_slots(engine))
        start = pos(engine, slot)
        for _ in range(60):
            engine.step()
        self.assertEqual(pos(engine, slot), start)  # a possessed resident only moves on input


class LegacyTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_legacy_worlds_have_no_driven_residents_scales_or_limits(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        self.assertEqual(anchor_driven_slots(engine), [])
        self.assertIsNone(needs_scale_vector(engine, engine.state.h_tensor))
        self.assertIsNone(age_scale_vector(engine, engine.state.h_tensor))
        for _ in range(20):
            engine.step()
        self.assertEqual(contract_without_epoch(engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertEqual(engine.pop_count >= 4, True)


if __name__ == "__main__":
    unittest.main()
