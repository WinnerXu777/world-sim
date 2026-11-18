"""Roster applied at world creation (P3.4): residents on their anchors with roles, traits, stock and bindings."""
from authored_village import MAP_FILES, load_village_maps
import json
import os
import unittest
import uuid
from pathlib import Path

from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation, LEGACY_PLAYABLE_VILLAGE_CONTRACT, contract_without_epoch
from persistence.sessions import GameSessions
from systems.movement.map_contract import load_from_environment
from systems.movement.spatial import is_standable_point, world_contract
from systems.roster.apply import apply_roster, clear_roster_cache, has_roster, roster_for_map

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


def load_both():
    load_village_maps()


async def roster_world():
    load_both()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def residents(engine):
    out = {}
    for slot, uid in enumerate(engine._human_uid_by_slot):
        if uid:
            record = engine.resident_store.get(uid)
            out[record["roster"]["key"]] = (slot, uid, record)
    return out


def position(engine, slot):
    return float(engine.state.h_tensor[slot, backend.X]), float(engine.state.h_tensor[slot, backend.Y])


class RosterApplyTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_eight_named_residents_with_roster_keys_and_original_roles(self):
        engine = await roster_world()
        found = residents(engine)
        self.assertEqual(sorted(found), ["builder", "elsa", "gatherer", "iven", "nessa", "orrin", "rhea", "smith"])
        self.assertEqual({k: v[2]["profile"]["name"] for k, v in found.items()},
                         {"smith": "Brann", "builder": "Mara", "gatherer": "Toma", "iven": "Iven", "elsa": "Elsa", "rhea": "Rhea", "orrin": "Orrin", "nessa": "Nessa"})
        self.assertEqual({k: v[2]["occupation"]["kind"] for k, v in found.items() if k in ("smith", "builder", "gatherer")},
                         {"smith": "smith", "builder": "builder", "gatherer": "gatherer"})
        self.assertEqual(engine.pop_count, 8)  # no hard-coded villagers are created on top
        for key in ("rhea", "orrin", "nessa"):
            self.assertIsNone(found[key][2]["roster"]["role"])
            self.assertEqual(found[key][2]["roster"]["work_mode"], "anchor_only")

    async def test_residents_stand_on_standable_points_near_their_spawn_anchors(self):
        engine = await roster_world()
        contract = world_contract(engine)
        found = residents(engine)
        for key, (slot, _, _) in found.items():
            self.assertTrue(is_standable_point(position(engine, slot), contract), key)
        smith_x, smith_y = position(engine, found["smith"][0])
        self.assertEqual((smith_x, smith_y), (660.0, 56.0))  # smith:spawn (40, 56) + the interior origin (620, 0)
        spawn = (184.0, 160.0)
        for key in ("builder", "gatherer", "iven", "elsa", "rhea", "orrin", "nessa"):
            x, y = position(engine, found[key][0])
            self.assertLessEqual(max(abs(x - spawn[0]), abs(y - spawn[1])), 2 * 2.4 * 2 + 1e-6, key)
        self.assertEqual(len({position(engine, found[k][0]) for k in found}), 8)  # no stacking

    async def test_inventories_are_exactly_the_roster_seed(self):
        engine = await roster_world()
        found = residents(engine)
        def items(key):
            inv = backend.get_owner_inventory(engine.inventory_state, "human", found[key][1])
            return {i["kind"]: i["quantity"] for i in inv["items"]}
        self.assertEqual(items("smith"), {"iron_ingot": 4, "wood_bundle": 4, "hammer": 1, "coin": 20})
        self.assertEqual(items("builder"), {"hammer": 1, "coin": 35})
        self.assertEqual(items("iven"), {"coin": 40, "rations": 1})
        self.assertEqual(items("gatherer"), {"basket": 1, "coin": 35})
        self.assertEqual(items("elsa"), {"coin": 40, "bandage": 1})
        self.assertEqual(items("rhea"), {"coin": 25, "basket": 1, "rations": 2})
        self.assertEqual(items("orrin"), {"coin": 60, "basket": 1, "rations": 1})
        self.assertEqual(items("nessa"), {"coin": 30, "bandage": 2, "rations": 1})
        smith_inv = backend.get_owner_inventory(engine.inventory_state, "human", found["smith"][1])
        self.assertGreaterEqual((smith_inv["capacity_slots"], smith_inv["capacity_weight"]), (16, 80.0))

    async def test_personality_override_and_binding_record(self):
        engine = await roster_world()
        smith = residents(engine)["smith"][2]
        self.assertEqual(smith["personality"]["archetype"], "stoic_survivor")
        self.assertEqual(smith["personality"]["traits"]["greed"], 0.45)
        self.assertEqual(smith["personality"]["traits"]["discipline"], 0.8)
        self.assertEqual(smith["roster"]["anchors"]["work"], "smith:work_forge")
        self.assertEqual((smith["roster"]["work_mode"], smith["roster"]["needs_scale"]), ("occupation", 0.015))
        self.assertTrue(smith["schedule_state"].get("current_routine"))
        self.assertEqual(residents(engine)["iven"][2]["occupation"]["kind"] != "smith", True)

    async def test_the_result_is_deterministic(self):
        first = await roster_world()
        snapshot = {k: (position(first, v[0]), v[1], v[2]["occupation"]["kind"]) for k, v in residents(first).items()}
        second = await roster_world()
        self.assertEqual(snapshot, {k: (position(second, v[0]), v[1], v[2]["occupation"]["kind"]) for k, v in residents(second).items()})

    async def test_the_binding_survives_save_and_restore(self):
        load_both()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                _test_storage / "roster_apply" / uuid.uuid4().hex, backend.create_genesis, 905, map_name="starter_village")
        await sessions.new("Roster")
        before = {k: (v[1], v[2]["roster"], v[2]["occupation"]["kind"]) for k, v in residents(backend.engine).items()}
        save_id = sessions.active_id
        backend.engine.reset_world()
        await sessions.continue_world(save_id)
        after = {k: (v[1], v[2]["roster"], v[2]["occupation"]["kind"]) for k, v in residents(backend.engine).items()}
        self.assertEqual(before, after)
        self.assertEqual(backend.engine.pop_count, 8)

    async def test_apply_is_refused_for_a_roster_that_does_not_fit(self):
        engine = await roster_world()
        roster = roster_for_map("starter_village")
        broken = type(roster)(roster.map_id, roster.needs_scale, tuple(
            type(r)(r.key, r.name, r.sex, r.age, r.role, r.archetype, r.traits, {**r.anchors, "work": "nope:missing"}, r.stock, r.personal,
                    r.inventory, r.work_mode) for r in roster.residents))
        with self.assertRaises(ValueError):
            apply_roster(engine, "starter_village", broken)

    async def test_legacy_maps_and_rosterless_authored_maps_are_unchanged(self):
        self.assertFalse(has_roster("playable_village"))
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertEqual(backend.engine.pop_count, 4)
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        for resident in residents_any(backend.engine):
            self.assertNotIn("roster", resident)

    async def test_missing_roster_file_means_no_roster(self):
        clear_roster_cache()
        self.assertIsNone(roster_for_map("no_such_map"))


def residents_any(engine):
    return [engine.resident_store.get(uid) for uid in engine._human_uid_by_slot if uid]


if __name__ == "__main__":
    unittest.main()
