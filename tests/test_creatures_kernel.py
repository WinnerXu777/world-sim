"""1008 Phase 2 step 4 (1008_creatures_gap.md sections 5 and 8): the creature behaviour kernel on hand-built worlds.

A real window engine, no chunks integrated: creature rows are allocated by hand under uids of the form ``c2_2:fauna:..`` (home = the centre of chunk (2, 2) = (640, 640)) and
``kernel.step`` is called once per tick with ``engine.tick`` advanced by the test. The legacy day is 2400 ticks (dawn 0-599, day 600-1199, dusk 1200-1799, night 1800-2399)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.creatures import kernel, table  # noqa: E402

HOME = (640.0, 640.0)
NIGHT, DAY = 1900, 700


class KernelFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_CREATURES": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(kernel.uninstall)
        kernel.install()
        self.count = 0
        self.engine.tick = NIGHT

    def spawn(self, species, x, y, group=0, hunger=0.0, hp=None, uid=None, **cols):
        row = table.CREATURES[species]
        self.count += 1
        uid = uid or f"c2_2:fauna:{species}{self.count}"
        columns = {cfg.M_HP: row["hp"] if hp is None else hp, cfg.SCALE: max(row["footprint"]) / 2.0, cfg.A_LIFE_EXP: 30.0, cfg.A_HUNGER: hunger,
                   cfg.A_AGGRESSION: row["aggro"], table.C_GROUP: group, **cols}
        (slot,) = self.manager.allocator.allocate([uid], [row["id"]], [x], [y], {c: [v] for c, v in columns.items()})
        self.manager.allocator.owned.discard(slot)
        return slot

    def human(self, slot, x, y, hp=100.0):
        self.place_human(slot, x, y)
        self.engine.state.h_tensor[slot, cfg.HP] = hp
        self.engine.state.h_tensor[slot, cfg.H_SPACE] = 0.0

    def pos(self, slot):
        m = self.engine.state.m_tensor
        return float(m[slot, cfg.CX]), float(m[slot, cfg.CY])

    def go(self, ticks, until=None):
        for _ in range(ticks):
            self.engine.tick += 1
            kernel.step(self.engine)
            if until is not None and until():
                return True
        return until is None


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class HookTests(KernelFixture):
    async def test_flag_off_the_kernel_does_nothing_and_the_legacy_mask_is_the_same_object(self):
        slot = self.spawn("boar", *HOME)
        before = self.engine.state.m_tensor[slot].clone()
        mask = torch.zeros(self.engine.state.m_tensor.shape[0], dtype=torch.bool)
        mask[slot] = True
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CREATURES")
            self.assertEqual(kernel.step(self.engine), 0)
            self.assertIs(kernel.legacy_rows(mask, self.engine.state.m_tensor), mask)
        self.assertTrue(torch.equal(self.engine.state.m_tensor[slot], before))

    async def test_flag_on_the_legacy_loops_leave_table_brain_rows_alone(self):
        boar = self.spawn("boar", *HOME)
        wolf = self.spawn("wolf", *HOME)
        mask = torch.zeros(self.engine.state.m_tensor.shape[0], dtype=torch.bool)
        mask[boar] = mask[wolf] = True
        out = kernel.legacy_rows(mask, self.engine.state.m_tensor)
        self.assertFalse(bool(out[boar]))
        self.assertTrue(bool(out[wolf]), "wolf keeps the legacy brain")

    async def test_the_legacy_move_loop_does_not_touch_a_table_brain_row(self):
        import instincts_and_tools as iat
        boar = self.spawn("boar", *HOME)
        m = self.engine.state.m_tensor
        a_mask = torch.zeros(m.shape[0], dtype=torch.bool)
        a_mask[boar] = True
        before = m[boar].clone()
        iat.animal_instinct_move({"a_mask": a_mask, "h_tensor_ref": self.engine.state.h_tensor}, m, "cpu")
        self.assertTrue(torch.equal(m[boar], before))
        iat.animal_instinct_predator_attack({"a_mask": a_mask, "h_mask": self.engine.state.h_tensor[:, cfg.TYPE] > 0}, m, self.engine.state.h_tensor, [0], [0], "cpu")
        self.assertTrue(torch.equal(m[boar], before))

    async def test_the_legacy_move_loop_still_moves_a_legacy_row(self):
        import instincts_and_tools as iat
        wolf = self.spawn("wolf", *HOME)
        m = self.engine.state.m_tensor
        a_mask = torch.zeros(m.shape[0], dtype=torch.bool)
        a_mask[wolf] = True
        before = self.pos(wolf)
        for _ in range(5):
            iat.animal_instinct_move({"a_mask": a_mask, "h_tensor_ref": self.engine.state.h_tensor}, m, "cpu")
        self.assertNotEqual(self.pos(wolf), before)

    async def test_the_boot_hook_is_registered_and_removed(self):
        from harness import engine_hooks as eh
        from simulation.dispatch import Dispatcher
        dispatch = Dispatcher()
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1", "EDEN_CREATURES": "1"}):
            kernel.uninstall()
            eh.install(dispatch)
            self.assertIn("harness_creatures", [n for n, _ in dispatch.step_hooks])
            names = [n for n, _ in dispatch.step_hooks]
            self.assertLess(names.index("harness_window"), names.index("harness_creatures"), "populate first, then act")
            eh.uninstall(dispatch)
            self.assertNotIn("harness_creatures", [n for n, _ in dispatch.step_hooks])
            self.assertNotIn(table.id_of("boar"), cfg.ANIMAL_MOVE_STEP)


class InstallTests(KernelFixture):
    async def test_install_adds_the_new_species_and_leaves_the_legacy_five(self):
        legacy = {name: dict(getattr(cfg, name)) for name in kernel.DICT_NAMES if name != "ANIMAL_PREY"}
        boar = table.id_of("boar")
        self.assertEqual(cfg.ANIMAL_MOVE_STEP[boar], table.CREATURES["boar"]["speed"]["walk"])
        self.assertEqual(cfg.ANIMAL_LIFE_EXP[boar], tuple(table.CREATURES["boar"]["life_exp"]))
        self.assertEqual(cfg.MAP_SCHEMA[boar]["label"], "boar")
        self.assertIn(table.id_of("rabbit"), cfg.ANIMAL_BASE_AGGRESSION)
        for name, before in legacy.items():
            for ident in (cfg.M_SHEEP, cfg.M_DEER, cfg.M_TIGER, cfg.M_WOLF, cfg.M_FISH):
                self.assertEqual(getattr(cfg, name).get(ident), before.get(ident))
        self.assertIn(table.id_of("goblin"), cfg.ANIMAL_PREY if table.prey_ids("goblin") else {table.id_of("goblin"): 1})
        self.assertIn(cfg.AGENT_TYPE_HUMAN, cfg.ANIMAL_PREY[table.id_of("giant_spider")], "'always' hunts humans")

    async def test_uninstall_removes_exactly_what_was_added(self):
        snapshot = {name: dict(getattr(cfg, name)) for name in kernel.DICT_NAMES}
        kernel.uninstall()
        self.assertNotIn(table.id_of("boar"), cfg.ANIMAL_SCALE)
        self.assertNotIn(table.id_of("boar"), cfg.MAP_SCHEMA)
        kernel.install()
        for name, before in snapshot.items():
            self.assertEqual(getattr(cfg, name), before)


class RngTests(unittest.TestCase):
    def test_the_hash_is_reproducible_uniform_and_independent_of_row_order(self):
        slots = torch.arange(1000)
        gens = torch.zeros(1000)
        a = kernel.unit(7, slots, gens, 1)
        self.assertTrue(torch.equal(a, kernel.unit(7, slots, gens, 1)))
        self.assertTrue(torch.equal(a.flip(0), kernel.unit(7, slots.flip(0), gens, 1)))
        self.assertTrue(bool((a >= 0).all() and (a < 1).all()))
        self.assertAlmostEqual(float(a.mean()), 0.5, delta=0.05)
        self.assertFalse(torch.equal(a, kernel.unit(8, slots, gens, 1)))
        self.assertFalse(torch.equal(a, kernel.unit(7, slots, gens, 2)))
        self.assertFalse(torch.equal(a, kernel.unit(7, slots, gens + 1, 1)))


class MovementTests(KernelFixture):
    async def test_a_wanderer_moves_stays_near_home_and_replays_exactly(self):
        paths = []
        for _ in range(2):
            self.engine.tick = NIGHT
            slot = self.spawn("goblin", *HOME)
            self.engine.state.m_tensor[slot, cfg.M_GEN] = 5.0              # the generation is part of the hash: the same row identity in both runs
            path = []
            for _ in range(300):
                self.go(1)
                path.append(self.pos(slot))
            paths.append(path)
            self.manager.allocator.release([slot])
        self.assertNotEqual(paths[0][0], paths[0][-1])
        self.assertTrue(all(dist(p, HOME) < table.CREATURES["goblin"]["territory"]["leash"] + 30 for p in paths[0]))
        self.assertEqual(paths[0], paths[1], "same seed, same slot, same tick: bit for bit")

    async def test_activity_follows_the_time_of_day(self):
        moved = {}
        for label, start in (("night", NIGHT), ("day", DAY)):
            slot = self.spawn("skeleton", *HOME)
            self.engine.tick = start
            ticks_moved = 0
            for _ in range(300):
                before = self.pos(slot)
                self.go(1)
                ticks_moved += self.pos(slot) != before
            moved[label] = ticks_moved
            self.manager.allocator.release([slot])
        self.assertGreater(moved["night"], moved["day"] * 2, moved)

    async def test_a_creature_beyond_its_leash_walks_home(self):
        leash = table.CREATURES["goblin"]["territory"]["leash"]
        slot = self.spawn("goblin", HOME[0] + leash + 60.0, HOME[1])
        start = dist(self.pos(slot), HOME)
        self.go(120)
        self.assertLess(dist(self.pos(slot), HOME), start - 20.0)

    async def test_a_group_pulls_together(self):
        slots = [self.spawn("goblin", HOME[0] + dx, HOME[1] + dy, group=77) for dx, dy in ((-120, 0), (120, 0), (0, 120))]
        spread = lambda: sum(dist(self.pos(a), self.pos(b)) for a in slots for b in slots)  # noqa: E731
        before = spread()
        self.go(200)
        self.assertLess(spread(), before * 0.8)

    async def test_dormant_rows_are_left_alone(self):
        slot = self.spawn("goblin", *HOME)
        dormant = torch.zeros(self.engine.state.m_tensor.shape[0], dtype=torch.bool)
        dormant[slot] = True
        self.engine._dormant_a = dormant
        self.addCleanup(lambda: setattr(self.engine, "_dormant_a", None))
        before = self.engine.state.m_tensor[slot].clone()
        self.go(50)
        self.assertTrue(torch.equal(self.engine.state.m_tensor[slot], before))

    async def test_the_creature_never_leaves_the_window_frame(self):
        slot = self.spawn("fox", -1270.0, HOME[1])
        self.human(0, -1275.0, HOME[1])                           # it flees east from the human, then west pressure cannot push it out either
        self.go(100)
        x0, y0, x1, y1 = kernel._limits()
        x, y = self.pos(slot)
        self.assertTrue(x0 <= x < x1 and y0 <= y < y1)


class FearAndHuntTests(KernelFixture):
    async def test_a_fox_flees_a_human(self):
        slot = self.spawn("fox", *HOME)
        self.human(0, HOME[0] + 30.0, HOME[1])
        start = dist(self.pos(slot), (HOME[0] + 30.0, HOME[1]))
        self.go(1)
        self.assertEqual(float(self.engine.state.m_tensor[slot, table.C_STATE]), float(table.STATES["flee"]))
        self.go(9)
        self.assertGreater(dist(self.pos(slot), (HOME[0] + 30.0, HOME[1])), start + 20.0)

    async def test_a_spider_always_hunts_a_human_a_goblin_only_when_hungry(self):
        spider = self.spawn("giant_spider", *HOME)
        self.human(0, HOME[0] + 60.0, HOME[1])
        h = self.engine.state.h_tensor
        self.assertTrue(self.go(200, until=lambda: float(h[0, cfg.HP]) < 100.0), "the spider reached and bit the human")
        self.assertEqual(float(h[0, cfg.THREAT]), 100.0)
        self.assertAlmostEqual(100.0 - float(h[0, cfg.HP]) - 18.0 * round((100.0 - float(h[0, cfg.HP])) / 18.0), 0.0, places=3, msg="whole bites of 18")
        self.manager.allocator.release([spider])
        h[0, cfg.HP] = 100.0
        goblin = self.spawn("goblin", *HOME, hunger=5.0)
        self.go(150)
        self.assertEqual(float(h[0, cfg.HP]), 100.0, "a fed goblin leaves the human alone")
        self.engine.state.m_tensor[goblin, cfg.A_HUNGER] = 80.0
        self.assertTrue(self.go(300, until=lambda: float(h[0, cfg.HP]) < 100.0), "a hungry goblin attacks")

    async def test_the_attack_cooldown_spaces_the_bites(self):
        self.spawn("giant_spider", HOME[0] + 5.0, HOME[1])
        self.human(0, *HOME)
        h = self.engine.state.h_tensor
        hp, bites = [], []
        for _ in range(120):
            before = float(h[0, cfg.HP])
            self.go(1)
            if float(h[0, cfg.HP]) < before:
                bites.append(self.engine.tick)
        gaps = [b - a for a, b in zip(bites, bites[1:])]
        self.assertGreaterEqual(len(bites), 3)
        self.assertTrue(all(g >= table.CREATURES["giant_spider"]["cooldown"] for g in gaps), gaps)

    async def test_a_boar_ignores_a_far_human_and_defends_when_cornered_or_hurt(self):
        boar = self.spawn("boar", *HOME)
        self.human(0, HOME[0] + 50.0, HOME[1])
        h = self.engine.state.h_tensor
        self.go(100)
        self.assertEqual(float(h[0, cfg.HP]), 100.0)
        self.human(0, *self.pos(boar))                                    # right on top of it
        self.human(0, self.pos(boar)[0] + 5.0, self.pos(boar)[1])
        self.assertTrue(self.go(100, until=lambda: float(h[0, cfg.HP]) < 100.0), "cornered")

    async def test_a_skeleton_never_gets_hungry_or_flees(self):
        slot = self.spawn("skeleton", *HOME, hunger=70.0, hp=3.0)
        self.human(0, HOME[0] + 20.0, HOME[1])
        self.go(30)
        self.assertEqual(float(self.engine.state.m_tensor[slot, cfg.A_HUNGER]), 0.0)
        self.assertNotEqual(float(self.engine.state.m_tensor[slot, table.C_STATE]), float(table.STATES["flee"]))

    async def test_a_fox_kills_a_rabbit_and_the_event_names_the_killer_once(self):
        fox = self.spawn("fox", *HOME, hunger=70.0)
        rabbit = self.spawn("rabbit", HOME[0] + 25.0, HOME[1], uid="c2_2:fauna:rabbit9")
        fox_uid = self.engine._entity_uid_by_slot[fox]
        m = self.engine.state.m_tensor
        def pinned():                                                     # the rabbit (a table-brain row too) would run from the fox: hold it still
            m[rabbit, cfg.CX], m[rabbit, cfg.CY] = HOME[0] + 25.0, HOME[1]
            return float(m[rabbit, cfg.M_HP]) <= 0.0
        self.assertTrue(self.go(600, until=pinned), "the fox caught the rabbit")
        self.go(5)
        events = [e for e in self.engine._pending_events if e["type"] == "creature_killed"]
        self.assertEqual(len(events), 1, "queued once even though the row stays dead for several ticks")
        self.assertEqual(events[0]["id"], "c2_2:fauna:rabbit9")
        self.assertEqual(events[0]["species"], "rabbit")
        self.assertEqual(events[0]["killer_uid"], fox_uid)
        self.assertEqual(len(events[0]["pos"]), 2)
        self.assertLess(float(m[fox, cfg.A_HUNGER]), 50.0, "a kill feeds the killer")

    async def test_a_creature_that_dies_of_other_causes_is_reported_without_a_killer(self):
        self.spawn("goblin", *HOME, hp=0.0, uid="c2_2:fauna:goblin_dead")
        self.go(1)
        events = [e for e in self.engine._pending_events if e["type"] == "creature_killed"]
        self.assertEqual([(e["id"], e["killer_uid"]) for e in events], [("c2_2:fauna:goblin_dead", None)])


if __name__ == "__main__":
    unittest.main()
