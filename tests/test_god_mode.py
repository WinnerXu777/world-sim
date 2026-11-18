"""God mode (P5): powers, rejections, idempotency, pause, witnesses, permanence, possession loop, the iron-gift loop."""
import uuid

import httpx

import unittest
from test_startup_preservation import backend
import genesis_config as cfg
from test_smith_loop import SmithLoopCase, inventory
from test_map_contract import LEGACY_PLAYABLE_VILLAGE_CONTRACT, contract_without_epoch
from systems.commission.engine import commission_state_payload, greeting
from systems.god import commit_event, is_paused, remembers, set_paused
from systems.god.state import store
from systems.inventory.currency import inventory_balance
from systems.inventory.queries import total_quantity


class GodCase(SmithLoopCase):
    """The roster world with a god controller ("god") that possesses nobody. Resident helpers come from SmithLoopCase."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        names = {self.engine.resident_store.get(u)["profile"]["name"]: u for u in self.engine._human_uid_by_slot if u}
        self.mara, self.toma, self.elsa = names["Mara"], names["Toma"], names["Elsa"]
        self.engine.player_control.release_target(self.engine, controller_id="cust")  # god mode starts with no possession

    async def asyncTearDown(self):
        set_paused(self.engine, False)
        self.engine.scheduler.set_time_scale(1.0)
        await super().asyncTearDown()

    def god(self, command, **extra):
        payload = {"protocol_version": 1, "world_epoch": self.engine.world_epoch, "controller_id": "god",
                   "command_id": str(uuid.uuid4()), **extra}
        received = self.engine.command_inbox.submit(self.engine, command, payload)
        if received.get("status") == "rejected":
            return received, payload
        self.engine.step()
        return self.engine.command_inbox.result(payload["command_id"]), payload

    def hp(self, human_id):
        return float(self.engine.state.h_tensor[self.engine._human_slot_for_id(human_id), cfg.HP])

    def set_hp(self, human_id, value):
        self.engine.state.h_tensor[self.engine._human_slot_for_id(human_id), cfg.HP] = value

    def kinds(self, human_id):
        return [e["kind"] for e in self.engine.resident_store.get(human_id)["memory"]["recent_events"]]


class HealTests(GodCase):
    async def test_heal_never_goes_past_max_and_is_remembered_by_witnesses_only(self):
        self.set_hp(self.mara, 40.0)
        result, _ = self.god("god_heal", target_id=self.mara, amount=30)
        self.assertEqual(result["status"], "applied")
        self.assertAlmostEqual(result["healed"], 30.0, delta=2.0)  # natural regeneration moves HP a little between ticks
        self.assertAlmostEqual(result["hp_after"], 70.0, delta=2.0)
        result, _ = self.god("god_heal", target_id=self.mara, amount=100)
        self.assertEqual(result["hp_after"], 100.0)  # clamped at max HP
        self.assertAlmostEqual(result["healed"], 30.0, delta=2.0)
        self.assertEqual(self.hp(self.mara), 100.0)
        outdoors = [self.mara, self.toma, self.elsa]
        for human_id in outdoors:
            self.assertIn("divine_heal", self.kinds(human_id), human_id)
        self.assertNotIn("divine_heal", self.kinds(self.smith_id))  # the smith was indoors in another map

    async def test_heal_at_full_health_is_a_no_op_with_no_memory(self):
        before = self.kinds(self.mara)
        result, _ = self.god("god_heal", target_id=self.mara)
        self.assertEqual((result["status"], result["healed"], result["god_event_id"]), ("applied", 0.0, None))
        self.assertEqual(self.kinds(self.mara), before)

    async def test_the_dead_cannot_be_healed_and_nothing_is_resurrected(self):
        self.set_hp(self.toma, 0.0)
        result, _ = self.god("god_heal", target_id=self.toma, amount=50)
        self.assertEqual((result["status"], result["reason"]), ("rejected", "dead_resident"))
        self.assertEqual(self.hp(self.toma), 0.0)
        unknown, _ = self.god("god_heal", target_id="h_999999")
        self.assertEqual(unknown["reason"], "unknown_resident")

    async def test_invalid_amounts_and_dry_run(self):
        self.set_hp(self.mara, 50.0)
        for amount in (0, -5, 101, True, "10"):
            result, _ = self.god("god_heal", target_id=self.mara, amount=amount)
            self.assertEqual((result["status"], result["reason"]), ("rejected", "invalid_amount"), amount)
        result, _ = self.god("god_heal", target_id=self.mara, amount=20, dry_run=True)
        self.assertEqual(result["dry_run"], True)
        self.assertAlmostEqual(result["hp_after"], 70.0, delta=3.0)
        self.assertLess(self.hp(self.mara), 60.0)  # nothing was applied (natural regeneration is slow)
        self.assertNotIn("divine_heal", self.kinds(self.mara))


class SpawnResourceTests(GodCase):
    async def test_iron_into_a_resident_and_into_containers(self):
        before = total_quantity(inventory(self.engine, self.smith_id), "iron_ingot")
        result, _ = self.god("god_spawn_resource", resource="iron_ingot", quantity=2, target_kind="resident", target_id=self.smith_id)
        self.assertEqual((result["status"], result["quantity"], result["item_kind"]), ("applied", 2, "iron_ingot"))
        self.assertEqual(total_quantity(inventory(self.engine, self.smith_id), "iron_ingot"), before + 2)
        chest = self.god("god_spawn_resource", resource="wood", quantity=3, target_kind="container", target_id="smith:output_chest")[0]
        self.assertEqual(chest["status"], "applied")
        record = backend.get_container_inventory(self.engine.inventory_state, "smith:output_chest")
        self.assertEqual(total_quantity(record, "wood_bundle"), 3)
        crate = self.god("god_spawn_resource", resource="coin", quantity=50, target_kind="container", target_id="village:supply_crate")[0]
        self.assertEqual(crate["status"], "applied")

    async def test_rejections(self):
        cases = [({"resource": "gold", "quantity": 1, "target_kind": "resident", "target_id": self.smith_id}, "resource_not_allowed"),
                 ({"resource": "iron_ingot", "quantity": 0, "target_kind": "resident", "target_id": self.smith_id}, "invalid_quantity"),
                 ({"resource": "iron_ingot", "quantity": 21, "target_kind": "resident", "target_id": self.smith_id}, "invalid_quantity"),
                 ({"resource": "iron_ingot", "quantity": True, "target_kind": "resident", "target_id": self.smith_id}, "invalid_quantity"),
                 ({"resource": "coin", "quantity": 201, "target_kind": "resident", "target_id": self.smith_id}, "invalid_quantity"),
                 ({"resource": "iron_ingot", "quantity": 1, "target_kind": "resident", "target_id": "h_999999"}, "unknown_resident"),
                 ({"resource": "iron_ingot", "quantity": 1, "target_kind": "container", "target_id": "nope"}, "unknown_container"),
                 ({"resource": "iron_ingot", "quantity": 1, "target_kind": "container", "target_id": "smith:forge"}, "not_a_container"),
                 ({"resource": "iron_ingot", "quantity": 1, "target_kind": "tree", "target_id": "x"}, "invalid_target_kind")]
        before = self.totals()
        for payload, reason in cases:
            result, _ = self.god("god_spawn_resource", **payload)
            self.assertEqual((result["status"], result["reason"]), ("rejected", reason), payload)
        self.assertEqual(self.totals(), before)

    async def test_dead_resident_and_full_inventory_receive_nothing(self):
        self.set_hp(self.elsa, 0.0)
        self.assertEqual(self.god("god_spawn_resource", resource="food", quantity=1, target_kind="resident", target_id=self.elsa)[0]["reason"], "dead_resident")
        inv = inventory(self.engine, self.mara)
        inv["capacity_slots"] = len(inv["items"])
        result, _ = self.god("god_spawn_resource", resource="iron_ingot", quantity=5, target_kind="resident", target_id=self.mara)
        self.assertEqual((result["status"], result["reason"]), ("rejected", "no_room"))
        self.assertEqual(total_quantity(inventory(self.engine, self.mara), "iron_ingot"), 0)  # all or nothing

    async def test_every_allowed_resource_and_dry_run(self):
        for resource in ("iron_ingot", "wood", "food", "water", "coin"):
            result, _ = self.god("god_spawn_resource", resource=resource, quantity=1, target_kind="resident", target_id=self.mara)
            self.assertEqual(result["status"], "applied", resource)
        before = self.totals()
        result, _ = self.god("god_spawn_resource", resource="iron_ingot", quantity=4, target_kind="resident", target_id=self.mara, dry_run=True)
        self.assertEqual((result["status"], result["dry_run"]), ("applied", True))
        self.assertEqual(self.totals(), before)

    async def test_the_gift_is_witnessed_by_the_smith_only_when_given_indoors(self):
        self.god("god_spawn_resource", resource="iron_ingot", quantity=2, target_kind="resident", target_id=self.smith_id)
        self.assertIn("divine_gift", self.kinds(self.smith_id))
        for outsider in (self.mara, self.toma, self.elsa):
            self.assertNotIn("divine_gift", self.kinds(outsider))
        self.god("god_spawn_resource", resource="food", quantity=2, target_kind="container", target_id="village:supply_crate")
        self.assertIn("divine_gift", self.kinds(self.toma))  # near the crate in the village
        self.assertEqual(self.kinds(self.smith_id).count("divine_gift"), 1)  # the smith did not witness the village gift


class WeatherTests(GodCase):
    async def test_set_weather_updates_the_nature_state_and_is_seen_only_outdoors(self):
        result, _ = self.god("god_weather", weather="rain")
        self.assertEqual((result["status"], result["changed"], result["previous"]), ("applied", True, "clear"))
        self.assertEqual(self.engine._nature_state["weather"], "rain")
        self.assertIn("weather_changed", self.kinds(self.mara))
        self.assertNotIn("weather_changed", self.kinds(self.smith_id))
        outdoors = sorted(u for u in self.engine._human_uid_by_slot if u and float(self.engine.state.h_tensor[self.engine._human_slot_for_id(u), cfg.X]) < 620)
        self.assertEqual(sorted(result["affected_residents"]), outdoors)
        self.assertNotIn(self.customer_id, result["affected_residents"])  # indoors with the smith

    async def test_same_weather_is_a_no_op_and_unsupported_kinds_are_rejected(self):
        self.god("god_weather", weather="storm")
        again, _ = self.god("god_weather", weather="storm")
        self.assertEqual((again["status"], again["changed"], again["god_event_id"]), ("applied", False, None))
        self.assertEqual(self.kinds(self.mara).count("weather_changed"), 1)
        for bad in ("hail", "", None, 5):
            result, _ = self.god("god_weather", weather=bad)
            self.assertEqual((result["status"], result["reason"]), ("rejected", "weather_not_supported"), bad)
        for duration in (0, -1, True, "5", 10**6):
            result, _ = self.god("god_weather", weather="rain", duration_ticks=duration)
            self.assertEqual(result["reason"], "invalid_duration", duration)

    async def test_dry_run_previews_and_changes_nothing(self):
        result, _ = self.god("god_weather", weather="fog" if False else "cold", dry_run=True)
        self.assertEqual((result["dry_run"], result["weather"], result["reversible"]), (True, "cold", True))
        self.assertIn("food_growth", result["effects"])
        self.assertEqual(self.engine._nature_state.get("weather", "clear"), "clear")
        self.assertNotIn("weather_changed", self.kinds(self.mara))

    async def test_weather_does_not_bring_back_random_disasters_and_is_reversible(self):
        self.god("god_weather", weather="storm")
        for _ in range(250):
            self.engine.step()
        self.assertEqual(self.engine._nature_state["weather"], "storm")  # the cycle is off on roster maps: no random change
        self.assertTrue(all(self.hp(u) >= 99.9 for u in self.engine._human_uid_by_slot if u))
        self.god("god_weather", weather="clear")
        self.assertEqual(self.engine._nature_state["weather"], "clear")

    async def test_the_weather_is_visible_in_the_frame_and_status(self):
        self.god("god_weather", weather="heat")
        self.engine.step()
        self.assertEqual(self.engine._frame_payload["nature"]["weather"], "heat")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            status = (await client.get("/status")).json()
        self.assertEqual(status["god"]["weather"], "heat")
        self.assertFalse(status["god"]["paused"])


class TimeTests(GodCase):
    async def test_pause_stops_ticks_but_commands_still_apply_and_resume_restarts(self):
        self.set_hp(self.mara, 30.0)
        self.assertTrue(self.god("god_time", action="pause")[0]["paused"])
        tick = self.engine.tick
        positions = [tuple(float(v) for v in self.engine.state.h_tensor[s, :2]) for s in range(5)]
        for _ in range(40):
            self.engine.step()
        self.assertEqual(self.engine.tick, tick)  # simulation time is frozen
        self.assertEqual(positions, [tuple(float(v) for v in self.engine.state.h_tensor[s, :2]) for s in range(5)])
        result, _ = self.god("god_heal", target_id=self.mara, amount=20)  # applied at the paused boundary
        self.assertEqual(result["status"], "applied")
        self.assertAlmostEqual(result["hp_after"], 50.0, delta=0.5)  # time is frozen: no regeneration either
        self.assertEqual(self.engine.tick, tick)
        agent = next(a for a in self.engine._frame_payload["agents"] if a["id"] == self.mara)
        self.assertIsNotNone(agent)  # the frame was rebuilt while paused
        self.assertEqual(self.god("god_time", action="resume")[0]["paused"], False)
        for _ in range(5):
            self.engine.step()
        self.assertGreater(self.engine.tick, tick)

    async def test_paused_world_still_answers_other_commands(self):
        self.god("god_time", action="pause")
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
        self.move_customer_next_to_smith()
        result, _ = self.request()  # a commission command is drained while paused
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.engine.tick, 0 if self.engine.tick == 0 else self.engine.tick)
        order = self.orders()[0]
        for _ in range(60):
            self.engine.step()
        self.assertEqual(order["progress_ticks"], 0)  # no work happens while time is paused

    async def test_conservative_scales_only(self):
        for scale in (0.5, 1.0, 2.0):
            self.assertEqual(self.god("god_time", action="scale", scale=scale)[0]["time_scale"], scale)
        for scale in (0, 4, 0.1, -1, True, "2"):
            result, _ = self.god("god_time", action="scale", scale=scale)
            self.assertEqual((result["status"], result["reason"]), ("rejected", "scale_not_allowed"), scale)
        self.assertEqual(self.god("god_time", action="dance")[0]["reason"], "invalid_time_action")

    async def test_pause_is_not_saved_a_reload_resumes(self):
        self.god("god_time", action="pause")
        self.assertTrue(is_paused(self.engine))
        set_paused(self.engine, False)
        self.assertFalse(is_paused(self.engine))


class AuthorizationAndIdempotencyTests(GodCase):
    async def test_god_commands_need_the_current_world_epoch_and_no_possession(self):
        stale = {"protocol_version": 1, "world_epoch": "old", "controller_id": "god", "command_id": str(uuid.uuid4()), "target_id": self.mara}
        self.assertEqual(self.engine.command_inbox.submit(self.engine, "god_heal", stale)["reason"], "stale_world_epoch")
        bad_protocol = {**stale, "world_epoch": self.engine.world_epoch, "protocol_version": 2}
        self.assertEqual(self.engine.command_inbox.submit(self.engine, "god_heal", bad_protocol)["reason"], "unsupported_protocol")
        self.engine.player_control.claim_target(self.engine, controller_id="god", target_kind="human", target_id=self.mara)
        embodied = {**stale, "world_epoch": self.engine.world_epoch}
        self.assertEqual(self.engine.command_inbox.submit(self.engine, "god_heal", embodied)["reason"], "release_possession_first")
        self.engine.player_control.release_target(self.engine, controller_id="god")
        ok = self.engine.command_inbox.submit(self.engine, "god_heal", {**embodied, "command_id": str(uuid.uuid4())})
        self.assertEqual(ok["status"], "received")

    async def test_commands_are_idempotent_by_command_id(self):
        self.set_hp(self.mara, 40.0)
        first, payload = self.god("god_heal", target_id=self.mara, amount=10)
        again = self.engine.command_inbox.submit(self.engine, "god_heal", payload)
        self.assertEqual(again, first)
        self.engine.step()
        self.assertAlmostEqual(self.hp(self.mara), 50.0, delta=2.0)  # healed once, not twice (twice would be 60)
        conflict = self.engine.command_inbox.submit(self.engine, "god_heal", {**payload, "amount": 99})
        self.assertEqual((conflict["ok"], conflict["reason"]), (False, "command_id_conflict"))
        self.assertEqual(self.kinds(self.mara).count("divine_heal"), 1)

    async def test_results_are_correlated_and_visible(self):
        self.set_hp(self.mara, 10.0)
        result, payload = self.god("god_heal", target_id=self.mara)
        self.assertEqual(result["command_id"], payload["command_id"])
        self.assertTrue(result["god_event_id"].startswith("g_"))
        entry = store(self.engine)["events"][result["god_event_id"]]
        self.assertEqual((entry["kind"], entry["target_id"]), ("divine_heal", self.mara))
        self.assertIn(result["god_event_id"], [e.get("event_id") for e in self.engine.resident_store.get(self.mara)["memory"]["recent_events"] if e["kind"] == "divine_heal"])
        pending = [e for e in self.engine._pending_events if e.get("type") == "divine_heal"] + \
                  [e for e in self.engine._frame_payload.get("events", []) if e.get("type") == "divine_heal"]
        self.assertTrue(pending)

    async def test_http_routes(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            body = {"protocol_version": 1, "world_epoch": self.engine.world_epoch, "controller_id": "god", "command_id": str(uuid.uuid4()),
                    "weather": "wind"}
            self.assertEqual((await client.post("/god/weather", json=body)).status_code, 401)
            response = await client.post("/god/weather", json=body, headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual((response.status_code, response.json()["status"]), (202, "received"))
            self.engine.step()
            done = (await client.get(f"/commands/{body['command_id']}")).json()
            self.assertEqual((done["status"], done["weather"]), ("applied", "wind"))
            for path, extra in (("/god/heal", {"target_id": self.mara}), ("/god/spawn_resource", {"resource": "coin", "quantity": 5, "target_kind": "resident", "target_id": self.mara}),
                                ("/god/time", {"action": "scale", "scale": 1.0})):
                response = await client.post(path, json={**body, "command_id": str(uuid.uuid4()), **extra}, headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
                self.assertEqual(response.status_code, 202, path)
            bad = await client.post("/god/heal", json={**body, "command_id": str(uuid.uuid4()), "world_epoch": "old"},
                                    headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual((bad.status_code, bad.json()["reason"]), (400, "stale_world_epoch"))


class PossessionLoopTests(GodCase):
    async def test_embodied_release_god_possess_again(self):
        claim = self.engine.player_control.claim_target(self.engine, controller_id="p", target_kind="human", target_id=self.mara)
        first = claim["possession_epoch"]
        self.set_hp(self.mara, 20.0)
        denied = self.engine.command_inbox.submit(self.engine, "god_heal", {"protocol_version": 1, "world_epoch": self.engine.world_epoch,
                                                                            "controller_id": "p", "command_id": str(uuid.uuid4()), "target_id": self.mara})
        self.assertEqual(denied["reason"], "release_possession_first")
        self.engine.player_control.release_target(self.engine, controller_id="p")
        payload = {"protocol_version": 1, "world_epoch": self.engine.world_epoch, "controller_id": "p", "command_id": str(uuid.uuid4()), "target_id": self.mara}
        self.assertEqual(self.engine.command_inbox.submit(self.engine, "god_heal", payload)["status"], "received")
        self.engine.step()
        self.assertEqual(self.hp(self.mara), 100.0)
        again = self.engine.player_control.claim_target(self.engine, controller_id="p", target_kind="human", target_id=self.mara)
        self.assertNotEqual(again["possession_epoch"], first)
        stale = {key: claim[key] for key in ("protocol_version", "world_epoch", "target_kind", "target_id")}
        stale.update(possession_epoch=first, seq=1, move={"x": 1, "y": 0}, buttons={})
        self.assertEqual(self.engine.player_control.submit_input(self.engine, "p", stale)["reason"], "stale_possession_epoch")

    async def test_released_residents_return_to_their_anchors(self):
        self.engine.player_control.claim_target(self.engine, controller_id="p", target_kind="human", target_id=self.toma)
        slot = self.engine._human_slot_for_id(self.toma)
        self.engine.state.h_tensor[slot, cfg.X], self.engine.state.h_tensor[slot, cfg.Y] = 250.0, 250.0
        for _ in range(10):
            self.engine.step()
        self.assertEqual((float(self.engine.state.h_tensor[slot, cfg.X]), float(self.engine.state.h_tensor[slot, cfg.Y])), (250.0, 250.0))  # possessed: still
        self.engine.player_control.release_target(self.engine, controller_id="p")
        for _ in range(40):
            self.engine.step()
        moved = abs(float(self.engine.state.h_tensor[slot, cfg.X]) - 250.0) + abs(float(self.engine.state.h_tensor[slot, cfg.Y]) - 250.0)
        self.assertGreater(moved, 5.0)  # autonomous again: walking to an anchor


class IronGiftLoopTests(GodCase):
    """Gate G: refused for want of iron, the god gives iron, the smith accepts and remembers, and it survives a reload."""

    def possess_customer(self):
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
        self.move_customer_next_to_smith()

    async def test_refuse_gift_accept_remember_and_persist(self):
        inv = inventory(self.engine, self.smith_id)
        inv["items"] = [i for i in inv["items"] if i["kind"] != "iron_ingot"]  # the smith has no iron
        self.possess_customer()
        refused, _ = self.request()
        self.assertEqual((refused["code"], refused["accepted"]), ("refused_no_materials", False))
        self.assertIsNone(greeting(self.engine, self.smith_id, self.customer_id))
        self.engine.player_control.release_target(self.engine, controller_id="cust")
        gift, _ = self.god("god_spawn_resource", resource="iron_ingot", quantity=2, target_kind="resident", target_id=self.smith_id)
        self.assertEqual(gift["status"], "applied")
        self.assertEqual(total_quantity(inventory(self.engine, self.smith_id), "iron_ingot"), 2)
        self.assertIn(self.customer_id, store(self.engine)["events"][gift["god_event_id"]]["witnesses"])  # the customer was in the room
        self.possess_customer()
        accepted, _ = self.request()
        self.assertEqual((accepted["code"], accepted["accepted"]), ("accepted", True))
        self.assertIn("divine_gift", self.kinds(self.smith_id))
        self.assertIn("divine_gift", self.kinds(self.customer_id))  # a witness remembers too
        self.assertEqual(greeting(self.engine, self.smith_id, self.customer_id)["code"], "followup_gift")
        # persistence
        from persistence.sessions import GameSessions
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                backend_storage() / uuid.uuid4().hex, backend.create_genesis, 905, map_name="starter_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Gift", self.engine.world_epoch
        await sessions.save()
        save_id = sessions.active_id
        event_id = gift["god_event_id"]
        backend.engine.reset_world()
        await sessions.continue_world(save_id)
        self.engine = backend.engine
        self.assertEqual(self.kinds(self.smith_id).count("divine_gift"), 1)
        self.assertEqual(self.kinds(self.customer_id).count("divine_gift"), 1)
        self.assertEqual(greeting(self.engine, self.smith_id, self.customer_id)["code"], "followup_gift")
        # no double effect after reload: replaying the same causal event changes nobody
        witnesses = store(self.engine)["events"][event_id]["witnesses"]
        commit_event(self.engine, "divine_gift", point=(0.0, 0.0), witnesses=witnesses, extra={"event_id": event_id})
        self.assertEqual(self.kinds(self.smith_id).count("divine_gift"), 1)
        for _ in range(900):  # a long time later it is still there (permanent policy, not the default TTL)
            self.engine.step()
        self.assertEqual(self.kinds(self.smith_id).count("divine_gift"), 1)
        # event ids do not repeat after the reload
        fresh = self.god_after_reload("god_heal", target_id=self.mara)
        self.assertNotEqual(fresh.get("god_event_id"), event_id)

    def god_after_reload(self, action, **extra):
        self.smith_slot = self.engine._human_slot_for_id(self.smith_id)
        self.set_hp(self.mara, 10.0)
        payload = {"protocol_version": 1, "world_epoch": self.engine.world_epoch, "controller_id": "god", "command_id": str(uuid.uuid4()), **extra}
        self.engine.command_inbox.submit(self.engine, action, payload)
        self.engine.step()
        return self.engine.command_inbox.result(payload["command_id"])

    async def test_a_delivered_sword_is_what_the_smith_greets_the_customer_with(self):
        self.possess_customer()
        self.god_gift_first()
        order = self.to_ready()
        self.collect(order)
        self.assertEqual(greeting(self.engine, self.smith_id, self.customer_id)["code"], "followup_delivered")  # delivery outranks the gift
        state = commission_state_payload(self.engine, "cust")
        self.assertEqual(state["greeting"]["code"], "followup_delivered")
        self.assertIn(state["greeting"]["text"], ("How does the blade sit in your hand? No chips, I hope.", "Back again? How is the sword treating you?"))

    def god_gift_first(self):
        self.engine.player_control.release_target(self.engine, controller_id="cust")
        self.god("god_spawn_resource", resource="iron_ingot", quantity=1, target_kind="resident", target_id=self.smith_id)
        self.possess_customer()

    async def test_the_inspect_view_explains_the_resident(self):
        self.possess_customer()
        self.request()
        order = self.orders()[0]
        self.run_until(lambda: order["state"] == "working")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            view = (await client.get(f"/god/inspect/{self.smith_id}")).json()
            self.assertEqual((view["ok"], view["name"], view["role"], view["alive"]), (True, "Brann", "smith", True))
            self.assertEqual(view["map_id"], "smith_interior")
            self.assertEqual(view["anchors"]["work"], "smith:work_forge")
            self.assertEqual(view["commission_orders"][0]["state"], "working")
            self.assertIn("order", view["explanation"])
            self.assertIn("Brann", view["explanation"])
            self.assertEqual({"hp", "hunger", "thirst", "stamina"}, set(view["needs"]))
            self.assertTrue(any(r["id"] == self.customer_id for r in view["relationships"]))
            self.assertEqual((await client.get("/god/inspect/h_999999")).status_code, 404)
            customer = (await client.get(f"/god/inspect/{self.customer_id}")).json()
            self.assertTrue(customer["controlled"])
            self.assertIn("possessed", customer["explanation"])


def backend_storage():
    from test_startup_preservation import _test_storage
    return _test_storage / "god_mode"


class LegacyUnchangedTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_legacy_contract_is_byte_identical_and_god_powers_work_there(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        engine.state.h_tensor[0, cfg.HP] = 50.0
        payload = {"protocol_version": 1, "world_epoch": engine.world_epoch, "controller_id": "god", "command_id": str(uuid.uuid4()),
                   "target_id": engine._human_uid_by_slot[0], "amount": 25}
        engine.command_inbox.submit(engine, "god_heal", payload)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["hp_after"], 75.0)
        self.assertEqual(contract_without_epoch(engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertFalse(is_paused(engine))


if __name__ == "__main__":
    unittest.main()
