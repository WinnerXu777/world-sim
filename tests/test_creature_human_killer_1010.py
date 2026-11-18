"""Real combat resolver + engine outcome hook + creature death scan attribution."""
import os
import unittest
from unittest import mock

import torch

from test_creatures_kernel import KernelFixture, HOME
from systems.creatures import kernel
from systems.combat.intents import CombatIntent
from systems.combat.resolver import resolve_human_attack_intents
import genesis_config as cfg


class HumanKillerTests(KernelFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        caches = mock.patch.dict(self.engine.__dict__, {"_creature_killers": {}, "_creature_killed": set()})
        caches.start()
        self.addCleanup(caches.stop)
        for slot in (0, 1):
            self.human(slot, *HOME)
            self.engine.state.h_tensor[slot, cfg.H_STAMINA] = 100
        human_mask, _, entity_mask = self.engine._current_masks()
        self.engine._assign_missing_ids(human_mask, entity_mask)
        # Attribution is exercised through the real hook; unrelated orchestration is isolated.
        orchestration = mock.patch.object(self.engine, "_orchestrate_combat_outcome")
        orchestration.start()
        self.addCleanup(orchestration.stop)

    def hit(self, victim, attackers=(0,), *, damage=20, walls=None, source="manual"):
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        pre_h, pre_m = h[:, cfg.HP].clone(), m[:, cfg.M_HP].clone()
        intents = [CombatIntent(source=source, action="attack", attacker_kind="human", attacker_slot=slot,
                                target_kind="entity", target_slot=victim,
                                target_id=self.engine._entity_uid_by_slot[victim]) for slot in attackers]
        result = resolve_human_attack_intents(intents, h, m, str(h.device), attack_damage=damage, walls=walls)
        self.engine._record_combat_outcomes(result, pre_h, pre_m)
        return result

    def kills(self):
        return [e for e in self.engine._pending_events if e["type"] == "creature_killed"]

    async def test_lethal_manual_and_rules_hit_names_stable_human_once(self):
        for source in ("manual", "rules"):
            victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=10, uid=f"victim:{source}")
            self.assertEqual(self.hit(victim, source=source)["resolved"], 1)
            before_h = self.engine.state.h_tensor.clone()
            before_m = self.engine.state.m_tensor.clone()
            kernel._scan_kills(self.engine)
            kernel._scan_kills(self.engine)
            events = [e for e in self.kills() if e["id"] == f"victim:{source}"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["killer_uid"], self.engine._human_uid_by_slot[0])
            self.assertTrue(torch.equal(before_h, self.engine.state.h_tensor))
            self.assertTrue(torch.equal(before_m, self.engine.state.m_tensor))

    async def test_nonlethal_then_environmental_death_has_no_killer(self):
        victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=100)
        self.assertEqual(self.hit(victim)["resolved"], 1)
        kernel._scan_kills(self.engine)
        self.assertEqual(self.kills(), [])
        self.assertEqual(self.engine._creature_killers, {})
        self.engine.state.m_tensor[victim, cfg.M_HP] = 0
        kernel._scan_kills(self.engine)
        self.assertIsNone(self.kills()[0]["killer_uid"])

    async def test_rejected_hit_does_not_claim_later_environmental_death(self):
        victim = self.spawn("boar", HOME[0] + 4, HOME[1], hp=10)
        wall = {"min": [HOME[0] + 1, HOME[1] - 10], "max": [HOME[0] + 3, HOME[1] + 10]}
        result = self.hit(victim, walls=[wall])
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["rejections"][0]["reason"], "blocked")
        self.assertEqual(float(self.engine.state.m_tensor[victim, cfg.M_HP]), 10)
        self.assertEqual(self.engine._creature_killers, {})
        self.engine.state.m_tensor[victim, cfg.M_HP] = 0
        kernel._scan_kills(self.engine)
        self.assertIsNone(self.kills()[0]["killer_uid"])

    async def test_two_attackers_preserve_resolver_first_intent_convention(self):
        victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=30)
        result = self.hit(victim, attackers=(1, 0))
        self.assertEqual(result["resolved"], 2)
        kernel._scan_kills(self.engine)
        self.assertEqual(len(self.kills()), 1)
        self.assertEqual(self.kills()[0]["killer_uid"], self.engine._human_uid_by_slot[1])

    async def test_recycled_slot_environmental_death_cannot_inherit_human(self):
        victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=10, uid="victim:old")
        self.hit(victim)
        self.manager.allocator.release([victim])
        replacement = self.spawn("boar", *HOME, hp=0, uid="victim:replacement")
        self.assertEqual(replacement, victim)
        kernel._scan_kills(self.engine)
        self.assertEqual([(e["id"], e["killer_uid"]) for e in self.kills()], [("victim:replacement", None)])

    async def test_recycled_slot_new_lethal_hit_gets_new_human(self):
        victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=10, uid="victim:old")
        self.hit(victim)
        self.manager.allocator.release([victim])
        replacement = self.spawn("boar", HOME[0] + 2, HOME[1], hp=10, uid="victim:new")
        self.assertEqual(replacement, victim)
        self.hit(replacement, attackers=(1,))
        kernel._scan_kills(self.engine)
        self.assertEqual([(e["id"], e["killer_uid"]) for e in self.kills()],
                         [("victim:new", self.engine._human_uid_by_slot[1])])

    async def test_creature_killer_path_still_names_creature_and_feeds_once(self):
        fox = self.spawn("fox", *HOME, hunger=70)
        rabbit = self.spawn("rabbit", HOME[0] + 2, HOME[1], hp=1)
        params, cols, _, _, _ = kernel.params(self.engine.state.m_tensor.device)
        p = params[[int(self.engine.state.m_tensor[fox, cfg.M_TYPE])]]
        kernel._attack(self.engine, torch.tensor([fox]), p, cols, torch.tensor([True]), torch.tensor([False]),
                       torch.tensor([], dtype=torch.long), torch.tensor([0]), torch.tensor([rabbit]), torch.tensor([0]))
        kernel._scan_kills(self.engine)
        fed = float(self.engine.state.m_tensor[fox, cfg.A_HUNGER])
        kernel._scan_kills(self.engine)
        self.assertEqual(len(self.kills()), 1)
        self.assertEqual(self.kills()[0]["killer_uid"], self.engine._entity_uid_by_slot[fox])
        self.assertLess(fed, 70)
        self.assertEqual(float(self.engine.state.m_tensor[fox, cfg.A_HUNGER]), fed)

    async def test_flag_off_does_not_record_human_or_run_kill_hook(self):
        victim = self.spawn("boar", HOME[0] + 2, HOME[1], hp=10)
        with mock.patch.dict(os.environ, {"EDEN_CREATURES": "0"}):
            self.assertEqual(self.hit(victim)["resolved"], 1)
            self.assertEqual(self.engine._creature_killers, {})
            self.assertEqual(kernel.step(self.engine), 0)
            self.assertEqual(self.kills(), [])


if __name__ == "__main__":
    unittest.main()
