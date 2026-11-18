import copy
import unittest
import uuid

import httpx

from test_startup_preservation import backend


class ControlProtocolTests(unittest.IsolatedAsyncioTestCase):
    def identified_event(self, **changes):
        return {**self.payload, "event_id": uuid.uuid4().hex, "event": "talk_command",
                "action": "talk", "semantic_action": "talk_command", "text": "One request", **changes}

    async def test_event_result_read_is_scoped_and_does_not_resubmit(self):
        event = self.identified_event()
        self.runtime.submit_event(backend.engine, "player", event)
        params = {"controller_id": "player", "event_id": event["event_id"],
                  "world_epoch": event["world_epoch"], "possession_epoch": event["possession_epoch"]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            before = copy.deepcopy(self.runtime.sessions_by_controller)
            result = await client.get("/control/event_result", params=params)
            self.assertEqual(result.json()["status"], "received")
            for changes in ({"world_epoch": "old"}, {"possession_epoch": "old"},
                            {"controller_id": "someone_else"}, {"event_id": "invalid"},
                            {"event_id": uuid.uuid4().hex}):
                response = await client.get("/control/event_result", params={**params, **changes})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
            self.assertEqual(self.runtime.sessions_by_controller, before)
            self.runtime.begin_tick_inputs(backend.engine)
            result = await client.get("/control/event_result", params=params)
            self.assertEqual(result.json()["status"], "consumed")
            self.assertEqual(len(self.runtime.drain_talk_events(backend.engine)), 1)
            self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])

    async def test_two_identified_attacks_and_movement_each_reach_their_tick_phase(self):
        engine = backend.engine
        victim = engine._human_uid_by_slot[1]
        engine.state.h_tensor[0, backend.X] = 100
        engine.state.h_tensor[0, backend.Y] = 100
        engine.state.h_tensor[1, backend.X] = 101
        engine.state.h_tensor[1, backend.Y] = 100
        engine.state.h_tensor[0, backend.H_STAMINA] = 100
        engine.state.h_tensor[1, backend.HP] = 100
        first = self.identified_event(event="click_command", action="attack", semantic_action="attack_target", target_id=victim)
        second = {**first, "event_id": uuid.uuid4().hex}
        for event in (first, second):
            self.assertTrue(self.runtime.submit_event(engine, "player", event)["ok"])
        self.runtime.submit_input(engine, "player", {**self.payload, "seq": 10})
        for count, event in enumerate((first, second), 1):
            self.runtime.begin_tick_inputs(engine)
            engine._apply_manual_control_human_actions(self.runtime.build_tick_context(engine))
            result = self.runtime.submit_event(engine, "player", event)
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["reason"], "hit")
            self.assertAlmostEqual(float(engine.state.h_tensor[1, backend.HP]), 100 - count * backend.ATTACK_DAMAGE)
            self.assertEqual(self.runtime.sessions_by_controller["player"]["move_vector"], {"x": 0, "y": 0})
        self.runtime.begin_tick_inputs(engine)
        engine._apply_manual_control_human_actions(self.runtime.build_tick_context(engine))
        self.assertEqual(self.runtime.sessions_by_controller["player"]["move_vector"], {"x": 1, "y": 0})
        self.assertAlmostEqual(float(engine.state.h_tensor[1, backend.HP]), 100 - 2 * backend.ATTACK_DAMAGE)

    async def test_identified_invalid_attack_finishes_rejected_and_does_not_linger(self):
        event = self.identified_event(event="click_command", action="attack", semantic_action="attack_target", target_id="missing")
        self.runtime.submit_event(backend.engine, "player", event)
        backend.engine.step()
        result = self.runtime.submit_event(backend.engine, "player", event)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "target_invalid")
        self.assertIsNone(self.runtime.sessions_by_controller["player"]["command_state"]["pending_action"])

    async def test_full_simulation_tick_applies_manual_attack_damage_once(self):
        engine = backend.engine
        victim = engine._human_uid_by_slot[1]
        self.runtime.claim_target(engine, controller_id="victim", target_kind="human", target_id=victim)
        engine.state.h_tensor[0, backend.X] = 100
        engine.state.h_tensor[0, backend.Y] = 100
        engine.state.h_tensor[1, backend.X] = 101
        engine.state.h_tensor[1, backend.Y] = 100
        engine.state.h_tensor[0, backend.H_STAMINA] = 100
        engine.state.h_tensor[1, backend.HP] = 100
        event = self.identified_event(event="click_command", action="attack", semantic_action="attack_target", target_id=victim)
        self.runtime.submit_event(engine, "player", event)
        engine.step()
        self.assertAlmostEqual(float(engine.state.h_tensor[1, backend.HP]), 100 - backend.ATTACK_DAMAGE)
        self.assertEqual(self.runtime.submit_event(engine, "player", event)["status"], "applied")

    async def test_full_tick_wall_blocks_identified_attack_with_final_receipt(self):
        engine = backend.engine
        wall = backend.world_contract(engine)["boxes"][0]
        x = (wall["min"][0] + wall["max"][0]) / 2
        victim = engine._human_uid_by_slot[1]
        self.runtime.claim_target(engine, controller_id="victim", target_kind="human", target_id=victim)
        engine.state.h_tensor[:2, backend.X] = x
        engine.state.h_tensor[0, backend.Y] = wall["min"][1] - .4
        engine.state.h_tensor[1, backend.Y] = wall["max"][1] + .4
        engine.state.h_tensor[0, backend.H_STAMINA] = 100
        engine.state.h_tensor[1, backend.HP] = 100
        event = self.identified_event(event="click_command", action="attack", semantic_action="attack_target", target_id=victim)
        self.runtime.submit_event(engine, "player", event)
        engine.step()
        result = self.runtime.submit_event(engine, "player", event)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "blocked")
        self.assertEqual(float(engine.state.h_tensor[1, backend.HP]), 100)

    async def test_identified_attack_range_and_stamina_rejections_preserve_health(self):
        engine = backend.engine
        for distance, stamina, reason in ((100, 100, "range"), (1, 0, "stamina")):
            engine.state.h_tensor[0, backend.X] = 100
            engine.state.h_tensor[0, backend.Y] = 100
            engine.state.h_tensor[1, backend.X] = 100 + distance
            engine.state.h_tensor[1, backend.Y] = 100
            engine.state.h_tensor[0, backend.H_STAMINA] = stamina
            before = float(engine.state.h_tensor[1, backend.HP])
            event = self.identified_event(event="click_command", action="attack", semantic_action="attack_target",
                                          target_id=engine._human_uid_by_slot[1])
            self.runtime.submit_event(engine, "player", event)
            self.runtime.begin_tick_inputs(engine)
            engine._apply_manual_control_human_actions(self.runtime.build_tick_context(engine))
            result = self.runtime.submit_event(engine, "player", event)
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["reason"], reason)
            self.assertEqual(float(engine.state.h_tensor[1, backend.HP]), before)

    async def test_identified_event_retry_consumed_once_despite_new_movement(self):
        event = self.identified_event()
        self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": 10})
        first = self.runtime.submit_event(backend.engine, "player", event)
        self.assertEqual(first["status"], "received")
        duplicate = self.runtime.submit_event(backend.engine, "player", {**event, "seq": 20})
        self.assertTrue(duplicate["duplicate"])
        self.runtime.begin_tick_inputs(backend.engine)
        events = self.runtime.drain_talk_events(backend.engine)
        self.assertEqual([e["event"]["event_id"] for e in events], [event["event_id"]])
        again = self.runtime.submit_event(backend.engine, "player", event)
        self.assertEqual(again["status"], "consumed")
        self.assertEqual(first["status"], "received")
        self.runtime.begin_tick_inputs(backend.engine)
        self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])
        self.assertEqual(self.runtime.sessions_by_controller["player"]["last_input_seq"], 10)

    async def test_identified_event_conflict_invalid_id_and_old_epoch_do_not_mutate(self):
        event = self.identified_event()
        self.runtime.submit_event(backend.engine, "player", event)
        before = copy.deepcopy(self.runtime.sessions_by_controller)
        for change, reason in (({"text": "Different request"}, "event_id_conflict"),
                               ({"event_id": "bad"}, "invalid_control_event"),
                               ({"world_epoch": "old"}, "stale_world_epoch"),
                               ({"possession_epoch": "old"}, "stale_possession_epoch")):
            result = self.runtime.submit_event(backend.engine, "player", {**event, **change})
            self.assertEqual(result["reason"], reason)
            self.assertEqual(self.runtime.sessions_by_controller, before)

    async def test_expired_identified_event_cannot_be_revived_by_retry(self):
        now = [100.0]
        self.runtime.clock = lambda: now[0]
        event = self.identified_event()
        self.runtime.submit_event(backend.engine, "player", event)
        now[0] += 1
        self.runtime.tick_maintenance(backend.engine)
        retry = self.runtime.submit_event(backend.engine, "player", event)
        self.assertEqual(retry["status"], "expired")
        self.runtime.begin_tick_inputs(backend.engine)
        self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])

    async def test_event_receipt_bound_preserves_old_ids_and_rejects_new_ones(self):
        first = self.identified_event(action="cancel", semantic_action="cancel", event="cancel")
        self.runtime.submit_event(backend.engine, "player", first)
        self.runtime.begin_tick_inputs(backend.engine)
        for _ in range(4095):
            result = self.runtime.submit_event(backend.engine, "player", {**first, "event_id": uuid.uuid4().hex})
            self.assertTrue(result["ok"])
            self.runtime.begin_tick_inputs(backend.engine)
        full = self.runtime.submit_event(backend.engine, "player", self.identified_event())
        self.assertEqual(full["reason"], "event_receipts_full")
        self.assertTrue(self.runtime.submit_event(backend.engine, "player", first)["duplicate"])

    async def asyncSetUp(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.runtime = backend.engine.player_control
        self.target = backend.engine._human_uid_by_slot[0]
        self.claim = self.runtime.claim_target(backend.engine, controller_id="player",
                                               target_kind="human", target_id=self.target)
        self.payload = {"protocol_version": 1, "world_epoch": backend.engine.world_epoch,
                        "possession_epoch": self.claim["possession_epoch"], "seq": 1,
                        "controller_id": "player", "target_id": self.target,
                        "target_kind": "human", "move": {"x": 1, "y": 0}}

    async def test_old_possession_input_and_event_rejected_after_reclaim_same_actor(self):
        self.runtime.release_target(backend.engine, controller_id="player")
        new = self.runtime.claim_target(backend.engine, controller_id="player",
                                        target_kind="human", target_id=self.target)
        self.assertNotEqual(new["possession_epoch"], self.claim["possession_epoch"])
        before = copy.deepcopy(self.runtime.sessions_by_controller)
        for submit in (self.runtime.submit_input, self.runtime.submit_event):
            result = submit(backend.engine, "player", self.payload)
            self.assertEqual(result["reason"], "stale_possession_epoch")
        self.assertEqual(before, self.runtime.sessions_by_controller)

    async def test_committed_position_and_ack_stay_paired_between_ticks(self):
        engine = backend.engine
        engine.state.h_tensor[0, backend.X] = 100.12345
        engine.state.h_tensor[0, backend.Y] = 100.54321
        self.runtime.submit_input(engine, "player", self.payload)
        before_tick = engine.tick
        engine.step()
        first = self.runtime.status_snapshot()["sessions"][0]["committed_state"]
        self.assertEqual(first["completed_tick"], before_tick)
        self.assertEqual(first["last_applied_input_seq"], 1)
        self.assertEqual(first["position"], {"x": float(engine.state.h_tensor[0, backend.X]),
                                             "y": float(engine.state.h_tensor[0, backend.Y])})
        self.assertNotEqual(first["position"]["x"], round(first["position"]["x"], 1))
        self.runtime.submit_input(engine, "player", {**self.payload, "seq": 2, "move": {"x": 0, "y": 1}})
        received = self.runtime.status_snapshot()["sessions"][0]
        self.assertEqual(received["last_input_seq"], 2)
        self.assertEqual(received["committed_state"], first)
        received["committed_state"]["position"]["x"] = -1000
        self.assertEqual(self.runtime.status_snapshot()["sessions"][0]["committed_state"], first)
        engine.step()
        second = self.runtime.status_snapshot()["sessions"][0]["committed_state"]
        self.assertEqual(second["completed_tick"], before_tick + 1)
        self.assertEqual(second["last_applied_input_seq"], 2)
        self.assertEqual(second["position"]["y"], float(engine.state.h_tensor[0, backend.Y]))
        self.runtime.release_target(engine, controller_id="player")
        self.runtime.claim_target(engine, controller_id="player", target_kind="human", target_id=self.target)
        self.assertIsNone(self.runtime.status_snapshot()["sessions"][0]["committed_state"])

    async def test_committed_position_contains_collision_result(self):
        from systems.movement.spatial import world_contract
        engine = backend.engine
        wall = world_contract(engine)["boxes"][0]
        engine.state.h_tensor[0, backend.X] = (wall["min"][0] + wall["max"][0]) / 2
        engine.state.h_tensor[0, backend.Y] = wall["min"][1] - .5
        self.runtime.submit_input(engine, "player", {**self.payload, "move": {"x": 0, "y": 1}})
        engine.step()
        state = self.runtime.status_snapshot()["sessions"][0]["committed_state"]
        self.assertEqual(state["position"]["y"], float(engine.state.h_tensor[0, backend.Y]))
        self.assertLessEqual(state["position"]["y"], wall["min"][1] - .35 + .0001)
        self.assertEqual(state["last_applied_input_seq"], 1)

    async def test_applied_duration_counts_held_ticks_and_resets_for_new_input(self):
        engine = backend.engine
        self.runtime.submit_input(engine, "player", self.payload)
        for count in range(1, 4):
            engine.step()
            state = self.runtime.status_snapshot()["sessions"][0]["committed_state"]
            self.assertEqual(state["last_applied_input_seq"], 1)
            self.assertAlmostEqual(state["input_applied_seconds"], count / backend.TICK_RATE_HZ)
        self.runtime.submit_input(engine, "player", {**self.payload, "seq": 2})
        self.runtime.submit_input(engine, "player", {**self.payload, "seq": 3})
        engine.step()
        state = self.runtime.status_snapshot()["sessions"][0]["committed_state"]
        self.assertEqual(state["last_applied_input_seq"], 3)
        self.assertAlmostEqual(state["input_applied_seconds"], 1 / backend.TICK_RATE_HZ)

    async def test_old_world_rejected_even_if_possession_token_matches(self):
        self.payload["world_epoch"] = "previous-world"
        result = self.runtime.submit_input(backend.engine, "player", self.payload)
        self.assertEqual(result["reason"], "stale_world_epoch")
        self.assertEqual(self.runtime.sessions_by_controller["player"]["last_input_seq"], -1)

    async def test_valid_input_and_duplicate_have_one_received_effect(self):
        async with httpx.AsyncClient(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}, transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            first = await client.post("/control/input", json=self.payload)
            self.assertEqual(first.status_code, 200)
            before = copy.deepcopy(self.runtime.sessions_by_controller)
            again = await client.post("/control/input", json=self.payload)
            self.assertEqual(again.json()["reason"], "stale_input_seq")
            self.assertEqual(before, self.runtime.sessions_by_controller)

    async def test_invalid_input_cannot_mutate_session(self):
        cases = [{"protocol_version": 2}, {"seq": True}, {"seq": "1"},
                 {"target_id": "other-actor"}, {"move": {"x": float("nan")}},
                 {"look_yaw": float("inf")}, {"move": []}]
        before = copy.deepcopy(self.runtime.sessions_by_controller)
        for changes in cases:
            with self.subTest(changes=changes):
                result = self.runtime.submit_input(backend.engine, "player", {**self.payload, **changes})
                self.assertFalse(result["ok"])
                self.assertEqual(before, self.runtime.sessions_by_controller)

    async def test_received_input_is_only_applied_and_acknowledged_by_tick(self):
        self.assertTrue(self.runtime.submit_input(backend.engine, "player", self.payload)["ok"])
        session = self.runtime.sessions_by_controller["player"]
        self.assertEqual(session["last_input_seq"], 1)
        self.assertEqual(session["last_applied_input_seq"], -1)
        self.assertEqual(session["move_vector"], {"x": 0, "y": 0})
        backend.engine.step()
        self.assertEqual(session["move_vector"], {"x": 1, "y": 0})
        self.assertEqual(session["last_applied_input_seq"], 1)
        self.assertEqual(backend.engine._frame_payload["controls"][0]["last_applied_input_seq"], 1)

    async def test_full_queue_rejects_without_ack_and_release_discards_pending_input(self):
        for seq in range(1, 65):
            self.assertTrue(self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": seq})["ok"])
        full = self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": 65})
        self.assertEqual(full["reason"], "input_queue_full")
        self.assertEqual(self.runtime.sessions_by_controller["player"]["last_input_seq"], 64)
        self.runtime.release_target(backend.engine, controller_id="player")
        self.runtime.claim_target(backend.engine, controller_id="player", target_kind="human", target_id=self.target)
        backend.engine.step()
        session = self.runtime.sessions_by_controller["player"]
        self.assertEqual(session["move_vector"], {"x": 0, "y": 0})
        self.assertEqual(session["last_applied_input_seq"], -1)

    async def test_movement_and_cancel_are_consumed_in_received_sequence_order(self):
        session = self.runtime.sessions_by_controller["player"]
        self.runtime.submit_input(backend.engine, "player", self.payload)
        cancel = {**self.payload, "seq": 2, "event": "cancel", "semantic_action": "cancel", "action": "cancel"}
        self.assertTrue(self.runtime.submit_event(backend.engine, "player", cancel)["ok"])
        self.assertEqual(session["last_consumed_command_seq"], -1)
        self.assertFalse(any(item.get("kind") == "event" for item in self.runtime.history))
        backend.engine.step()
        self.assertEqual(session["move_vector"], {"x": 0, "y": 0})
        self.assertEqual(session["last_consumed_command_seq"], 2)
        self.assertEqual(session["last_applied_input_seq"], 1)
        self.runtime.submit_event(backend.engine, "player", {**cancel, "seq": 3})
        self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": 4})
        backend.engine.step()
        self.assertEqual(session["move_vector"], {"x": 1, "y": 0})
        self.assertEqual(session["last_consumed_command_seq"], 4)

    async def test_accepted_talk_events_are_not_silently_truncated_at_eight(self):
        for seq in range(1, 13):
            event = {**self.payload, "seq": seq, "event": "talk_command", "action": "talk",
                     "semantic_action": "talk_command", "text": f"Line {seq}"}
            self.assertTrue(self.runtime.submit_event(backend.engine, "player", event)["ok"])
        self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])
        self.runtime.begin_tick_inputs(backend.engine)
        events = self.runtime.drain_talk_events(backend.engine)
        self.assertEqual([entry["event"]["seq"] for entry in events], list(range(1, 13)))
        self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])

    async def test_wall_clock_disconnect_neutralizes_then_releases_possession(self):
        now = [100.0]
        self.runtime.clock = lambda: now[0]
        self.runtime.submit_input(backend.engine, "player", {**self.payload, "buttons": {"attack": True}})
        backend.engine.step()
        session = self.runtime.sessions_by_controller["player"]
        now[0] += self.runtime.input_timeout
        # This does not depend on simulated time advancing; it also handles resume after pause.
        self.runtime.tick_maintenance(backend.engine)
        self.assertEqual(session["move_vector"], {"x": 0, "y": 0})
        self.assertFalse(session["buttons"]["attack"])
        self.assertIsNone(session["command_state"]["pending_action"])
        now[0] = 105.0
        self.runtime.tick_maintenance(backend.engine)
        self.assertNotIn("player", self.runtime.sessions_by_controller)
        self.assertFalse(self.runtime.controlled_human_mask(backend.engine).any())

    async def test_expired_pending_actions_are_discarded_without_applied_ack(self):
        now = [100.0]
        self.runtime.clock = lambda: now[0]
        self.runtime.submit_input(backend.engine, "player", self.payload)
        now[0] = 101.0
        backend.engine.step()
        session = self.runtime.sessions_by_controller["player"]
        self.assertEqual(session["last_input_seq"], 1)
        self.assertEqual(session["last_applied_input_seq"], -1)
        self.assertEqual(session["last_consumed_command_seq"], -1)
        self.assertEqual(session["pending_inputs"], [])
        self.assertTrue(self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": 2})["ok"])
        backend.engine.step()
        self.assertEqual(session["last_applied_input_seq"], 2)

    async def test_new_packet_does_not_revive_expired_queued_talk(self):
        now = [100.0]
        self.runtime.clock = lambda: now[0]
        event = {**self.payload, "event": "talk_command", "action": "talk",
                 "semantic_action": "talk_command", "text": "Obsolete speech"}
        self.runtime.submit_event(backend.engine, "player", event)
        now[0] = 101.0
        self.runtime.submit_input(backend.engine, "player", {**self.payload, "seq": 2})
        self.runtime.begin_tick_inputs(backend.engine)
        self.assertEqual(self.runtime.drain_talk_events(backend.engine), [])
        self.assertEqual(self.runtime.sessions_by_controller["player"]["move_vector"], {"x": 1, "y": 0})
