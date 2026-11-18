"""D-008 / R3-INT: the agent driver with Tier 1 = rules must reproduce the roster (anchor) driver. Proof step 1 of ``1008_agent_driver_design.md``:
same seed, same world, 8 roster residents, ``driver == "anchor"`` vs ``driver == "agent"``, positions and the arrival record compared tick by tick,
including a food trip and a water trip (hunger and thirst are raised for two residents at the start)."""
from authored_village import load_village_maps
import random
import unittest
from driver_pin import pin_anchor

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from systems.roster.driver import driver_kind, runtime
from systems.actions.agent_driver import AgentDriver, MatrixTier1, Row, RulesTier1, rules_macro
from systems.decision import matrix
from systems.actions.recordops import EngineRecordOps

TICKS = 2000


class AgentDriverEquivalence(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def run_world(self, kind, ticks=TICKS, raise_needs=True, tier1=None):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        engine.__dict__.pop("_roster_runtime", None)          # the mover's state outlives reset_world; a test must not inherit the previous test's
        engine.__dict__["_agent_driver"] = AgentDriver(tier1 or RulesTier1())      # a fresh driver (the decision cache must not outlive a world)
        random.seed(1008)
        torch.manual_seed(1008)
        humans = [u for u in engine._human_uid_by_slot if u]
        for human_id in humans:
            engine.resident_store.get(human_id)["roster"]["driver"] = kind
        if raise_needs:
            h = engine.state.h_tensor
            h[engine._human_slot_for_id(humans[0]), cfg.THIRST] = 45.0
            h[engine._human_slot_for_id(humans[1]), cfg.HUNGER] = 45.0
        before = (runtime(engine).trips_done, runtime(engine).rations, runtime(engine).trip_timeouts, runtime(engine).trip_blocked)   # the runtime outlives reset_world
        trace = []
        for _ in range(ticks):
            engine.step()
            h = engine.state.h_tensor
            state = runtime(engine)
            trace.append(tuple((round(float(h[engine._human_slot_for_id(u), cfg.X]), 4), round(float(h[engine._human_slot_for_id(u), cfg.Y]), 4),
                                state.at_anchor.get(u), state.goal_key.get(u)) for u in humans))
        counters = tuple(now - was for now, was in zip((state.trips_done, state.rations, state.trip_timeouts, state.trip_blocked), before))
        return humans, trace, counters

    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()

    async def test_binding_driver_selects_the_kind(self):
        pin_anchor(self)                       # the default kind comes from EDEN_ROSTER_DRIVER; pin it
        self.assertEqual(driver_kind(None), "anchor")
        self.assertEqual(driver_kind({}), "anchor")
        self.assertEqual(driver_kind({"driver": "agent"}), "agent")
        self.assertEqual(driver_kind({"driver": "nonsense"}), "anchor")

    async def test_rules_agent_driver_reproduces_the_anchor_driver_tick_by_tick(self):
        _, anchor, anchor_counts = await self.run_world("anchor")
        humans, agent, agent_counts = await self.run_world("agent")
        self.assertEqual(len(anchor), len(agent))
        first = next((i for i, (a, b) in enumerate(zip(anchor, agent)) if a != b), None)
        if first is not None:
            diffs = [(humans[j], anchor[first][j], agent[first][j]) for j in range(len(humans)) if anchor[first][j] != agent[first][j]]
            self.fail(f"first difference at tick index {first}: {diffs[:3]}")
        self.assertEqual(anchor_counts, agent_counts)
        self.assertTrue(all(x != 0.0 or y != 0.0 for x, y, _, _ in anchor[-1]), "a dead or despawned resident reads (0, 0) in both runs and proves nothing")
        self.assertGreater(anchor_counts[0] + anchor_counts[1], 0, "the raised needs must cause a trip or a ration, or the test proves nothing")

    async def test_matrix_tier1_with_the_rules_prior_reproduces_the_anchor_driver(self):
        _, anchor, anchor_counts = await self.run_world("anchor")
        tier1 = MatrixTier1()
        humans, agent, agent_counts = await self.run_world("agent", tier1=tier1)
        first = next((i for i, (a, b) in enumerate(zip(anchor, agent)) if a != b), None)
        if first is not None:
            diffs = [(humans[j], anchor[first][j], agent[first][j]) for j in range(len(humans)) if anchor[first][j] != agent[first][j]]
            self.fail(f"first difference at tick index {first}: {diffs[:3]}")
        self.assertEqual(anchor_counts, agent_counts)
        self.assertGreater(tier1.decisions, len(humans), "the matrix must have been consulted more than once per resident (cadence)")
        driver = backend.engine.__dict__["_agent_driver"]
        self.assertEqual(driver.errors, 0)
        # cadence: far fewer decisions than resident-ticks
        self.assertLess(driver.decided, len(humans) * TICKS / 4)

    async def test_site_trip_op_starts_the_needs_loop_trip_for_an_agent_resident(self):
        await self.run_world("agent", ticks=5, raise_needs=False)
        engine = backend.engine
        human = next(u for u in engine._human_uid_by_slot if u)
        state = runtime(engine)
        state.trips.pop(human, None)
        before = state.trips_done
        ops = EngineRecordOps(engine)
        self.assertEqual(ops.op_site_trip(human, engine.tick, "mud"), {"ok": False, "reason": "bad_kind"})
        started = ops.op_site_trip(human, engine.tick, "water")
        self.assertEqual(started, {"ok": True, "trip": "water"})
        again = ops.op_site_trip(human, engine.tick, "food")
        self.assertEqual((again["ok"], again["reason"]), (False, "trip_active"))
        for _ in range(900):
            engine.step()
            if state.trips_done > before:
                break
        self.assertGreater(state.trips_done, before, "the trip started by the op must be walked and finished by the needs loop")

    async def test_an_attack_re_scores_the_victim_within_one_tick_while_a_calm_resident_keeps_its_period(self):
        await self.run_world("agent", ticks=40, raise_needs=False)
        engine = backend.engine
        driver = engine.__dict__["_agent_driver"]
        humans = [u for u in engine._human_uid_by_slot if u]
        victim, calm = humans[2], humans[3]
        h = engine.state.h_tensor
        for _ in range(3):
            engine.step()
        before = {u: driver.cache[u]["tick"] for u in (victim, calm)}
        h[engine._human_slot_for_id(victim), cfg.THREAT] = 80.0
        engine.step()
        self.assertGreaterEqual(driver.cache[victim]["tick"], before[victim] + 1, "a threat rise must re-score at once")
        self.assertLessEqual(abs(driver.cache[victim]["tick"] - int(engine.tick)), 1)
        calm_decisions = 0
        last = driver.cache[calm]["tick"]
        for _ in range(9):
            engine.step()
            if driver.cache[calm]["tick"] != last:
                calm_decisions += 1
                last = driver.cache[calm]["tick"]
        self.assertLessEqual(calm_decisions, 1, "a calm resident decides once per period, not every tick")
        # a sharp HP loss (an attack that does not show as threat yet) is an interrupt too
        h[engine._human_slot_for_id(victim), cfg.THREAT] = 0.0
        engine.step()
        engine.step()
        stamp = driver.cache[victim]["tick"]
        h[engine._human_slot_for_id(victim), cfg.HP] -= 30.0
        engine.step()
        self.assertGreater(driver.cache[victim]["tick"], stamp)
        status = driver.status()
        self.assertEqual((status["prior"], status["tier1"]), (100.0, "rules"))
        self.assertGreater(status["interrupts"], 0)

    async def test_with_the_prior_at_zero_the_matrix_choice_changes_the_macro(self):
        """Plumbing proof: a toy weight set (bias only, rising with the menu index) with the rules prior removed chooses the last *legal* macro; with the prior it
        chooses the rules macro."""
        await self.run_world("agent", ticks=3, raise_needs=False)
        engine = backend.engine
        from systems.roster.driver import current_routine, roster_of
        rows = []
        for slot, human_id in enumerate(engine._human_uid_by_slot):
            if not human_id:
                continue
            roster, resident = roster_of(engine, human_id)
            rows.append(Row(slot, human_id, roster, resident, current_routine(engine, human_id, resident), None))
        policy = matrix.MatrixPolicy.initial()
        for name in ("W", "U", "V", "b"):
            setattr(policy, name, torch.zeros_like(getattr(policy, name)))
        policy.b = torch.arange(matrix.K, dtype=policy.b.dtype)
        free = MatrixTier1(policy, prior_strength=0.0)
        got = free.decide(engine, rows)
        _, _, aff = free._context(engine)
        legal = aff.mask([r.human_id for r in rows])
        n_macro = len(matrix.MACRO_ACTIONS)
        for i, row in enumerate(rows):
            expected = [m for m in matrix.MACRO_ACTIONS if bool(legal[i, matrix.ACTION_INDEX[m]])][-1]
            self.assertEqual(got[row.human_id], expected)
        self.assertTrue(any(got[r.human_id] != rules_macro(r.routine, r.override) for r in rows), "the toy matrix must change at least one macro")
        held = MatrixTier1(policy, prior_strength=1.0).decide(engine, rows)
        self.assertEqual(held, {r.human_id: rules_macro(r.routine, r.override) for r in rows})


if __name__ == "__main__":
    unittest.main()
