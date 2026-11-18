"""Portals (G7): POST /control/portal, same-epoch teleport, teleport_seq, idempotency, rejections; dispatch hooks."""
from authored_village import MAP_FILES, load_village_maps
import json
import logging
import os
import unittest
import uuid
from pathlib import Path

import httpx

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES, SMITH
from simulation.dispatch import DISPATCH, Dispatcher
from simulation.portal_commands import PORTAL_REACH
from systems.movement.map_contract import (MAP_CONTRACTS, find_portal, load_from_environment, register_map_file)
from systems.movement.spatial import is_standable_point, world_contract

ROOT = Path(__file__).resolve().parents[1]
REAL_VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
REAL_SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"
INTERIOR = FIXTURES / "example_smith_interior.json"
ORIGIN = [620, 0]
PORTAL = "village:portal_smith"
BACK = "smith:portal_village"  # resolved from the real file in setUp


def load_real_world():
    load_village_maps()


async def real_world():
    load_real_world()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def claim(engine, x, y, controller="portal_test"):
    engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = x, y
    result = engine.player_control.claim_target(engine, controller_id=controller, target_kind="human", target_id=engine._human_uid_by_slot[0])
    return {key: result[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": controller}


def submit(engine, envelope, portal_id=PORTAL, command_id=None, **extra):
    payload = {**envelope, "command_id": command_id or str(uuid.uuid4()), "portal_id": portal_id, **extra}
    return payload, engine.command_inbox.submit(engine, "portal", payload)


def position(engine, slot=0):
    h = engine.state.h_tensor
    return float(h[slot, backend.X]), float(h[slot, backend.Y])


class PortalFlowTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()

    async def asyncTearDown(self):
        DISPATCH.clear()
        await super().asyncTearDown()

    async def test_portals_resolve_in_world_coordinates(self):
        await real_world()
        found = find_portal("starter_village", PORTAL)
        self.assertEqual(found["from"], [128.0, 104.0])
        self.assertTrue(found["to_loaded"])
        entry = json.loads(REAL_SMITH.read_text(encoding="utf-8"))
        local = next(a["position"] for a in entry["anchors"] if a["id"] == "smith:entry")
        self.assertEqual(found["to"], [local[0] + 620.0, local[1]])
        self.assertIsNone(find_portal("starter_village", "nope"))
        self.assertIsNone(find_portal("playable_village", PORTAL))

    async def test_walking_through_a_portal_teleports_in_the_same_epochs(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        epoch, possession = engine.world_epoch, env["possession_epoch"]
        payload, received = submit(engine, env)
        self.assertEqual((received["ok"], received["status"]), (True, "received"))
        engine.step()
        result = engine.command_inbox.result(payload["command_id"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual((result["to_map"], result["teleport_seq"]), ("smith_interior", 1))
        target = tuple(find_portal("starter_village", PORTAL)["to"])
        self.assertEqual(tuple(result["position"]), target)
        self.assertAlmostEqual(position(engine)[0], target[0], places=3)
        self.assertAlmostEqual(position(engine)[1], target[1], places=3)
        self.assertEqual(engine.world_epoch, epoch)  # same epochs
        self.assertEqual(engine.player_control.sessions_by_controller["portal_test"]["possession_epoch"], possession)
        self.assertTrue(is_standable_point(position(engine), world_contract(engine)))

    async def test_no_slide_artefact_on_the_teleport_tick_or_after(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        payload, _ = submit(engine, env)
        engine.step()
        target = position(engine)
        for _ in range(3):
            engine.step()
            self.assertAlmostEqual(position(engine)[0], target[0], places=2)
            self.assertAlmostEqual(position(engine)[1], target[1], places=2)
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["status"], "applied")

    async def test_teleport_seq_is_on_the_frame_and_committed_state_and_grows(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        before = engine._frame_payload["agents"]
        self.assertTrue(all("teleport_seq" not in a for a in before))
        submit(engine, env)
        engine.step()
        engine.step()
        frame_agent = next(a for a in engine._frame_payload["agents"] if a["id"] == engine._human_uid_by_slot[0])
        self.assertEqual(frame_agent["teleport_seq"], 1)
        others = [a for a in engine._frame_payload["agents"] if a["id"] != engine._human_uid_by_slot[0]]
        self.assertTrue(all("teleport_seq" not in a for a in others))
        self.assertEqual(engine.player_control.sessions_by_controller["portal_test"]["committed_state"]["teleport_seq"], 1)
        back = find_portal("starter_village", "smith:portal_village")
        self.assertIsNotNone(back, "the real smith_interior has a portal back to the village")
        engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = back["from"][0], back["from"][1] + 6.0
        payload, _ = submit(engine, env, portal_id="smith:portal_village")
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["teleport_seq"], 2)
        engine.step()
        self.assertEqual(engine.player_control.sessions_by_controller["portal_test"]["committed_state"]["teleport_seq"], 2)

    async def test_commands_are_idempotent_by_command_id(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        payload, first = submit(engine, env)
        again = engine.command_inbox.submit(engine, "portal", payload)
        self.assertEqual(again, first)
        engine.step()
        applied = engine.command_inbox.result(payload["command_id"])
        replay = engine.command_inbox.submit(engine, "portal", payload)
        self.assertEqual(replay, applied)
        engine.step()
        self.assertEqual(engine._teleport_seq[engine._human_uid_by_slot[0]], 1)  # applied once
        conflict = engine.command_inbox.submit(engine, "portal", {**payload, "portal_id": "smith:portal_village"})
        self.assertEqual((conflict["ok"], conflict["reason"]), (False, "command_id_conflict"))

    async def test_rejections(self):
        engine = await real_world()
        env = claim(engine, 40.0, 40.0)  # far from the smith door
        payload, _ = submit(engine, env)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["reason"], "out_of_range")
        self.assertEqual(engine._teleport_seq, {})
        env = claim(engine, 128.0, 110.0 + PORTAL_REACH)  # just outside reach
        payload, _ = submit(engine, env)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["reason"], "out_of_range")
        for bad in ("nope", "", None, 5, "x" * 200):
            payload, _ = submit(engine, env, portal_id=bad)
            engine.step()
            result = engine.command_inbox.result(payload["command_id"])
            self.assertEqual((result["status"], result["reason"]), ("rejected", "unknown_portal"), bad)
        stale = {**env, "world_epoch": "old"}
        _, rejected = submit(engine, stale)
        self.assertEqual((rejected["ok"], rejected["reason"]), (False, "stale_world_epoch"))
        _, rejected = submit(engine, {**env, "possession_epoch": "old"})
        self.assertEqual(rejected["reason"], "stale_possession_epoch")
        _, rejected = submit(engine, {**env, "controller_id": "nobody"})
        self.assertEqual(rejected["reason"], "stale_possession_epoch")
        self.assertEqual(engine._teleport_seq, {})

    async def test_target_not_loaded_when_the_interior_is_not_placed(self):
        register_map_file(REAL_VILLAGE, base_dir=ROOT / "myassets")
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        env = claim(engine, 128.0, 110.0)
        payload, _ = submit(engine, env)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["reason"], "target_not_loaded")
        self.assertEqual(position(engine)[1], 110.0)

    async def test_a_blocked_target_is_rejected_and_nothing_moves(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        entry = MAP_CONTRACTS["smith_interior"]
        for anchor in entry["anchors"]:
            if anchor["id"] == "smith:entry":
                anchor["position"] = [620.0 + 5.0, 5.0]  # inside the interior's boundary wall
        payload, _ = submit(engine, env)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["reason"], "blocked_target")
        self.assertEqual(engine._teleport_seq, {})
        self.assertAlmostEqual(position(engine)[1], 110.0, places=3)

    async def test_legacy_worlds_reject_portals_and_never_show_teleport_seq(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        env = claim(engine, 600.0, 450.0)
        payload, _ = submit(engine, env)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["reason"], "unknown_portal")
        self.assertTrue(all("teleport_seq" not in a for a in engine._frame_payload["agents"]))

    async def test_the_fixture_interior_portal_returns_to_the_primary_spawn(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        register_map_file(INTERIOR, origin=[300.0, 0.0], base_dir=FIXTURES, primary=False, world="example_smith")
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        engine = backend.engine
        env = claim(engine, 348.0, 66.0)  # inside the interior, near its exit door anchor (348, 70)
        payload, _ = submit(engine, env, portal_id="example_smith_interior:portal_out")
        engine.step()
        result = engine.command_inbox.result(payload["command_id"])
        self.assertEqual((result["status"], result["to_map"], result["position"]), ("applied", "example_smith", [8.0, 32.0]))


class PortalHttpTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1")

    async def test_post_then_poll(self):
        engine = await real_world()
        env = claim(engine, 128.0, 110.0)
        command_id = str(uuid.uuid4())
        body = {**env, "command_id": command_id, "portal_id": PORTAL}
        async with self.client() as client:
            refused = await client.post("/control/portal", json=body)
            self.assertEqual(refused.status_code, 401)
            response = await client.post("/control/portal", json=body, headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "received")
            self.assertEqual((await client.get(f"/commands/{command_id}")).json()["status"], "received")
            engine.step()
            done = (await client.get(f"/commands/{command_id}")).json()
            self.assertEqual((done["status"], done["to_map"], done["teleport_seq"]), ("applied", "smith_interior", 1))
            bad = await client.post("/control/portal", json={**body, "command_id": str(uuid.uuid4()), "world_epoch": "x"},
                                    headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual((bad.status_code, bad.json()["reason"]), (400, "stale_world_epoch"))


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        DISPATCH.clear()

    def tearDown(self):
        DISPATCH.clear()

    def test_default_registry_routes_portal_equip_transfer_and_falls_back_to_inventory(self):
        from simulation.inventory_commands import execute as inventory_execute
        from simulation.portal_commands import execute as portal_execute
        self.assertIs(DISPATCH.executors["equip"], inventory_execute)
        self.assertIs(DISPATCH.executors["transfer"], inventory_execute)
        self.assertIs(DISPATCH.executors["portal"], portal_execute)
        self.assertIs(DISPATCH.default_executor, inventory_execute)
        user_hooks = [n for hooks in (DISPATCH.step_hooks, DISPATCH.post_step_hooks, DISPATCH.genesis_hooks) for n, _ in hooks
                      if n not in DISPATCH.builtin_names]
        self.assertEqual(user_hooks, [])  # nothing but the game's own builtin hooks

    def test_custom_executors_and_a_dispatcher_without_default(self):
        d = Dispatcher()
        self.assertEqual(d.execute(None, "x", {}), {"ok": False, "reason": "unknown_action"})
        d.register_executor("x", lambda engine, action, payload: {"ok": True, "echo": (action, payload)})
        self.assertEqual(d.execute(None, "x", {"a": 1}), {"ok": True, "echo": ("x", {"a": 1})})
        with self.assertRaises(ValueError):
            d.register_executor("", lambda *a: None)
        with self.assertRaises(ValueError):
            d.register_executor("y", "not callable")

    def test_hooks_run_in_order_and_failures_are_logged_not_swallowed(self):
        d = Dispatcher()
        calls = []
        d.register_step_hook("first", lambda engine: calls.append(("first", engine)))
        d.register_step_hook("boom", lambda engine: 1 / 0)
        d.register_step_hook("last", lambda engine: calls.append(("last", engine)))
        with self.assertLogs("eden.dispatch", level="ERROR") as logged:
            failures = d.run_step_hooks("E")
        self.assertEqual((failures, calls), (1, [("first", "E"), ("last", "E")]))
        self.assertIn("boom", logged.output[0])
        self.assertIn("ZeroDivisionError", logged.output[0])
        self.assertEqual([(kind, name) for kind, name, _ in d.errors], [("step", "boom")])
        with self.assertRaises(ValueError):
            d.register_step_hook("first", lambda engine: None)  # names are unique

    def test_genesis_hooks_get_the_map_name_and_unregister_works(self):
        d = Dispatcher()
        seen = []
        d.register_genesis_hook("g", lambda engine, name: seen.append((engine, name)))
        d.run_genesis_hooks("E", "map_x")
        d.unregister_hook("g")
        d.run_genesis_hooks("E", "map_y")
        self.assertEqual(seen, [("E", "map_x")])
        self.assertEqual(d.run_step_hooks("E"), 0)

    async def test_step_hooks_run_every_tick_after_the_reconcile_and_genesis_hooks_run_last(self):
        order = []
        DISPATCH.register_genesis_hook("g", lambda engine, name: order.append(("genesis", name, engine.world_loaded, engine.pop_count)))
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        self.assertEqual(order, [("genesis", "playable_village", True, 4)])  # world is fully built when the hook runs
        DISPATCH.register_step_hook("t", lambda eng: order.append(("tick", eng.tick)))
        engine.step()
        engine.step()
        self.assertEqual(order[1:], [("tick", engine.tick - 2), ("tick", engine.tick - 1)])  # tick increments after the hooks

    async def test_a_failing_step_hook_does_not_abort_the_tick(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        DISPATCH.register_step_hook("boom", lambda eng: 1 / 0)
        before = engine.tick
        with self.assertLogs("eden.dispatch", level="ERROR"):
            engine.step()
        self.assertEqual(engine.tick, before + 1)

    async def test_inventory_commands_still_flow_through_the_dispatcher(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = 600.0, 450.0
        claim_result = engine.player_control.claim_target(engine, controller_id="inv", target_kind="human", target_id=engine._human_uid_by_slot[0])
        env = {key: claim_result[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "inv"}
        command_id = str(uuid.uuid4())
        received = engine.command_inbox.submit(engine, "equip", {**env, "command_id": command_id, "item_id": "nothing", "owner_kind": "human",
                                                                 "owner_id": engine._human_uid_by_slot[0]})
        self.assertEqual(received["status"], "received")
        engine.step()
        result = engine.command_inbox.result(command_id)
        self.assertEqual((result["status"], result["reason"]), ("rejected", "item_not_equippable"))


if __name__ == "__main__":
    unittest.main()
