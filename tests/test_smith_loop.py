"""The smith loop on the real maps and a real Engine.step loop: request -> decide -> reserve -> work -> deliver once ->
remembered after reload, plus the failure and save/restore matrix. Work time is shortened through the one constant."""
from authored_village import MAP_FILES, load_village_maps
import json
import os
import unittest
import uuid
from pathlib import Path

import httpx

from test_startup_preservation import backend, _test_storage
import genesis_config as cfg
from test_map_contract import AsyncRegistryIsolation
from persistence.sessions import GameSessions
from systems.commission.config import COMMISSION_CONFIG
from systems.commission.engine import commission_open_between, env_for, find_smith, forge_entity_id
from systems.commission.escrow import escrow_contents
from systems.inventory.currency import inventory_balance
from systems.inventory.queries import total_quantity
from systems.movement.map_contract import load_from_environment

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


def inventory(engine, human_id):
    return backend.get_owner_inventory(engine.inventory_state, "human", human_id)


class SmithLoopCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._config = dict(COMMISSION_CONFIG)
        COMMISSION_CONFIG.update(work_ticks_per_time_unit=20, forge_wait_ticks=30)  # 30 work ticks instead of 900
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.smith_id, self.smith = find_smith(self.engine)
        self.customer_id = next(u for u in self.engine._human_uid_by_slot if u and (self.engine.resident_store.get(u)["roster"]["key"] == "iven"))
        self.customer_slot = self.engine._human_slot_for_id(self.customer_id)
        self.smith_slot = self.engine._human_slot_for_id(self.smith_id)
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
        self.move_customer_next_to_smith()

    async def asyncTearDown(self):
        COMMISSION_CONFIG.clear()
        COMMISSION_CONFIG.update(self._config)
        await super().asyncTearDown()

    # helpers ---------------------------------------------------------------
    def smith_pos(self):
        h = self.engine.state.h_tensor
        return float(h[self.smith_slot, cfg.X]), float(h[self.smith_slot, cfg.Y])

    def move_customer_next_to_smith(self, dx=9.0, dy=3.0):
        x, y = self.smith_pos()
        self.engine.state.h_tensor[self.customer_slot, cfg.X], self.engine.state.h_tensor[self.customer_slot, cfg.Y] = x + dx, y + dy

    def command(self, action, **extra):
        payload = {**self.env, "command_id": str(uuid.uuid4()), **extra}
        received = self.engine.command_inbox.submit(self.engine, action, payload)
        self.assertEqual(received["status"], "received", received)  # rejected here = authorization failed
        self.engine.step()
        return self.engine.command_inbox.result(payload["command_id"]), payload

    def request(self):
        return self.command("commission_request")

    def orders(self):
        return list(self.engine.inventory_state.get("work_orders", {}).get("orders", {}).values())

    def run_until(self, predicate, limit=900):
        for _ in range(limit):
            if predicate():
                return True
            self.engine.step()
        return predicate()

    def to_ready(self):
        result, _ = self.request()
        self.assertEqual(result["code"], "accepted", result)
        order = self.orders()[0]
        self.assertTrue(self.run_until(lambda: order["state"] == "ready"), order["state"])
        return order

    def collect(self, order):
        self.move_customer_next_to_smith(dx=6.0, dy=2.0)
        return self.command("commission_collect", order_id=order["order_id"])

    def totals(self):
        """Conserved kinds only (the controlled customer's first-sync rations and bandage are not part of the loop)."""
        out = {}
        for record in self.engine.inventory_state["inventories"].values():
            for item in record["items"]:
                if item["kind"] in ("iron_ingot", "wood_bundle", "coin", "sword"):
                    out[item["kind"]] = out.get(item["kind"], 0) + item["quantity"]
        return out

    def events(self, human_id, kind):
        return [e for e in self.engine.resident_store.get(human_id)["memory"]["recent_events"] if e.get("kind") == kind]


