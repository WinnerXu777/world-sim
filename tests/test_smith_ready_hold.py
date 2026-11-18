"""A ready, uncollected sword keeps the smith at his forge (bounded), whatever the schedule says.

Found by the Godot live harness on the 4-map world: the order became ready in the evening/night block (a time block is 600
ticks, a sword takes 900), the commission pull on the smith ended at ``ready``, his schedule walked him to bed and the
customer's collect failed (out of range / blocked) although the sword was ready.
"""
import math
import unittest
import uuid

from authored_village import load_village_maps
from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from systems.commission.config import COMMISSION_CONFIG
from systems.commission.engine import commission_goal_override, find_smith
from systems.roster.driver import map_id_at, runtime

NIGHT_START = 1790  # engine.tick % 2400: the "night" block begins at 1800


class ReadyHoldCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._config = dict(COMMISSION_CONFIG)
        COMMISSION_CONFIG.update(work_ticks_per_time_unit=20, forge_wait_ticks=30)  # 30 work ticks instead of 900
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.smith_id, _ = find_smith(self.engine)
        self.smith_slot = self.engine._human_slot_for_id(self.smith_id)
        iven = next(u for u in self.engine._human_uid_by_slot if u and self.engine.resident_store.get(u)["roster"]["key"] == "iven")
        self.customer_id, self.customer_slot = iven, self.engine._human_slot_for_id(iven)
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=iven)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}

    async def asyncTearDown(self):
        COMMISSION_CONFIG.clear()
        COMMISSION_CONFIG.update(self._config)
        await super().asyncTearDown()

    def reclaim(self):
        """Possession lapses after 5 s of wall-clock silence (a real client keeps sending input); take it again."""
        self.engine.player_control.release_target(self.engine, controller_id="cust") if hasattr(self.engine.player_control, "release_target") else None
        claim = self.engine.player_control.claim_target(self.engine, controller_id="cust", target_kind="human", target_id=self.customer_id)
        self.env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}

    def command(self, action, **extra):
        payload = {**self.env, "command_id": str(uuid.uuid4()), **extra}
        self.assertEqual(self.engine.command_inbox.submit(self.engine, action, payload)["status"], "received")
        self.engine.step()
        return self.engine.command_inbox.result(payload["command_id"])

    def smith_position(self):
        h = self.engine.state.h_tensor
        return float(h[self.smith_slot, cfg.X]), float(h[self.smith_slot, cfg.Y])

    def stand_next_to_smith(self):
        x, y = self.smith_position()
        h = self.engine.state.h_tensor
        h[self.customer_slot, cfg.X], h[self.customer_slot, cfg.Y] = x + 9.0, y + 3.0

    def order(self):
        return next(iter(self.engine.inventory_state["work_orders"]["orders"].values()))

    def run_until(self, predicate, limit=900):
        for _ in range(limit):
            if predicate():
                return True
            self.engine.step()
        return predicate()

    async def ready_at_night(self):
        for _ in range(5):
            self.engine.step()
        self.engine.tick = NIGHT_START  # dusk: the order will become ready after the night block began
        self.stand_next_to_smith()
        accepted = self.command("commission_request")
        self.assertEqual(accepted["code"], "accepted", accepted)
        self.assertTrue(self.run_until(lambda: self.order()["state"] == "ready"))
        self.assertGreaterEqual(self.engine.tick % 2400, 1800)  # it is night now
        return self.order()

    async def test_a_ready_sword_keeps_the_smith_at_the_forge_and_collect_succeeds_at_night(self):
        order = await self.ready_at_night()
        work = runtime(self.engine).at_anchor.get(self.smith_id)
        self.assertEqual(work, "work")
        start = self.smith_position()
        for _ in range(300):  # the customer needs a moment to turn round; the schedule says sleep
            self.engine.step()
        end = self.smith_position()
        self.assertLess(math.hypot(end[0] - start[0], end[1] - start[1]), 3.0, "the smith walked away from a ready, uncollected order")
        self.assertEqual(map_id_at(self.engine, end), "smith_interior")
        self.reclaim()
        self.stand_next_to_smith()
        collected = self.command("commission_collect", order_id=order["order_id"])
        self.assertEqual((collected["status"], collected["state"]), ("applied", "delivered"), collected)

    async def test_the_hold_ends_when_the_sword_is_collected_and_the_smith_goes_back_to_his_schedule(self):
        order = await self.ready_at_night()
        self.reclaim()
        self.stand_next_to_smith()
        self.assertEqual(commission_goal_override(self.engine, self.smith_id), "work")
        self.assertEqual(self.command("commission_collect", order_id=order["order_id"])["state"], "delivered")
        self.assertIsNone(commission_goal_override(self.engine, self.smith_id))
        before = self.smith_position()
        self.assertTrue(self.run_until(lambda: runtime(self.engine).goal_key.get(self.smith_id) != "work", 600))
        self.engine.step()
        self.assertNotEqual(runtime(self.engine).goal_key.get(self.smith_id), "work")  # the night routine took him over again

    async def test_the_hold_is_bounded_when_nobody_collects(self):
        COMMISSION_CONFIG["ready_hold_ticks"] = 100
        order = await self.ready_at_night()
        self.assertEqual(commission_goal_override(self.engine, self.smith_id), "work")
        for _ in range(110):
            self.engine.step()
        self.assertIsNone(commission_goal_override(self.engine, self.smith_id))  # the sword stays ready, the smith is free again
        self.assertEqual(self.order()["state"], "ready")
        self.assertEqual(self.order()["order_id"], order["order_id"])

    async def test_other_states_and_other_smiths_are_unaffected(self):
        self.assertIsNone(commission_goal_override(self.engine, self.smith_id))  # no order
        self.assertIsNone(commission_goal_override(self.engine, self.customer_id))  # not a smith
        self.stand_next_to_smith()
        self.command("commission_request")
        self.assertEqual(commission_goal_override(self.engine, self.smith_id), "work")  # reserved
        self.assertTrue(self.run_until(lambda: self.order()["state"] == "working"))
        self.assertEqual(commission_goal_override(self.engine, self.smith_id), "work")


if __name__ == "__main__":
    unittest.main()
