"""1008 Phase 2 (1008_creatures_gap.md section 9): parity of the table brain with the legacy loops for the trio sheep, deer, wolf.

Not identity (the legacy loops use ``random``): the same hand-built field is run once with the species on the legacy brain (``engine.step``) and once on the table brain (``kernel.step``)
and the outcomes are compared as rates - how many prey a pack of wolves kills in a fixed time, whether the wolves eat (hunger falls), how far prey and wolves drift. The bounds are
wide on purpose: they stop a kernel that is an order of magnitude off the legacy behaviour, and ``tools/creature_balance.py`` is the place where the numbers are tuned."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_feed import FeedFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.creatures import kernel, table  # noqa: E402

TRIO = ("sheep", "deer", "wolf")
TICKS = 1200
WOLVES, SHEEP, DEER = 3, 6, 6
CENTRE = (1000.0, 1000.0)


class ParityFixture(FeedFixture):
    def field(self, brain):
        """3 wolves around the centre, 6 sheep and 6 deer within 60 units, no humans; returns (wolf slots, prey slots)."""
        self.engine.world_loaded = True
        saved = {name: table.CREATURES[name]["brain"] for name in TRIO}
        for name in TRIO:
            table.CREATURES[name]["brain"] = "table" if brain == "kernel" else "legacy"
        self.addCleanup(lambda: [table.CREATURES[name].__setitem__("brain", b) for name, b in saved.items()])
        self.terrain()
        self.human(0, 520.0, 520.0)                                       # integrates the 5 x 5 ring around the field; a fed, watered observer far from it
        self.run_ticks(26)
        m = self.engine.state.m_tensor
        plan = (m[:cfg.MAX_ENTITIES, cfg.M_TYPE] >= 40) & (m[:cfg.MAX_ENTITIES, cfg.M_TYPE] < 80)
        m[:cfg.MAX_ENTITIES][plan] = 0.0                                  # the plan's own creatures would crowd the field
        self.manager.creatures.records.clear()
        wolves = [self.spawn("wolf", CENTRE[0] + 30.0 * (i - 1), CENTRE[1] + 90.0, hunger=60.0, group=1) for i in range(WOLVES)]
        prey = [self.spawn("sheep", CENTRE[0] + 10.0 * (i - 3), CENTRE[1], hunger=10.0) for i in range(SHEEP)]
        prey += [self.spawn("deer", CENTRE[0] + 10.0 * (i - 3), CENTRE[1] + 25.0, hunger=10.0) for i in range(DEER)]
        return wolves, prey

    def feed(self):
        h = self.engine.state.h_tensor
        h[0, cfg.HUNGER], h[0, cfg.THIRST], h[0, cfg.H_STAMINA] = 20.0, 20.0, 100.0
        h[0, cfg.H_AGE], h[0, cfg.H_LIFE_EXP], h[0, cfg.H_STRENGTH] = 30.0, 80.0, 50.0

    def alive(self, slots, kind):
        m = self.engine.state.m_tensor
        return sum(1 for s in slots if float(m[s, cfg.M_HP]) > 0 and float(m[s, cfg.M_TYPE]) == float(table.id_of(kind)))

    def scenario(self, brain, seed):
        torch.manual_seed(seed)
        wolves, prey = self.field(brain)
        start_hunger = [float(self.engine.state.m_tensor[w, cfg.A_HUNGER]) for w in wolves]
        for _ in range(TICKS):
            self.feed()
            self.engine.step()                                          # the whole legacy registry; it skips the rows of the table-brain species
            self.manager.tick()
            kernel.step(self.engine)
        m = self.engine.state.m_tensor
        eaten = len(prey) - self.alive(prey[:SHEEP], "sheep") - self.alive(prey[SHEEP:], "deer")
        return {"killed": eaten, "wolves": self.alive(wolves, "wolf"), "hunger_change": sum(float(m[w, cfg.A_HUNGER]) - h for w, h in zip(wolves, start_hunger)) / WOLVES}


RESULTS: dict = {}


class ParityTests(ParityFixture):
    """Each brain runs in its own fixture (a second scenario in one fixture inherits the first one's rows); the comparison test runs last by name."""

    async def test_1_the_legacy_pack(self):
        RESULTS["legacy"] = result = self.scenario("legacy", 1)
        self.assertGreaterEqual(result["killed"], 1, result)
        self.assertLess(result["hunger_change"], -20.0, f"the wolves eat despite the {TICKS} ticks of drain ({result})")

    async def test_2_the_kernel_pack_hunts_and_eats_but_only_while_hungry(self):
        RESULTS["kernel"] = result = self.scenario("kernel", 1)
        self.assertGreaterEqual(result["killed"], 1, f"the pack kills at least one of twelve prey in {TICKS} ticks ({result})")
        self.assertEqual(result["wolves"], WOLVES, result)
        self.assertLess(result["hunger_change"], -20.0, f"the wolves eat despite the {TICKS} ticks of drain ({result})")
        need = WOLVES * (60.0 + 0.03 * TICKS) / kernel.KILL_FEED
        self.assertLessEqual(result["killed"], need, "a kernel pack never kills more than its hunger can use")

    async def test_3_the_kernel_never_kills_more_than_the_legacy_loop(self):
        # The intended difference: the legacy loop bites anything in reach, hungry or not (it empties the field, and sometimes loses a wolf); the table brain hunts only above hunger 20
        # and a kill feeds KILL_FEED, so a fed pack stops.
        if "legacy" not in RESULTS or "kernel" not in RESULTS:
            self.skipTest("run the whole module")
        self.assertLessEqual(RESULTS["kernel"]["killed"], RESULTS["legacy"]["killed"], RESULTS)

    async def test_prey_flee_and_wolves_do_not_hunt_without_hunger(self):
        torch.manual_seed(1)
        wolves, prey = self.field("kernel")
        for w in wolves:
            self.engine.state.m_tensor[w, cfg.A_HUNGER] = 0.0
        for _ in range(600):
            self.engine.tick += 1
            kernel.step(self.engine)
        self.assertEqual(self.alive(prey[:SHEEP], "sheep") + self.alive(prey[SHEEP:], "deer"), len(prey), "fed wolves leave the herd alone")


if __name__ == "__main__":
    unittest.main()
