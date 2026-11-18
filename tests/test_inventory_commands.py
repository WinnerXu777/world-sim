import copy
import unittest
import uuid
import httpx
from test_startup_preservation import backend
from systems.inventory import get_owner_inventory, get_container_inventory, add_item, total_quantity
from simulation.commands import CommandInbox


class InventoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.engine = backend.engine
        self.actor = self.engine._human_uid_by_slot[0]
        claim = self.engine.player_control.claim_target(self.engine, controller_id="inventory_test",
                                                       target_kind="human", target_id=self.actor)
        self.own = get_owner_inventory(self.engine.inventory_state, "human", self.actor)
        h = self.engine.state.h_tensor[0]
        container_id = self.engine._spawn_storage_case_at(float(h[backend.X]) + 2, float(h[backend.Y]), seed_contents=False)
        self.container = get_container_inventory(self.engine.inventory_state, container_id)
        add_item(self.container, "wood_bundle", 5)
        self.payload = {"protocol_version": 1, "world_epoch": self.engine.world_epoch,
                        "possession_epoch": claim["possession_epoch"], "controller_id": "inventory_test",
                        "command_id": str(uuid.uuid4()), "source_inventory_id": self.container["inventory_id"],
                        "target_inventory_id": self.own["inventory_id"], "item_kind": "wood_bundle", "quantity": 1}

    async def test_transfer_retries_have_one_effect_and_stable_applied_result(self):
        before = total_quantity(self.own, "wood_bundle")
        async with httpx.AsyncClient(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}, transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            first = await client.post("/inventory/transfer", json=self.payload)
            self.assertEqual(first.status_code, 202, first.text)
            again = await client.post("/inventory/transfer", json=self.payload)
            self.assertEqual(first.json(), again.json())
            self.assertEqual(total_quantity(self.own, "wood_bundle"), before)
            self.engine.step()
            result = (await client.get("/commands/" + self.payload["command_id"])).json()
            self.assertEqual(result["status"], "applied", result)
            self.assertEqual(result["moved"], 1)
            self.assertEqual(total_quantity(self.own, "wood_bundle"), before + 1)
            replay = (await client.post("/inventory/transfer", json=self.payload)).json()
            self.assertEqual(replay, result)
            self.assertEqual(total_quantity(self.own, "wood_bundle"), before + 1)

    async def test_conflicting_id_and_stale_world_do_not_enqueue(self):
        inbox = self.engine.command_inbox
        inbox.submit(self.engine, "transfer", self.payload)
        conflict = inbox.submit(self.engine, "transfer", {**self.payload, "quantity": 2})
        self.assertEqual(conflict["reason"], "command_id_conflict")
        stale = inbox.submit(self.engine, "transfer", {**self.payload, "world_epoch": "old"})
        self.assertEqual(stale["reason"], "stale_world_epoch")
        self.assertEqual(len(inbox.pending), 1)

    async def test_release_before_tick_rejects_without_transfer(self):
        before = copy.deepcopy(self.engine.inventory_state)
        self.engine.command_inbox.submit(self.engine, "transfer", self.payload)
        self.engine.player_control.release_target(self.engine, controller_id="inventory_test")
        self.engine.command_inbox.drain(self.engine, backend.execute_inventory_command)
        self.assertEqual(self.engine.inventory_state, before)
        self.assertEqual(self.engine.command_inbox.result(self.payload["command_id"])["reason"], "stale_possession_epoch")

    async def test_reach_and_quantity_are_checked_at_application(self):
        for changes, reason in (({"quantity": -1}, "invalid_quantity"), ({}, "container_out_of_reach")):
            payload = {**self.payload, **changes, "command_id": str(uuid.uuid4())}
            self.engine.command_inbox.submit(self.engine, "transfer", payload)
            if not changes:
                self.engine.state.h_tensor[0, backend.X] += 500
            before = copy.deepcopy(self.engine.inventory_state)
            self.engine.command_inbox.drain(self.engine, backend.execute_inventory_command)
            self.assertEqual(self.engine.command_inbox.result(payload["command_id"])["reason"], reason)
            self.assertEqual(self.engine.inventory_state, before)

    async def test_capacity_rejection_keeps_previous_receipts_for_safe_retries(self):
        inbox = CommandInbox(capacity=1, result_capacity=1)
        receipt = inbox.submit(self.engine, "transfer", self.payload)
        overflow = inbox.submit(self.engine, "transfer", {**self.payload, "command_id": str(uuid.uuid4())})
        self.assertEqual(overflow["reason"], "command_capacity_reached")
        self.assertEqual(inbox.submit(self.engine, "transfer", self.payload), receipt)
        inbox.drain(self.engine, backend.execute_inventory_command)
        self.assertEqual(inbox.submit(self.engine, "transfer", self.payload)["status"], "applied")

    async def test_equip_another_resident_is_rejected(self):
        payload = {**self.payload, "owner_kind": "human", "owner_id": self.engine._human_uid_by_slot[1], "item_id": "anything"}
        before = copy.deepcopy(self.engine.inventory_state)
        self.engine.command_inbox.submit(self.engine, "equip", payload)
        self.engine.command_inbox.drain(self.engine, backend.execute_inventory_command)
        self.assertEqual(self.engine.command_inbox.result(payload["command_id"])["reason"], "inventory_not_controlled")
        self.assertEqual(self.engine.inventory_state, before)
