"""Window re-base with most residents far from the player (the real-server walk: 5-7 space-0 residents end up outside the window): the model plane keeps every resident, every book and every
errand coherent through several re-bases, and the agent driver keeps stepping without errors."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import math
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from systems.actions.agent_driver import AgentDriver, Goal, RulesTier1
from systems.actions.ladder import Errand
from systems.actions.offers import offers_of
from systems.actions.rebase import FOLLOWING_PURPOSES, rebase_model_plane
from systems.credit import runtime as credit_runtime
from systems.justice import runtime as justice_runtime
from systems.labour import runtime as labour_runtime

# window shifts of the real walk (1 202 .. 3 400 units), one per epoch 0..4
SHIFTS = [(-1202.0, 0.0), (0.0, -1500.0), (-2048.0, 640.0), (1024.0, -3400.0), (-512.0, 256.0)]


class FarResidents(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_CREDIT": "1", "EDEN_LABOUR": "1", "EDEN_JUSTICE": "1",
                                                          "EDEN_MARKET": "1", "EDEN_REPUTATION": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.runner = self.driver.runner(self.engine)
        self.services = self.runner.services
        self.near, self.far = self.humans[:1], self.humans[1:8]
        for index, human_id in enumerate(self.far):                    # seven residents far outside the window (the player's frame is near the first resident)
            slot = self.engine._human_slot_for_id(human_id)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 4000.0 + 500.0 * index, -3000.0 + 700.0 * index
        self.entity = next(u for u in self.engine._entity_uid_by_slot if u)

    def pos(self, human_id):
        slot = self.engine._human_slot_for_id(human_id)
        return float(self.h[slot, cfg.X]), float(self.h[slot, cfg.Y])

    def populate(self):
        """Every kind of state the plane keeps about a resident, on the far residents: errands of every purpose, an open loan, a shift, a case, an offer, a goal."""
        f = self.far
        errands = self.driver.ladder.errands
        errands[f[0]] = Errand("forage", "forage_node", (self.pos(f[0])[0] + 5, self.pos(f[0])[1]), self.entity, "eat_from_node", {"node": self.entity}, 10 ** 6)
        errands[f[1]] = Errand("steal", "steal", (self.pos(f[1])[0] + 5, self.pos(f[1])[1]), self.entity, "steal_when_safe", {}, 10 ** 6)
        for who, target, rung, purpose, verb in ((f[2], f[3], "trade", "visit", "offer_trade"), (f[3], f[4], "repay", "repay", "pay_debt"), (f[4], f[5], "work", "labour", "collect_wage"),
                                                 (f[5], f[6], "report", "report", "report_theft"), (f[6], f[2], "enforce", "enforce", "levy_damages")):
            errands[who] = Errand(rung, purpose, self.pos(target), target, verb, {"target": target}, 10 ** 6)
        loans = credit_runtime.of(self.services)
        self.loan = loans.open(f[0], f[1], "rations", 1, 0.3, 0, 2400)
        jobs = labour_runtime.of(self.services)
        self.job = jobs.hire(f[2], f[3], "coin", 2, 0)
        docket = justice_runtime.of(self.services)
        self.case = docket.open(f[1], f[0], f[6], f[0], "rations", 1, 3.0, 0, 2400)
        self.offer = offers_of(self.services).open(f[4], f[5], "rations", 1, "coin", 3, 0)
        for human_id in f:
            self.driver.last_goal[human_id] = Goal("routine", "work", (self.pos(human_id)[0] + 3, self.pos(human_id)[1] + 4))

    def books(self):
        loans, jobs, docket = credit_runtime.of(self.services), labour_runtime.of(self.services), justice_runtime.of(self.services)
        return ({k: (v.status, v.owed) for k, v in loans.loans.items()}, {k: (v.status, v.ready_at) for k, v in jobs.jobs.items()},
                {k: (v.status, v.outcome) for k, v in docket.cases.items()})

    async def test_five_rebases_with_seven_far_residents_lose_nothing_and_move_every_position_once(self):
        self.populate()
        uids = list(self.engine._human_uid_by_slot)
        books = self.books()
        offers = dict(offers_of(self.services)._offers)
        total_dx = total_dy = 0.0
        before = {h: self.pos(h) for h in self.humans}
        errands_before = {h: e.position for h, e in self.driver.ladder.errands.items()}
        goals_before = {h: g.position for h, g in self.driver.last_goal.items() if h in self.far}
        for dx, dy in SHIFTS:
            for human_id in self.humans:                              # the window manager shifts the tensors first
                slot = self.engine._human_slot_for_id(human_id)
                self.h[slot, cfg.X] += dx
                self.h[slot, cfg.Y] += dy
            counts = rebase_model_plane(self.engine, dx, dy)
            total_dx, total_dy = total_dx + dx, total_dy + dy
            self.assertEqual(counts["driver_goals"], len(self.far), counts)
        self.assertEqual(list(self.engine._human_uid_by_slot), uids)                              # no uid lost or moved
        self.assertEqual(offers_of(self.services)._offers, offers)                                 # open offers survive untouched
        self.assertEqual(self.books(), books)                                                      # the books hold no coordinates: nothing to shift, nothing lost
        for human_id in self.far:
            self.assertEqual(self.driver.last_goal[human_id].position, (goals_before[human_id][0] + total_dx, goals_before[human_id][1] + total_dy))
        errands = self.driver.ladder.errands
        for human_id in (self.far[0], self.far[1]):                                                 # a node / container errand is a fixed place: shifted with the world
            e0 = errands_before[human_id]
            self.assertEqual(errands[human_id].position, (e0[0] + total_dx, e0[1] + total_dy))
        for human_id, errand in errands.items():                                                    # a following errand's position is recomputed from the person each tick
            if errand.purpose in FOLLOWING_PURPOSES:
                self.assertEqual(errand.position, errands_before[human_id], errand.purpose)         # not touched by the re-base ...
                goal = self.driver.ladder.errand_goal(human_id, 0, self.engine)
                self.assertEqual(goal, self.pos(errand.target), errand.purpose)                      # ... and the live goal is the person's real position

    async def test_the_driver_keeps_stepping_after_the_rebase_without_errors(self):
        self.populate()
        for dx, dy in SHIFTS[:3]:
            for human_id in self.humans:
                slot = self.engine._human_slot_for_id(human_id)
                self.h[slot, cfg.X] += dx
                self.h[slot, cfg.Y] += dy
            rebase_model_plane(self.engine, dx, dy)
        for _ in range(40):
            self.engine.step()
        self.assertEqual(self.driver.errors, 0)
        self.assertTrue(all(math.isfinite(v) for h in self.humans for v in self.pos(h)))
        self.assertEqual(len([u for u in self.engine._human_uid_by_slot if u]), len(self.humans))


if __name__ == "__main__":
    unittest.main()