class HappyPathTests(SmithLoopCase):
    async def test_request_accept_work_deliver_once_and_remembered(self):
        start = self.totals()
        result, _ = self.request()
        self.assertEqual((result["status"], result["code"], result["accepted"], result["state"]), ("applied", "accepted", True, "reserved"))
        self.assertIn(result["line"], __import__("systems.commission.lines", fromlist=["x"]).LINES["smith"]["accepted"])
        order = self.orders()[0]
        self.assertEqual(escrow_contents(__import__("systems.commission", fromlist=["x"]).CommissionContext(state=self.engine.inventory_state), order)["coin"], 30)
        self.assertEqual(inventory_balance(inventory(self.engine, self.customer_id)), 10)
        self.assertTrue(self.run_until(lambda: order["state"] == "working"))
        self.assertTrue(self.run_until(lambda: order["state"] == "ready"))
        self.assertGreaterEqual(order["progress_ticks"], order["work_ticks"])
        work = __import__("systems.roster.driver", fromlist=["x"]).runtime(self.engine).at_anchor.get(self.smith_id)
        self.assertEqual(work, "work")  # the work happened at the forge anchor
        collected, _ = self.collect(order)
        self.assertEqual((collected["status"], collected["state"], collected["duplicate"]), ("applied", "delivered", False))
        end = self.totals()
        self.assertEqual(end["sword"], 1)
        self.assertEqual((end["iron_ingot"], end["wood_bundle"]), (start["iron_ingot"] - 2, start["wood_bundle"] - 1))
        self.assertEqual(end["coin"], start["coin"])
        self.assertEqual(total_quantity(inventory(self.engine, self.customer_id), "sword"), 1)
        self.assertEqual(inventory_balance(inventory(self.engine, self.smith_id)), 20 + 30)
        again, _ = self.collect(order)
        self.assertEqual((again["status"], again["duplicate"]), ("applied", True))
        self.assertEqual(self.totals()["sword"], 1)  # never a second sword
        for human_id in (self.smith_id, self.customer_id):
            kinds = [e["kind"] for e in self.engine.resident_store.get(human_id)["memory"]["recent_events"]]
            for kind in ("commission_accepted", "commission_ready", "commission_delivered"):
                self.assertEqual(kinds.count(kind), 1, (human_id, kind))
        relation = self.engine.resident_store.get(self.smith_id)["relationships"][self.customer_id]
        self.assertGreater(relation["closeness"], 0.1)
        self.assertIn("customer", relation["tags"])
        self.assertTrue(relation["tag_meta"]["customer"].get("permanent") or relation["tag_meta"]["customer"].get("expires_tick") is None)

    async def test_frame_events_and_talk_feed_carry_the_outcomes(self):
        order = self.to_ready()
        self.collect(order)
        types = [e["type"] for e in self.engine._pending_events] + [e["type"] for e in getattr(self.engine, "_frame_payload", {}).get("events", [])]
        self.assertIn("commission_delivered", types)
        lines = [l["text"] for l in self.engine.talk_agent.recent_lines]
        self.assertGreaterEqual(len(lines), 2)  # at least the acceptance and the handover

    async def test_read_model_follows_the_order(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            state = (await client.get("/commission/state", params={"controller_id": "cust"})).json()
            self.assertEqual((state["ok"], state["npc"]["name"], state["orders"]), (True, "Brann", []))
            self.assertEqual([c["id"] for c in state["choices"]], ["request_commission"])
            self.assertTrue(state["choices"][0]["enabled"])
            self.request()
            state = (await client.get("/commission/state", params={"controller_id": "cust"})).json()
            self.assertEqual(state["orders"][0]["state"], "reserved")
            self.assertEqual(state["choices"][0]["reason"], "duplicate_open_order")
            self.assertEqual((await client.get("/commission/state", params={"controller_id": "nobody"})).status_code, 404)

    async def test_http_routes_use_the_command_envelope(self):
        body = {**self.env, "command_id": str(uuid.uuid4())}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            self.assertEqual((await client.post("/commission/request", json=body)).status_code, 401)  # no capability
            response = await client.post("/commission/request", json=body, headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual((response.status_code, response.json()["status"]), (202, "received"))
            self.engine.step()
            done = (await client.get(f"/commands/{body['command_id']}")).json()
            self.assertEqual((done["status"], done["code"]), ("applied", "accepted"))
            stale = await client.post("/commission/request", json={**body, "command_id": str(uuid.uuid4()), "world_epoch": "old"},
                                      headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
            self.assertEqual((stale.status_code, stale.json()["reason"]), (400, "stale_world_epoch"))
            status = (await client.get("/status")).json()
            self.assertEqual(status["decision"]["provider_mode"], "rules")
            self.assertGreaterEqual(status["decision"]["counts"]["requests"], 1)


class RefusalAndRejectionTests(SmithLoopCase):
    async def test_no_iron_is_refused_truthfully_and_nothing_moves(self):
        smith_inv = inventory(self.engine, self.smith_id)
        smith_inv["items"] = [i for i in smith_inv["items"] if i["kind"] != "iron_ingot"]
        before = self.totals()
        result, _ = self.request()
        self.assertEqual((result["status"], result["code"], result["accepted"]), ("applied", "refused_no_materials", False))
        self.assertEqual(self.totals(), before)
        self.assertEqual(self.orders()[0]["state"], "refused")
        self.assertTrue(any("iron" in l["text"].lower() or "stock" in l["text"].lower() for l in self.engine.talk_agent.recent_lines[-1:]))
        self.assertEqual(len(self.events(self.smith_id, "commission_refused")), 1)

    async def test_destroyed_forge_refuses_with_no_forge(self):
        forge = forge_entity_id(self.engine, self.smith)
        self.engine.state.m_tensor[self.engine._entity_uid_by_slot.index(forge), cfg.M_HP] = 0
        result, _ = self.request()
        self.assertEqual(result["code"], "refused_no_forge")

    async def test_customer_without_coin_is_refused(self):
        inv = inventory(self.engine, self.customer_id)
        inv["items"] = [i for i in inv["items"] if i["kind"] != "coin"]
        result, _ = self.request()
        self.assertEqual(result["code"], "refused_cannot_afford")

    async def test_busy_smith_refuses(self):
        COMMISSION_CONFIG["capacity_open_orders"] = 1
        other = next(u for u in self.engine._human_uid_by_slot if u and u not in (self.smith_id, self.customer_id))
        from systems.commission import CommissionContext, submit_request
        from systems.commission.engine import decision_service, env_for as make_env
        ctx = CommissionContext(state=self.engine.inventory_state, tick=self.engine.tick, world_epoch=self.engine.world_epoch)
        submit_request(ctx, other, self.smith_id, "sword", decision_service(self.engine), "c-other", make_env(self.engine, self.smith_id, other))
        result, _ = self.request()
        self.assertEqual(result["code"], "refused_busy")

    async def test_far_customer_and_walled_off_customer_are_rejected_before_any_decision(self):
        x, y = self.smith_pos()
        self.engine.state.h_tensor[self.customer_slot, cfg.X], self.engine.state.h_tensor[self.customer_slot, cfg.Y] = x - 30, y
        result, _ = self.request()
        self.assertEqual((result["status"], result["reason"]), ("rejected", "out_of_range"))
        self.assertEqual(self.orders(), [])
        # in range, but the forge footprint (interior x 16..32, y 20..28 -> world x 636..652) is between them
        h = self.engine.state.h_tensor
        h[self.smith_slot, cfg.X], h[self.smith_slot, cfg.Y] = 644.0, 30.6
        h[self.customer_slot, cfg.X], h[self.customer_slot, cfg.Y] = 644.0, 17.5
        result, _ = self.request()
        self.assertEqual((result["status"], result["reason"]), ("rejected", "blocked"))
        self.assertEqual(self.orders(), [])

    async def test_only_a_controlling_player_can_commission(self):
        self.engine.player_control.release_target(self.engine, controller_id="cust")
        received = self.engine.command_inbox.submit(self.engine, "commission_request", {**self.env, "command_id": str(uuid.uuid4())})
        self.assertFalse(received["ok"])

    async def test_duplicate_requests_and_commands(self):
        first, payload = self.request()
        again = self.engine.command_inbox.submit(self.engine, "commission_request", payload)  # same command id
        self.assertEqual(again, self.engine.command_inbox.result(payload["command_id"]))
        second, _ = self.request()  # a new command id for the same open order
        self.assertEqual((second["status"], second["duplicate"], second["order_id"]), ("applied", True, first["order_id"]))
        self.assertEqual(len(self.orders()), 1)
        self.assertEqual(escrow_contents(__import__("systems.commission", fromlist=["x"]).CommissionContext(state=self.engine.inventory_state), self.orders()[0])["iron_ingot"], 2)


class CancelAndFailureTests(SmithLoopCase):
    async def test_cancel_before_work_refunds_in_full_and_after_work_started_is_refused(self):
        start = self.totals()
        result, _ = self.request()
        order = self.orders()[0]
        canceled, _ = self.command("commission_cancel", order_id=order["order_id"])
        self.assertEqual((canceled["status"], canceled["state"]), ("applied", "canceled"))
        self.assertEqual(self.totals(), start)
        self.assertEqual(inventory_balance(inventory(self.engine, self.customer_id)), 40)
        repeated, _ = self.command("commission_cancel", order_id=order["order_id"])
        self.assertEqual((repeated["status"], repeated["reason"]), ("rejected", "invalid_transition"))
        result, _ = self.request()
        order2 = self.orders()[-1]
        self.assertTrue(self.run_until(lambda: order2["state"] == "working"))
        late, _ = self.command("commission_cancel", order_id=order2["order_id"])
        self.assertEqual((late["status"], late["reason"]), ("rejected", "invalid_transition"))

    async def test_forge_destroyed_mid_work_fails_once_with_refund(self):
        self.request()
        order = self.orders()[0]
        self.assertTrue(self.run_until(lambda: order["state"] == "working"))
        forge = forge_entity_id(self.engine, self.smith)
        self.engine.state.m_tensor[self.engine._entity_uid_by_slot.index(forge), cfg.M_HP] = 0
        self.assertTrue(self.run_until(lambda: order["state"] == "failed", 200))
        self.assertEqual(order["failure_reason"], "forge_unavailable")
        self.assertEqual(inventory_balance(inventory(self.engine, self.customer_id)), 40)  # full refund
        self.assertEqual(total_quantity(inventory(self.engine, self.smith_id), "iron_ingot"), 4)
        for human_id in (self.smith_id, self.customer_id):
            self.assertEqual(len(self.events(human_id, "commission_failed")), 1)
        for _ in range(30):
            self.engine.step()
        self.assertEqual(len(self.events(self.smith_id, "commission_failed")), 1)  # never committed twice

    async def test_smith_dying_fails_the_order(self):
        self.request()
        order = self.orders()[0]
        self.assertTrue(self.run_until(lambda: order["state"] == "working"))
        self.engine.state.h_tensor[self.smith_slot, cfg.HP] = 0.0
        self.assertTrue(self.run_until(lambda: order["state"] == "failed", 60))
        self.assertEqual(order["failure_reason"], "smith_unavailable")
        self.assertEqual(inventory_balance(inventory(self.engine, self.customer_id)), 40)

    async def test_a_full_pack_blocks_collection_until_there_is_room(self):
        order = self.to_ready()
        inv = inventory(self.engine, self.customer_id)
        inv["capacity_slots"] = len(inv["items"])
        collected, _ = self.collect(order)
        self.assertEqual((collected["status"], collected["reason"]), ("rejected", "customer_inventory_full"))
        self.assertEqual(order["state"], "ready")
        inv["capacity_slots"] = 12
        collected, _ = self.collect(order)
        self.assertEqual(collected["status"], "applied")
        self.assertEqual(self.totals()["sword"], 1)

    async def test_collecting_from_across_the_room_is_rejected(self):
        order = self.to_ready()
        x, y = self.smith_pos()
        self.engine.state.h_tensor[self.customer_slot, cfg.X] = x + 40
        result, payload = self.command("commission_collect", order_id=order["order_id"])
        self.assertEqual((result["status"], result["reason"]), ("rejected", "out_of_range"))
        self.assertEqual(order["state"], "ready")


class KeywordTalkTests(SmithLoopCase):
    async def test_keyword_replies_are_suppressed_while_a_commission_is_open(self):
        self.assertFalse(commission_open_between(self.engine, self.smith_id, self.customer_id))
        self.request()
        self.assertTrue(commission_open_between(self.engine, self.smith_id, self.customer_id))
        self.assertTrue(commission_open_between(self.engine, self.customer_id, self.smith_id))
        envelope = {"event": {"listener_id": self.smith_id, "speaker_id": self.customer_id, "utterance": "I will pay you coin for a sword"}}
        self.assertIsNone(self.engine.talk_agent._generate_direct_result(self.engine, envelope))
        order = self.orders()[0]
        self.run_until(lambda: order["state"] == "ready")
        self.collect(order)
        self.assertFalse(commission_open_between(self.engine, self.smith_id, self.customer_id))


class FollowupAndFrameTests(SmithLoopCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # PlayerControlRuntime releases a possession after `possession_timeout` (5 s) of WALL time without input
        # (control_runtime.tick_maintenance). These tests step hundreds of ticks with no commands, which takes ~4 s idle and 16+ s
        # on a loaded machine, so the claim was sometimes released mid-test (line_code() -> None, G-001). Freeze the runtime's
        # injectable clock so the outcome depends on ticks, not on how fast the machine is.
        control = self.engine.player_control
        frozen = control.clock()
        control.clock = lambda: frozen

    def line_code(self):
        from systems.commission.engine import commission_state_payload
        payload = commission_state_payload(self.engine, "cust")
        return payload["line"]["code"] if payload.get("line") else None

    async def test_a_delivered_order_is_greeted_with_the_followup_line_on_a_later_visit(self):
        from systems.commission.lines import LINES
        order = self.to_ready()
        self.collect(order)
        self.assertEqual(self.line_code(), "delivered")  # just handed over
        for _ in range(COMMISSION_CONFIG["followup_after_ticks"] + 20):
            self.engine.step()
        self.assertEqual(self.line_code(), "followup_delivered")
        from systems.commission.engine import commission_state_payload
        text = commission_state_payload(self.engine, "cust")["line"]["text"]
        self.assertIn(text, LINES["smith"]["followup_delivered"])
        self.assertEqual(commission_state_payload(self.engine, "cust")["line"]["text"], text)  # deterministic

    async def test_the_followup_survives_save_and_continue(self):
        order = self.to_ready()
        self.collect(order)
        for _ in range(COMMISSION_CONFIG["followup_after_ticks"] + 20):
            self.engine.step()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                _test_storage / "sf" / uuid.uuid4().hex[:8], backend.create_genesis, 905, map_name="starter_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Followup", self.engine.world_epoch
        await sessions.save()
        save_id = sessions.active_id
        backend.engine.reset_world()
        await sessions.continue_world(save_id)
        self.engine = backend.engine
        self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.assertEqual(self.line_code(), "followup_delivered")

    async def test_roster_residents_publish_their_key_in_the_frame_and_legacy_frames_do_not(self):
        self.engine.step()
        keys = {a["name"]: a.get("roster_key") for a in self.engine._frame_payload["agents"]}
        self.assertEqual(keys, {"Brann": "smith", "Mara": "builder", "Toma": "gatherer", "Iven": "iven", "Elsa": "elsa",
                               "Rhea": "rhea", "Orrin": "orrin", "Nessa": "nessa"})
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        backend.engine.step()
        self.assertTrue(all("roster_key" not in a for a in backend.engine._frame_payload["agents"]))

    async def test_cancel_while_reserved_is_reachable_when_the_smith_is_away_from_the_forge(self):
        self.engine.state.h_tensor[self.smith_slot, cfg.X] = 668.0  # away from the forge anchor (644, 36)
        self.engine.state.h_tensor[self.smith_slot, cfg.Y] = 40.0
        self.move_customer_next_to_smith(dx=-9.0, dy=3.0)
        result, _ = self.request()
        order = self.orders()[0]
        self.assertEqual((result["code"], order["state"]), ("accepted", "reserved"))
        canceled, _ = self.command("commission_cancel", order_id=order["order_id"])
        self.assertEqual((canceled["status"], canceled["state"]), ("applied", "canceled"))


class SaveRestoreMatrixTests(SmithLoopCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                     _test_storage / "smith_loop" / uuid.uuid4().hex, backend.create_genesis, 905, map_name="starter_village")
        self.sessions.active_id, self.sessions.active_name, self.sessions.active_epoch = uuid.uuid4().hex, "Smith", self.engine.world_epoch

    async def reload(self):
        await self.sessions.save()
        save_id = self.sessions.active_id
        backend.engine.reset_world()
        await self.sessions.continue_world(save_id)
        self.engine = backend.engine
        self.smith_slot = self.engine._human_slot_for_id(self.smith_id)
        self.customer_slot = self.engine._human_slot_for_id(self.customer_id)
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
        self.move_customer_next_to_smith()

    def order(self):
        return self.orders()[0]

    async def test_reload_at_each_stage_is_exactly_once(self):
        start = self.totals()
        self.request()
        committed = sorted(self.order()["committed"])
        await self.reload()
        order = self.order()
        self.assertEqual((order["state"], sorted(order["committed"])), ("reserved", committed))
        self.assertEqual(self.totals(), {**start, "coin": start["coin"]})
        self.assertTrue(self.run_until(lambda: self.order()["state"] == "working"))
        for _ in range(10):
            self.engine.step()
        progress = self.order()["progress_ticks"]
        self.assertGreater(progress, 0)
        await self.reload()  # mid-work
        self.assertEqual(self.order()["state"], "working")
        self.assertEqual(self.order()["progress_ticks"], progress)  # persisted ticks, not wall time
        self.assertTrue(self.run_until(lambda: self.order()["state"] == "ready"))
        await self.reload()  # ready, not yet collected
        self.assertEqual(self.order()["state"], "ready")
        self.assertEqual(self.totals().get("sword"), 1)
        collected, _ = self.collect(self.order())
        self.assertEqual(collected["status"], "applied")
        await self.reload()  # delivered
        self.assertEqual(self.order()["state"], "delivered")
        again, _ = self.collect(self.order())
        self.assertEqual((again["status"], again["duplicate"]), ("applied", True))
        end = self.totals()
        self.assertEqual(end["sword"], 1)
        self.assertEqual((end["iron_ingot"], end["wood_bundle"]), (start["iron_ingot"] - 2, start["wood_bundle"] - 1))
        self.assertEqual(end["coin"], start["coin"])
        for human_id in (self.smith_id, self.customer_id):
            self.assertEqual(len(self.events(human_id, "commission_delivered")), 1)
            self.assertEqual(len(self.events(human_id, "commission_accepted")), 1)

    async def test_the_delivery_is_remembered_and_the_relationship_is_permanent_after_reload(self):
        order = self.to_ready()
        self.collect(order)
        await self.reload()
        smith = self.engine.resident_store.get(self.smith_id)
        self.assertEqual(len(self.events(self.smith_id, "commission_delivered")), 1)
        event = self.events(self.smith_id, "commission_delivered")[0]
        self.assertEqual(event["other_human_id"], self.customer_id)
        self.assertGreater(smith["relationships"][self.customer_id]["closeness"], 0.0)
        for _ in range(900):  # 45 s of play (1.5 game years): a default-TTL event would be gone
            self.engine.step()
        self.assertEqual(len(self.events(self.smith_id, "commission_delivered")), 1)
        self.assertIn(self.customer_id, self.engine.resident_store.get(self.smith_id)["relationships"])

    async def test_order_ids_never_repeat_across_reloads(self):
        self.request()
        first = self.order()["order_id"]
        canceled, _ = self.command("commission_cancel", order_id=first)
        self.assertEqual(canceled["status"], "applied")
        await self.reload()
        result, _ = self.request()
        self.assertNotEqual(result["order_id"], first)
        self.assertEqual(sorted(o["order_id"] for o in self.orders()), ["o_000001", "o_000002"])


if __name__ == "__main__":
    unittest.main()
