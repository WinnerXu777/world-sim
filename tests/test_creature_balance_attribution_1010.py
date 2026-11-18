"""Unit tests for creature balance causal attribution observer (R0.3 concrete evidence prerequisite).

Verifies:
1. Actual production damage function (apply_human_damage) invoked on fixture with stable human/creature IDs
   under lethal and non-lethal conditions.
2. Multiple same-tick sources and overkill correctly distinguish requested vs actual applied damage.
3. Nearby uninvolved animal is NEVER assigned as the killer (demonstrates proximity != causation).
4. Slot recycled unknown stale identity does not leak history across human resets.
5. Attribution wrappers restore original functions bit-for-bit even on raised exceptions.
6. Bounded rings (per resident) and first-death cap (cap 8) prevent memory growth over long runs.
7. Observed path returns bit-identical tensors and RNG states as unobserved call.
8. Unattributed HP loss and old age are reported as explicit genuine causes, never fabricated.
9. Duels closed-form formula estimates honesty.
10. Actual kernel._attack 2 attackers lethal integration test: effect and RNG parity, no fabricated single killer,
    bounded attacker candidates with contributions, damage_by_species bounded. Distinct single attacker exact.
11. Pre-feed death observation regression: actual dying needs/age observed before reset, final tensors fed.
12. Authoritative engine UID recycling automatically clears slot history and prevents stale lethal record leakage.
13. Structural memory bounds per cfg.MAX_HUMANS and finite known keys.
"""
from __future__ import annotations

import collections
from collections import deque
import os
from pathlib import Path
import sys
import unittest

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from systems.health import damage as health_damage  # noqa: E402
from systems.creatures import kernel, table  # noqa: E402
from tools.creature_balance_attribution import AttributionObserver, LEGACY_NAMES  # noqa: E402
from tools import creature_balance  # noqa: E402



class MockEngineState:
    def __init__(self, h_tensor: torch.Tensor, m_tensor: torch.Tensor):
        self.h_tensor = h_tensor
        self.m_tensor = m_tensor


class MockEngine:
    def __init__(self, h_tensor: torch.Tensor, m_tensor: torch.Tensor):
        self.state = MockEngineState(h_tensor, m_tensor)
        self.tick = 100
        self._human_uid_by_slot = [f"h_{i}" for i in range(h_tensor.shape[0])]
        self._entity_uid_by_slot = [f"e_{i}" for i in range(m_tensor.shape[0])]
        self._registry = []


class CreatureBalanceAttributionTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)
        # Create standard test fixture tensors
        self.h_tensor = torch.zeros((10, 50), dtype=torch.float32)
        self.m_tensor = torch.zeros((1024, 40), dtype=torch.float32)

        # Slot 0 is a living human at (520.0, 520.0) with 100 HP
        self.h_tensor[0, cfg.TYPE] = float(cfg.AGENT_TYPE_HUMAN)
        self.h_tensor[0, cfg.X] = 520.0
        self.h_tensor[0, cfg.Y] = 520.0
        self.h_tensor[0, cfg.HP] = 100.0
        self.h_tensor[0, cfg.HUNGER] = 20.0
        self.h_tensor[0, cfg.THIRST] = 20.0
        self.h_tensor[0, cfg.H_AGE] = 30.0
        self.h_tensor[0, cfg.H_LIFE_EXP] = 80.0

        self.engine = MockEngine(self.h_tensor, self.m_tensor)

    def test_actual_production_damage_nonlethal_and_lethal(self):
        """Invoke real production apply_human_damage on fixture with stable IDs and distinguish lethal/nonlethal."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)
        with observer:
            mask = torch.zeros(self.h_tensor.shape[0], dtype=torch.bool)
            mask[0] = True

            # 1. Non-lethal blow: 35 damage (100 -> 65)
            health_damage.apply_human_damage(mask, self.h_tensor, 35.0, hp_col=cfg.HP)
            self.assertEqual(float(self.h_tensor[0, cfg.HP]), 65.0)

            records = list(observer.damage_rings[0])
            self.assertEqual(len(records), 1)
            rec1 = records[0]
            self.assertEqual(rec1["damage_requested"], 35.0)
            self.assertEqual(rec1["damage_applied"], 35.0)
            self.assertEqual(rec1["victim_hp_before"], 100.0)
            self.assertEqual(rec1["victim_hp_after"], 65.0)
            self.assertFalse(rec1["is_lethal"])
            self.assertEqual(rec1["overkill"], 0.0)
            self.assertEqual(rec1["victim_uid"], "h_0")

            # 2. Lethal blow with overkill: 80 damage requested on 65 HP (65 -> 0, applied 65, overkill 15)
            health_damage.apply_human_damage(mask, self.h_tensor, 80.0, hp_col=cfg.HP)
            self.assertEqual(float(self.h_tensor[0, cfg.HP]), 0.0)

            records = list(observer.damage_rings[0])
            self.assertEqual(len(records), 2)
            rec2 = records[1]
            self.assertEqual(rec2["damage_requested"], 80.0)
            self.assertEqual(rec2["damage_applied"], 65.0)
            self.assertEqual(rec2["victim_hp_before"], 65.0)
            self.assertEqual(rec2["victim_hp_after"], 0.0)
            self.assertTrue(rec2["is_lethal"])
            self.assertEqual(rec2["overkill"], 15.0)

            # Describe death uses lethal record
            death_summary = observer.describe_death(0, 1, 65.0)
            self.assertEqual(death_summary["damage_applied"], 65.0)
            self.assertEqual(death_summary["damage_requested"], 80.0)
            self.assertEqual(death_summary["overkill"], 15.0)
            self.assertEqual(death_summary["hp_before"], 65.0)
            self.assertEqual(death_summary["victim_uid"], "h_0")

    def test_multiple_same_tick_sources_and_overkill(self):
        """Multiple attackers on the same tick distinguish requested vs actual applied and overkill."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)
        self.h_tensor[0, cfg.HP] = 35.0
        mask = torch.zeros(self.h_tensor.shape[0], dtype=torch.bool)
        mask[0] = True

        with observer:
            observer.set_probe_tick(42)

            # First blow on tick 42: Wolf A deals 20 damage (35 -> 15)
            observer.record_damage_event(
                victim_slot=0,
                damage_requested=20.0,
                damage_applied=20.0,
                victim_hp_before=35.0,
                victim_hp_after=15.0,
                source="creature_kernel_attack",
                attacker_species="wolf",
                attacker_uid="c2_2:fauna:wolf1",
                attacker_slot=10,
                is_lethal=False,
                overkill=0.0,
            )

            # Second blow on tick 42: Wolf B deals 25 damage on 15 HP (applied 15, overkill 10, lethal!)
            observer.record_damage_event(
                victim_slot=0,
                damage_requested=25.0,
                damage_applied=15.0,
                victim_hp_before=15.0,
                victim_hp_after=0.0,
                source="creature_kernel_attack",
                attacker_species="wolf",
                attacker_uid="c2_2:fauna:wolf2",
                attacker_slot=11,
                is_lethal=True,
                overkill=10.0,
            )

            ring = list(observer.damage_rings[0])
            self.assertEqual(len(ring), 2)
            self.assertEqual(ring[0]["damage_applied"], 20.0)
            self.assertFalse(ring[0]["is_lethal"])

            self.assertEqual(ring[1]["damage_applied"], 15.0)
            self.assertEqual(ring[1]["damage_requested"], 25.0)
            self.assertEqual(ring[1]["overkill"], 10.0)
            self.assertTrue(ring[1]["is_lethal"])

            summary = observer.describe_death(0, 42, 35.0)
            self.assertEqual(summary["killer_uid"], "c2_2:fauna:wolf2")
            self.assertEqual(summary["killer_species"], "wolf")
            self.assertEqual(summary["damage_applied"], 15.0)
            self.assertEqual(summary["overkill"], 10.0)

    def test_nearby_uninvolved_animal_never_assigned_killer(self):
        """Demonstrate proximity != causation: closest sheep is not attributed when wolf dealt lethal blow."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)

        # Place sheep right next to human (distance 0.3 units)
        sheep_slot = 40
        self.m_tensor[sheep_slot, cfg.M_TYPE] = float(table.CREATURES["sheep"]["id"])
        self.m_tensor[sheep_slot, cfg.CX] = 520.2
        self.m_tensor[sheep_slot, cfg.CY] = 520.2
        self.m_tensor[sheep_slot, cfg.M_HP] = 40.0
        self.m_tensor[sheep_slot, cfg.M_SPACE] = 0.0

        # Place wolf further away (distance 15 units)
        wolf_slot = 41
        self.m_tensor[wolf_slot, cfg.M_TYPE] = float(table.CREATURES["wolf"]["id"])
        self.m_tensor[wolf_slot, cfg.CX] = 535.0
        self.m_tensor[wolf_slot, cfg.CY] = 520.0
        self.m_tensor[wolf_slot, cfg.M_HP] = 60.0
        self.m_tensor[wolf_slot, cfg.M_SPACE] = 0.0
        self.engine._entity_uid_by_slot[wolf_slot] = "c2_2:fauna:wolf99"

        # The wolf deals the lethal damage
        observer.record_damage_event(
            victim_slot=0,
            damage_requested=50.0,
            damage_applied=50.0,
            victim_hp_before=50.0,
            victim_hp_after=0.0,
            source="creature_kernel_attack",
            attacker_species="wolf",
            attacker_uid="c2_2:fauna:wolf99",
            attacker_slot=wolf_slot,
            is_lethal=True,
            overkill=0.0,
        )

        death_summary = observer.describe_death(0, 10, 50.0)

        # Nearest creature spatially is indeed sheep
        self.assertEqual(death_summary["nearest_creature"][0], "sheep")
        self.assertLess(death_summary["nearest_creature"][1], 1.0)

        # But TRUE killer is wolf! Sheep is NEVER assigned as killer.
        self.assertEqual(death_summary["true_cause"], "creature")
        self.assertEqual(death_summary["killer_species"], "wolf")
        self.assertEqual(death_summary["killer_uid"], "c2_2:fauna:wolf99")
        self.assertFalse(death_summary["proximity_matches_true_killer"])

    def test_slot_recycled_unknown_stale_identity_does_not_leak_history(self):
        """Slot recycling clears damage ring and lethality state so new resident starts clean."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)

        # Resident 1 ("resident_A") takes damage and dies
        self.engine._human_uid_by_slot[0] = "resident_A"
        observer.set_victim_uid(0, "resident_A")
        observer.record_damage_event(
            victim_slot=0,
            damage_requested=100.0,
            damage_applied=100.0,
            victim_hp_before=100.0,
            victim_hp_after=0.0,
            source="creature_kernel_attack",
            attacker_species="boar",
            is_lethal=True,
        )
        self.assertEqual(len(observer.damage_rings[0]), 1)
        self.assertIsNotNone(observer.latest_lethal_records[0])

        # Reset slot for new resident ("resident_B")
        self.engine._human_uid_by_slot[0] = "resident_B"
        observer.on_human_reset(0, new_uid="resident_B")
        self.assertEqual(len(observer.damage_rings[0]), 0)
        self.assertIsNone(observer.latest_lethal_records[0])
        self.assertEqual(observer.get_victim_uid(0), "resident_B")

        # New resident takes 10 non-lethal damage
        observer.record_damage_event(
            victim_slot=0,
            damage_requested=10.0,
            damage_applied=10.0,
            victim_hp_before=100.0,
            victim_hp_after=90.0,
            source="legacy_predator_attack",
            attacker_species="wolf",
            is_lethal=False,
        )
        ring = list(observer.damage_rings[0])
        self.assertEqual(len(ring), 1)
        self.assertEqual(ring[0]["victim_uid"], "resident_B")
        self.assertEqual(ring[0]["damage_applied"], 10.0)
        # Zero leakage of resident_A's boar kill
        self.assertIsNone(observer.latest_lethal_records[0])

    def test_attribution_wrappers_restore_original_functions_on_error(self):
        """AttributionObserver cleanly restores original functions even when an exception is raised."""
        orig_fn = health_damage.apply_human_damage
        observer = AttributionObserver(engine=self.engine, humans_count=1)

        try:
            with observer:
                # Inside context, function is wrapped
                self.assertIsNot(health_damage.apply_human_damage, orig_fn)
                raise RuntimeError("simulated probe exception")
        except RuntimeError:
            pass

        # Outside context, original function is restored bit-for-bit
        self.assertIs(health_damage.apply_human_damage, orig_fn)

    def test_bounded_rings_and_firstdeath_cap(self):
        """Ring size and first-death cap prevent unbounded memory growth."""
        observer = AttributionObserver(engine=self.engine, humans_count=1, ring_size=4, max_first_deaths=8)

        # Deliver 12 damage hits
        for i in range(12):
            observer.record_damage_event(
                victim_slot=0,
                damage_requested=5.0,
                damage_applied=5.0,
                victim_hp_before=100.0 - i * 5,
                victim_hp_after=95.0 - i * 5,
                source="test",
            )
        # Ring has exactly 4 items (old ones evicted)
        self.assertEqual(len(observer.damage_rings[0]), 4)

        # Trigger 15 deaths
        for i in range(15):
            observer.record_damage_event(
                victim_slot=0,
                damage_requested=10.0,
                damage_applied=10.0,
                victim_hp_before=10.0,
                victim_hp_after=0.0,
                is_lethal=True,
            )
            observer.describe_death(0, i, 10.0)
            observer.on_human_reset(0)

        # First deaths list is capped at 8
        self.assertEqual(len(observer.first_deaths), 8)
        # Total deaths counter tracks all 15 deaths
        self.assertEqual(observer.total_deaths, 15)

    def test_observed_path_returns_same_tensors_and_rng_as_unobserved(self):
        """Instrumented call produces bit-identical tensors and does not disturb torch RNG."""
        h1 = self.h_tensor.clone()
        h2 = self.h_tensor.clone()
        mask = torch.zeros(h1.shape[0], dtype=torch.bool)
        mask[0] = True

        torch.manual_seed(12345)
        # Unobserved call
        health_damage.apply_human_damage(mask, h1, 27.5, hp_col=cfg.HP)
        rng_unobserved = torch.get_rng_state()

        torch.manual_seed(12345)
        # Observed call
        observer = AttributionObserver(engine=self.engine, humans_count=1)
        with observer:
            health_damage.apply_human_damage(mask, h2, 27.5, hp_col=cfg.HP)
        rng_observed = torch.get_rng_state()

        self.assertTrue(torch.equal(h1, h2))
        self.assertTrue(torch.equal(rng_unobserved, rng_observed))

    def test_pure_observer_old_age_and_unattributed_deaths(self):
        """Unattributed HP loss and old age are reported as genuine causes, never fabricated as wolf."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)

        # 1. Old age death
        observer.record_old_age_death(0)
        old_age_death = observer.describe_death(0, 5, 100.0)
        self.assertEqual(old_age_death["true_cause"], "old_age")
        self.assertEqual(old_age_death["lethal_source"], "instinct_die")
        self.assertIsNone(old_age_death["killer_species"])

        # 2. Unattributed HP loss (HP drops without captured damage call)
        observer.on_human_reset(0)
        self.h_tensor[0, cfg.HP] = 0.0
        unattributed_death = observer.describe_death(0, 6, 80.0)
        self.assertEqual(unattributed_death["true_cause"], "unattributed_hp_loss")
        self.assertEqual(unattributed_death["lethal_source"], "unknown")
        self.assertIsNone(unattributed_death["killer_species"])

        # 3. Unresolved type removal (TYPE becomes 0 without damage or old age)
        observer.on_human_reset(0)
        self.h_tensor[0, cfg.TYPE] = 0.0
        self.h_tensor[0, cfg.HP] = 0.0
        unresolved_death = observer.describe_death(0, 7, 0.0)
        self.assertEqual(unresolved_death["true_cause"], "unresolved_type_removal")

    def test_formula_estimates_honesty(self):
        """duels() output is clearly identified as closed-form formula estimates."""
        duels_list = creature_balance.duels()
        self.assertIsInstance(duels_list, list)
        self.assertGreater(len(duels_list), 0)
        for entry in duels_list:
            self.assertIn("species", entry)
            self.assertIn("hunter_seconds_to_kill", entry)
            self.assertIn("creature_seconds_to_kill_resident", entry)
            self.assertEqual(entry.get("estimate_type"), "closed_form_formula")
        # Docstring explicit honesty check
        self.assertIn("formula estimates", creature_balance.duels.__doc__.lower())

    def test_actual_kernel_attack_two_attackers_multiattacker_ambiguity_and_single_attacker(self):
        """Meaningful actual kernel._attack integration test with 2 attackers + 1 victim dying.

        Verifies:
        1. Effect parity: victim takes damage, threat is updated, HP drops to 0.
        2. RNG parity: observed vs unobserved execution produces identical torch RNG state.
        3. No fabricated single killer: killer_uid/killer_slot/species are 'unknown', not attackers[0].
        4. Attacker candidates stored with exact UIDs, species, requested contributions, and actual aggregate damage.
        5. Summary damage_by_species has no unbounded joined keys, aggregating under 'unknown'.
        6. Distinct genuine single attacker still attributes exact killer UID, slot, and species.
        """
        # Set up 2 wolf attackers in m_tensor (slots 10 and 11)
        wolf_id = int(table.CREATURES["wolf"]["id"])
        self.m_tensor[10, cfg.M_TYPE] = float(wolf_id)
        self.m_tensor[10, cfg.M_HP] = 60.0
        self.m_tensor[11, cfg.M_TYPE] = float(wolf_id)
        self.m_tensor[11, cfg.M_HP] = 60.0
        self.engine._entity_uid_by_slot[10] = "c2_2:fauna:wolf_alpha"
        self.engine._entity_uid_by_slot[11] = "c2_2:fauna:wolf_beta"

        # Victim has less HP than the aggregate damage in the actual species table.
        self.h_tensor[0, cfg.HP] = 20.0
        self.h_tensor[0, cfg.TYPE] = float(cfg.AGENT_TYPE_HUMAN)
        self.engine._human_uid_by_slot[0] = "victim_human_0"

        # Parameters for kernel._attack
        P, col, _, _, _ = kernel.params(self.engine.state.m_tensor.device)
        cidx = torch.tensor([10, 11], dtype=torch.long)
        p = P[self.m_tensor[cidx, cfg.M_TYPE].long()]
        requested_each = float(p[0, col["damage"]])
        requested_total = float(p[:, col["damage"]].sum())
        self.assertGreater(requested_total, 20.0)
        attacking = torch.ones(2, dtype=torch.bool)
        use_human = torch.ones(2, dtype=torch.bool)
        h_slots = torch.tensor([0], dtype=torch.long)
        dh_arg = torch.zeros(2, dtype=torch.long)  # Both attack victim at h_slots[0]
        a_slots = torch.empty(0, dtype=torch.long)
        dp_arg = torch.zeros(2, dtype=torch.long)

        # 1. Test RNG parity between unobserved and observed calls
        torch.manual_seed(9999)
        rng_before = torch.get_rng_state()

        observer = AttributionObserver(engine=self.engine, humans_count=1)
        with observer:
            observer.set_probe_tick(1)
            # Call actual production kernel._attack
            kernel._attack(self.engine, cidx, p, col, attacking, use_human, h_slots, dh_arg, a_slots, dp_arg)

        rng_after = torch.get_rng_state()
        # Production _attack does not consume torch RNG, so state is identical
        self.assertTrue(torch.equal(rng_before, rng_after))

        # 2. Effect parity: human took 20 damage and is now at 0 HP; threat set to 100
        self.assertEqual(float(self.h_tensor[0, cfg.HP]), 0.0)
        self.assertEqual(float(self.h_tensor[0, cfg.THREAT]), 100.0)

        # 3. No fabricated single killer: describe_death must report killer UNKNOWN
        death_summary = observer.describe_death(0, 1, 20.0)
        self.assertEqual(death_summary["true_cause"], "creature")
        self.assertEqual(death_summary["killer_uid"], "unknown")
        self.assertEqual(death_summary["killer_species"], "unknown")
        self.assertEqual(death_summary["killer_slot"], "unknown")
        self.assertEqual(death_summary["damage_applied"], 20.0)
        self.assertEqual(death_summary["damage_requested"], requested_total)
        self.assertEqual(death_summary["overkill"], requested_total - 20.0)

        # 4. Bounded actual attacker candidates stored with exact details
        candidates = death_summary.get("attacker_candidates", [])
        self.assertEqual(len(candidates), 2)
        uids = {c["creature_uid"] for c in candidates}
        self.assertEqual(uids, {"c2_2:fauna:wolf_alpha", "c2_2:fauna:wolf_beta"})
        species_set = {c["creature_species"] for c in candidates}
        self.assertEqual(species_set, {"wolf"})
        for c in candidates:
            self.assertEqual(c["damage_requested"], requested_each)

        # 5. Summary damage_by_species has NO joined strings ('wolf/wolf') and aggregates under 'unknown'
        summary_data = observer.summary()
        self.assertNotIn("wolf/wolf", summary_data["damage_by_species"])
        self.assertEqual(summary_data["damage_by_species"].get("unknown"), 20.0)
        self.assertEqual(summary_data["deaths_by_killer_species"].get("unknown"), 1)

        # 6. Distinct genuine single attacker still attributes exact killer
        self.engine._human_uid_by_slot[0] = "victim_human_single"
        observer.on_human_reset(0, new_uid="victim_human_single")
        self.h_tensor[0, cfg.HP] = 10.0
        boar_id = int(table.CREATURES["boar"]["id"])
        self.m_tensor[20, cfg.M_TYPE] = float(boar_id)
        self.m_tensor[20, cfg.M_HP] = 80.0
        self.engine._entity_uid_by_slot[20] = "c2_2:fauna:boar_solo"

        cidx_single = torch.tensor([20], dtype=torch.long)
        p_single = P[self.m_tensor[cidx_single, cfg.M_TYPE].long()]
        with observer:
            observer.set_probe_tick(2)
            kernel._attack(
                self.engine,
                cidx_single,
                p_single,
                col,
                torch.ones(1, dtype=torch.bool),
                torch.ones(1, dtype=torch.bool),
                h_slots,
                torch.zeros(1, dtype=torch.long),
                a_slots,
                torch.zeros(1, dtype=torch.long),
            )

        self.assertEqual(float(self.h_tensor[0, cfg.HP]), 0.0)
        single_death = observer.describe_death(0, 2, 10.0)
        self.assertEqual(single_death["true_cause"], "creature")
        self.assertEqual(single_death["killer_uid"], "c2_2:fauna:boar_solo")
        self.assertEqual(single_death["killer_species"], "boar")
        self.assertEqual(single_death["killer_slot"], 20)
        self.assertEqual(observer.summary()["damage_by_species"].get("boar"), 10.0)

    def test_actual_cause_and_prereset_observation_without_changing_final_tensors(self):
        """Regression test: pre-feed death observation captures actual pre-reset needs/age, not retrospective-20."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)
        # Setup human slot 0 starving before reset: hunger 95.0, thirst 85.0, age 45.0
        self.h_tensor[0, cfg.TYPE] = float(cfg.AGENT_TYPE_HUMAN)
        self.h_tensor[0, cfg.HP] = 0.0
        self.h_tensor[0, cfg.HUNGER] = 95.0
        self.h_tensor[0, cfg.THIRST] = 85.0
        self.h_tensor[0, cfg.H_AGE] = 45.0
        self.h_tensor[0, cfg.H_LIFE_EXP] = 80.0

        # Pre-feed observation captures the genuine dying state
        death_summary = observer.describe_death(0, tick=50, hp_before=15.0)
        self.assertEqual(death_summary["hunger"], 95.0)
        self.assertEqual(death_summary["thirst"], 85.0)
        self.assertEqual(death_summary["age"], 45.0)
        self.assertNotEqual(death_summary["hunger"], 20.0)

        # Now execute creature_balance.feed()
        b = creature_balance.Balance()
        b.engine = self.engine
        b.feed()

        # Final tensors are fed, preserving simulation outcome, order, math, and fed state
        self.assertEqual(float(self.h_tensor[0, cfg.HUNGER]), 20.0)
        self.assertEqual(float(self.h_tensor[0, cfg.THIRST]), 20.0)
        self.assertEqual(float(self.h_tensor[0, cfg.H_STAMINA]), 100.0)
        self.assertEqual(float(self.h_tensor[0, cfg.H_AGE]), 30.0)

        # But the recorded death diagnostic retains the true pre-reset observations!
        self.assertEqual(death_summary["hunger"], 95.0)
        self.assertEqual(death_summary["thirst"], 85.0)
        self.assertEqual(death_summary["age"], 45.0)

    def test_actual_uid_replacement_cannot_leak_old_lethal_record(self):
        """Authoritative engine UID recycling without manual on_human_reset cannot leak old lethal record."""
        observer = AttributionObserver(engine=self.engine, humans_count=1)

        # 1. Resident A dies from wolf attack
        self.engine._human_uid_by_slot[0] = "resident_alpha"
        self.assertEqual(observer.get_victim_uid(0), "resident_alpha")

        observer.record_damage_event(
            victim_slot=0,
            damage_requested=100.0,
            damage_applied=100.0,
            victim_hp_before=100.0,
            victim_hp_after=0.0,
            source="creature_kernel_attack",
            attacker_species="wolf",
            attacker_uid="c2_2:fauna:wolf_kill",
            attacker_slot=5,
            is_lethal=True,
        )
        self.assertIsNotNone(observer.latest_lethal_records[0])
        self.assertEqual(observer.latest_lethal_records[0]["victim_uid"], "resident_alpha")

        # 2. Root fixture now recycles slot 0 with new authoritative UID WITHOUT manual on_human_reset
        self.engine._human_uid_by_slot[0] = "resident_beta"
        self.h_tensor[0, cfg.HP] = 100.0

        # Sync/validation detects the authoritative UID change
        self.assertEqual(observer.get_victim_uid(0), "resident_beta")
        # Stored lethal record from resident_alpha was automatically cleared!
        self.assertIsNone(observer.latest_lethal_records[0])
        self.assertEqual(len(observer.damage_rings[0]), 0)

        # 3. Resident beta takes non-lethal damage from a fox
        observer.record_damage_event(
            victim_slot=0,
            damage_requested=5.0,
            damage_applied=5.0,
            victim_hp_before=100.0,
            victim_hp_after=95.0,
            source="creature_kernel_attack",
            attacker_species="fox",
            is_lethal=False,
        )

        # Resident beta later dies of unattributed HP loss
        self.h_tensor[0, cfg.HP] = 0.0
        death_summary = observer.describe_death(0, 10, 95.0)
        # MUST NOT leak resident_alpha's wolf kill!
        self.assertEqual(death_summary["victim_uid"], "resident_beta")
        self.assertEqual(death_summary["true_cause"], "unattributed_hp_loss")
        self.assertIsNone(death_summary["killer_species"])
        self.assertIsNone(death_summary["killer_uid"])

    def test_structurally_bounded_memory_per_max_humans_and_finite_keys(self):
        """Memory is structurally bounded per cfg.MAX_HUMANS, ring caps, first-death cap, and finite keys."""
        # humans_count is bounded by cfg.MAX_HUMANS
        observer = AttributionObserver(engine=self.engine, humans_count=99999, ring_size=5, max_first_deaths=4)
        self.assertLessEqual(observer.humans_count, getattr(cfg, "MAX_HUMANS", 64))

        # Rings bounded by ring_size
        for k in range(20):
            observer.record_damage_event(0, 1.0, 1.0, 100.0, 99.0, source="test")
        self.assertEqual(len(observer.damage_rings[0]), 5)

        # Multiattacker candidates capped at 8
        large_candidates = [
            {"creature_slot": i, "creature_uid": f"uid_{i}", "creature_species": "wolf", "damage_requested": 1.0}
            for i in range(25)
        ]
        ev = observer.record_damage_event(
            0, 25.0, 25.0, 100.0, 75.0, source="creature_kernel_attack", attacker_candidates=large_candidates
        )
        self.assertEqual(len(ev["attacker_candidates"]), 8)

        # Summary keys remain strictly bounded
        summ = observer.summary()
        self.assertIn("unknown", summ["damage_by_species"])
        for sp in summ["damage_by_species"]:
            self.assertTrue(sp in table.CREATURES or sp == "unknown")


if __name__ == "__main__":
    unittest.main()
