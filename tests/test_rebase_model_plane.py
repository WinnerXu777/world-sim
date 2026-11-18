"""systems.actions.rebase.rebase_model_plane: every absolute position the Model plane holds outside the tensors moves by (dx, dy); pocket residents do not."""
from authored_village import load_village_maps
import random
import unittest

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from driver_pin import pin_anchor
from systems.actions.agent_driver import AgentDriver, Goal, RulesTier1
from systems.actions.ladder import Errand
from systems.actions.rebase import HOLDERS, rebase_model_plane
from systems.roster.driver import runtime

DX, DY = -512.0, 256.0


class RebaseModelPlane(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.state = runtime(self.engine)
        self.a, self.b = self.humans[0], self.humans[1]
        self.slot_a, self.slot_b = self.engine._human_slot_for_id(self.a), self.engine._human_slot_for_id(self.b)
        self.h[self.slot_b, cfg.H_SPACE] = 3.0                                    # b lives in a pocket: not shifted
        self.entity_uids = [u for u in self.engine._entity_uid_by_slot if u][:2]

    def fill(self, human_id):
        """Give one resident a value in every holder, positions (100, 200)-based."""
        slot = self.engine._human_slot_for_id(human_id)
        self.state.final_positions[human_id] = (100.0, 200.0)
        self.state.mover.plans[human_id] = {"goal": (110.0, 210.0), "waypoints": [(102.0, 202.0), (110.0, 210.0)], "index": 0, "revision": "r",
                                            "best": 9.0, "stalled": 0, "replans": 0}
        self.state.mover.plans[("task", human_id)] = {"goal": (120.0, 220.0), "waypoints": [(120.0, 220.0)], "index": 0, "revision": "r",
                                                      "best": 9.0, "stalled": 0, "replans": 0}
        self.state.mover.no_path[human_id] = ((130.0, 230.0), "r", 99999)
        record = self.engine.resident_store.get(human_id)
        record["tasks"] = [{"id": "t1", "task_kind": "move_to_place", "target_kind": "point", "target_place": {"x": 140.0, "y": 240.0}}]
        record.setdefault("task_state", {})["current_task"] = {"id": "t1", "target_place": {"x": 140.0, "y": 240.0}, "task_state": {"ambush_anchor": {"x": 150.0, "y": 250.0}}}
        record.setdefault("memory", {})["last_threats"] = [{"kind": "wolf", "tick": 5, "x": 180.0, "y": 280.0, "distance": 4.0}]
        record["goals"] = [{"id": "g1", "target_place": {"x": 160.0, "y": 260.0}}, {"id": "g2", "target_place": {}}]
        self.driver.last_goal[human_id] = Goal("routine", "work", (170.0, 270.0))
        self.driver.ladder.errands[human_id] = Errand("forage", "forage_node", (190.0, 290.0), self.entity_uids[0], "eat_from_node", {"node": self.entity_uids[0]}, 99999)
        return slot

    def snapshot(self, human_id):
        record = self.engine.resident_store.get(human_id)
        return {
            "final": self.state.final_positions[human_id],
            "plan": (self.state.mover.plans[human_id]["goal"], list(self.state.mover.plans[human_id]["waypoints"])),
            "task_plan": self.state.mover.plans[("task", human_id)]["goal"],
            "no_path": self.state.mover.no_path[human_id][0],
            "task": record["tasks"][0]["target_place"],
            "current": record["task_state"]["current_task"]["target_place"],
            "ambush": record["task_state"]["current_task"]["task_state"]["ambush_anchor"],
            "goal": record["goals"][0]["target_place"], "empty_goal": record["goals"][1]["target_place"],
            "threat": dict(record["memory"]["last_threats"][0]),
            "last_goal": self.driver.last_goal[human_id].position,
            "errand": self.driver.ladder.errands[human_id].position,
        }

    async def test_every_holder_of_an_overworld_resident_moves_by_the_shift_and_a_pocket_resident_is_untouched(self):
        slot_a = self.fill(self.a)
        self.fill(self.b)
        self.state.checkpoint = self.h[:, :2].clone()
        before_a, before_b = self.snapshot(self.a), self.snapshot(self.b)
        checkpoint_a, checkpoint_b = self.state.checkpoint[slot_a].clone(), self.state.checkpoint[self.slot_b].clone()
        counts = rebase_model_plane(self.engine, DX, DY)
        self.assertEqual(set(counts), set(HOLDERS))
        self.assertTrue(all(counts[name] > 0 for name in HOLDERS), counts)       # every holder fired
        after = self.snapshot(self.a)
        self.assertEqual(after["final"], (before_a["final"][0] + DX, before_a["final"][1] + DY))
        self.assertEqual(after["plan"][0], (110.0 + DX, 210.0 + DY))
        self.assertEqual(after["plan"][1], [(102.0 + DX, 202.0 + DY), (110.0 + DX, 210.0 + DY)])
        self.assertEqual(after["task_plan"], (120.0 + DX, 220.0 + DY))
        self.assertEqual(after["no_path"], (130.0 + DX, 230.0 + DY))
        for name, base in (("task", 140.0), ("current", 140.0), ("goal", 160.0)):
            self.assertEqual((after[name]["x"], after[name]["y"]), (base + DX, base + 100.0 + DY), name)
        self.assertEqual((after["ambush"]["x"], after["ambush"]["y"]), (150.0 + DX, 250.0 + DY))
        self.assertEqual((after["threat"]["x"], after["threat"]["y"]), (180.0 + DX, 280.0 + DY))
        self.assertEqual(after["threat"]["distance"], 4.0)
        self.assertEqual(after["empty_goal"], {})                                  # a place without coordinates stays as it was
        self.assertEqual(after["last_goal"], (170.0 + DX, 270.0 + DY))
        self.assertEqual(after["errand"], (190.0 + DX, 290.0 + DY))
        self.assertEqual(float(self.state.checkpoint[slot_a, 0]), float(checkpoint_a[0]) + DX)
        self.assertEqual(float(self.state.checkpoint[slot_a, 1]), float(checkpoint_a[1]) + DY)
        self.assertEqual(self.snapshot(self.b), before_b)                          # the pocket resident keeps its own frame
        self.assertTrue(torch.equal(self.state.checkpoint[self.slot_b], checkpoint_b))

    async def test_an_errand_to_a_pocket_entity_or_a_visit_keeps_its_position(self):
        """Only an errand whose target lives in the overworld is shifted; a pocket target keeps the pocket frame, a visit is recomputed from the person."""
        slot = next(s for s, u in enumerate(self.engine._entity_uid_by_slot) if u == self.entity_uids[1])
        self.engine.state.m_tensor[slot, cfg.M_SPACE] = 3.0
        errands = self.driver.ladder.errands
        errands[self.a] = Errand("steal", "steal", (50.0, 60.0), self.entity_uids[1], "steal_when_safe", {}, 99999)
        counts = rebase_model_plane(self.engine, DX, DY)
        self.assertEqual(errands[self.a].position, (50.0, 60.0))
        errands[self.a] = Errand("trade", "visit", (70.0, 80.0), self.b, "offer_trade", {}, 99999)
        counts = rebase_model_plane(self.engine, DX, DY)
        self.assertEqual(errands[self.a].position, (70.0, 80.0))
        self.assertEqual(counts["ladder_errands"], 0)

    async def test_a_zero_shift_changes_nothing_and_reports_zero_counts(self):
        self.fill(self.a)
        before = self.snapshot(self.a)
        counts = rebase_model_plane(self.engine, 0, 0)
        self.assertEqual(set(counts), set(HOLDERS))
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(self.snapshot(self.a), before)

    async def test_a_walking_resident_keeps_walking_to_the_same_anchor_after_the_shift(self):
        """A real plan survives: step, shift the residents and (as the window manager does) nothing else is needed for the mover to carry on."""
        for _ in range(5):
            self.engine.step()
        plans_before = {k: (v["goal"], list(v["waypoints"])) for k, v in self.state.mover.plans.items()}
        counts = rebase_model_plane(self.engine, DX, DY)
        for key, (goal, waypoints) in plans_before.items():
            owner = key[1] if isinstance(key, tuple) else key
            if float(self.h[self.engine._human_slot_for_id(owner), cfg.H_SPACE]) == 0.0:
                plan = self.state.mover.plans[key]
                self.assertEqual(plan["goal"], (goal[0] + DX, goal[1] + DY))
        self.assertEqual(counts["mover_plans"], sum(1 for k in plans_before
                                                    if float(self.h[self.engine._human_slot_for_id(k[1] if isinstance(k, tuple) else k), cfg.H_SPACE]) == 0.0))


if __name__ == "__main__":
    unittest.main()
