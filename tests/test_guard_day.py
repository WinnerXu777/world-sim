"""EDEN_DEFEND pass on the real engine (the starter village, agent residents): who opens a post over whom, the errand, the hook through the real resolver, the answer to a blow, expiry, needs, dormancy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from systems.actions import guard_day
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.combat import modifiers
from systems.combat.intents import CombatIntent
from systems.combat.resolver import resolve_human_attack_intents
from systems.guard import GUARD_TICKS, TAKE, runtime


class Village(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    FLAGS = {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_DEFEND": "1"}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", self.FLAGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(modifiers.set_modifier, None)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_dormant_h", None)
        self.addCleanup(self.engine.__dict__.pop, "_dormant_h", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.a, self.b, self.c = self.humans[0], self.humans[1], self.humans[2]       # guard, charge, attacker
        for index, other in enumerate(self.humans[3:]):
            slot = self.engine._human_slot_for_id(other)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 3000.0 + 700.0 * index, 3000.0
        for human_id in self.humans:
            self.traits(human_id, protectiveness=0.1, aggression=0.2)
            self.engine.resident_store.get(human_id)["relationships"] = {}
            self.engine.resident_store.get(human_id)["occupation"] = {"kind": "gatherer"}
            slot = self.engine._human_slot_for_id(human_id)
            self.h[slot, cfg.HUNGER], self.h[slot, cfg.THIRST], self.h[slot, cfg.THREAT], self.h[slot, cfg.HP] = 10.0, 10.0, 0.0, 100.0
        self.place(self.a, 0.0)
        self.place(self.b, 8.0)
        self.place(self.c, 16.0)
        self.tick = 600
        self.book = runtime.of(self.driver.runner(self.engine).services)

    def place(self, human_id, dx):
        base = self.engine._human_slot_for_id(self.humans[0])
        slot = self.engine._human_slot_for_id(human_id)
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = self.h[base, cfg.X] + dx, self.h[base, cfg.Y] if slot != base else self.h[base, cfg.Y]

    def traits(self, human_id, **values):
        record = self.engine.resident_store.get(human_id)
        base = dict(((record.get("personality") or {}).get("traits")) or {})
        record["personality"] = {**(record.get("personality") or {}), "traits": {**base, **values}}

    def relate(self, owner, other, closeness):
        self.engine.resident_store.get(owner)["relationships"][other] = {"kind": "known", "closeness": closeness, "last_seen_tick": 0, "tags": ["known"], "tag_meta": {}}

    def threaten(self, human_id, value=60.0):
        self.h[self.engine._human_slot_for_id(human_id), cfg.THREAT] = value

    def step(self):
        self.engine.tick = self.tick                      # the runner stamps posts with the engine's tick
        guard_day.step(self.driver, self.engine, self.tick)

    def open_post(self):
        """The kin rule: a protective, fond guard goes to the threatened charge, and in reach opens the post."""
        self.traits(self.a, protectiveness=0.9)
        self.relate(self.a, self.b, 0.8)
        self.threaten(self.b)
        self.step()
        self.assertEqual(self.driver.ladder.errands[self.a].purpose, "guard")
        self.driver.ladder.arrive(self.driver, self.engine, self.a, self.tick)
        return self.book.of_guard(self.a)


class Open(Village):
    async def test_a_protective_resident_guards_the_one_it_holds_dear_when_they_are_under_threat(self):
        post = self.open_post()
        self.assertEqual((post.kind, post.charge), ("person", self.b))
        self.assertEqual(self.driver.ladder.errands[self.a].note, "held")
        self.assertEqual(self.driver.ladder.errands[self.a].expires, post.until)
        self.assertEqual(post.until, self.tick + GUARD_TICKS)

    async def test_the_hook_is_installed_and_only_by_the_flag(self):
        self.step()
        self.assertTrue(getattr(modifiers.COMBAT_MODIFIER, "guard", False))

    async def test_an_authority_guards_a_resident_it_does_not_distrust_a_stranger_does_not(self):
        self.threaten(self.b)
        self.step()
        self.assertNotIn(self.a, self.driver.ladder.errands)                                # nobody is protective or an authority
        self.engine.resident_store.get(self.a)["occupation"] = {"kind": "guard"}
        self.step()
        self.assertEqual(self.driver.ladder.errands[self.a].target, self.b)

    async def test_nobody_under_threat_means_no_post(self):
        self.traits(self.a, protectiveness=0.9)
        self.relate(self.a, self.b, 0.8)
        self.step()
        self.assertEqual(self.book.posts, {})
        self.assertNotIn(self.a, self.driver.ladder.errands)

    async def test_a_hungry_or_hurt_resident_does_not_take_a_post(self):
        self.traits(self.a, protectiveness=0.9)
        self.relate(self.a, self.b, 0.8)
        self.threaten(self.b)
        self.h[self.engine._human_slot_for_id(self.a), cfg.HUNGER] = 80.0
        self.step()
        self.assertNotIn(self.a, self.driver.ladder.errands)
        self.h[self.engine._human_slot_for_id(self.a), cfg.HUNGER] = 10.0
        self.h[self.engine._human_slot_for_id(self.a), cfg.HP] = 20.0
        self.step()
        self.assertNotIn(self.a, self.driver.ladder.errands)

    async def test_flag_off_installs_nothing_and_opens_nothing(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_DEFEND": ""}):
            self.traits(self.a, protectiveness=0.9)
            self.relate(self.a, self.b, 0.8)
            self.threaten(self.b)
            self.step()
        self.assertIsNone(modifiers.COMBAT_MODIFIER)
        self.assertEqual(self.book.posts, {})
        self.assertNotIn(self.a, self.driver.ladder.errands)


class Tend(Village):
    async def test_the_post_expires_and_releases_the_guard(self):
        post = self.open_post()
        self.threaten(self.b, 0.0)                                                        # (while the threat lasts, the rules post a new watch)
        self.tick = post.until
        self.step()
        self.assertEqual(post.status, "closed")
        self.assertEqual(post.reason, "expired")
        self.assertNotIn(self.a, self.driver.ladder.errands)

    async def test_hunger_calls_the_guard_off_so_it_never_starves_on_watch(self):
        post = self.open_post()
        self.h[self.engine._human_slot_for_id(self.a), cfg.HUNGER] = 75.0
        self.tick += 1
        self.step()
        self.assertEqual(post.reason, "needs")
        self.assertNotIn(self.a, self.driver.ladder.errands)

    async def test_a_downed_charge_or_guard_closes_it(self):
        post = self.open_post()
        self.h[self.engine._human_slot_for_id(self.b), cfg.HP] = 0.0
        self.tick += 1
        self.step()
        self.assertEqual(post.reason, "charge_gone")

    async def test_a_dormant_guard_loses_its_post(self):
        post = self.open_post()
        mask = torch.zeros(len(self.engine._human_uid_by_slot), dtype=torch.bool)
        mask[self.engine._human_slot_for_id(self.a)] = True
        self.engine._dormant_h = mask
        self.tick += 1
        self.step()
        self.assertEqual(post.reason, "dormant")

    async def test_a_post_opened_by_the_verb_gets_a_holding_errand(self):
        self.driver.ladder.errands.clear()
        self.engine.tick = self.tick
        runner = self.driver.runner(self.engine)
        result = runner.run(self.a, "defend", {"target": self.b}, proposer="rules:test")
        self.assertTrue(result.ok, result.code)
        self.tick = 610
        self.step()
        errand = self.driver.ladder.errands[self.a]
        self.assertEqual((errand.purpose, errand.target, errand.note), ("guard", self.b, "held"))

    async def test_a_place_post_follows_the_place_and_closes_when_it_is_lost(self):
        self.engine.tick = self.tick
        runner = self.driver.runner(self.engine)
        anchor = next(iter(runner.services.anchors(self.a).values()))
        self.place(self.a, 0.0)
        slot = self.engine._human_slot_for_id(self.a)
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = float(anchor.x), float(anchor.y)
        result = runner.run(self.a, "defend", {"place": anchor.id}, proposer="rules:test")
        self.assertTrue(result.ok, result.code)
        self.tick = 610
        self.step()
        post = self.book.of_guard(self.a)
        self.assertEqual(post.xy, (float(anchor.x), float(anchor.y)))
        self.assertEqual(self.driver.ladder.errands[self.a].purpose, "guard_place")
        post.charge = "gone:nowhere"
        self.tick += 1
        self.step()
        self.assertEqual(post.reason, "lost")


class Blows(Village):
    def attack(self, attacker, target):
        slot_a, slot_t = self.engine._human_slot_for_id(attacker), self.engine._human_slot_for_id(target)
        self.h[:, cfg.H_STAMINA] = 100.0
        intent = CombatIntent(source="sim", action="attack", attacker_kind="human", attacker_slot=slot_a, target_kind="human", target_slot=slot_t, target_id=target)
        resolve_human_attack_intents([intent], self.h, self.engine.state.m_tensor, "cpu", walls=[], attack_range=cfg.ATTACK_RANGE * 4)

    async def test_the_guard_takes_the_blow_and_the_charge_does_not(self):
        self.open_post()
        slot_a, slot_b = self.engine._human_slot_for_id(self.a), self.engine._human_slot_for_id(self.b)
        before = float(self.h[slot_a, cfg.HP]), float(self.h[slot_b, cfg.HP])
        self.attack(self.c, self.b)
        self.assertEqual(float(self.h[slot_b, cfg.HP]), before[1])
        self.assertLess(float(self.h[slot_a, cfg.HP]), before[0])
        self.assertEqual(len(self.book.blows), 1)
        self.assertEqual(self.book.blows[0].attacker, self.c)

    async def test_a_gentle_guard_warns_first_then_attacks_if_the_attacker_strikes_again(self):
        self.open_post()
        self.attack(self.c, self.b)
        self.tick = 610
        self.step()
        self.assertEqual(self.driver.routed["guard.warn:ok"], 1)
        self.assertEqual(self.driver.routed["guard.attack:ok"], 0)
        self.tick = 920
        self.engine.tick = self.tick
        self.h[self.engine._human_slot_for_id(self.a), cfg.HP] = 100.0
        self.attack(self.c, self.b)
        self.step()
        self.assertEqual(self.driver.routed["guard.attack:ok"], 1)

    async def test_a_fierce_guard_attacks_at_once(self):
        self.traits(self.a, aggression=0.9)
        self.open_post()
        self.attack(self.c, self.b)
        self.tick = 610
        self.step()
        self.assertEqual(self.driver.routed["guard.attack:ok"], 1)
        self.assertEqual(self.driver.routed["guard.warn:ok"], 0)

    async def test_an_old_blow_is_not_answered(self):
        self.traits(self.a, aggression=0.9)
        self.open_post()
        self.attack(self.c, self.b)
        self.tick = 900
        self.step()
        self.assertEqual(self.driver.routed["guard.attack:ok"], 0)
        self.assertEqual(self.book.answered, len(self.book.blows))


if __name__ == "__main__":
    unittest.main()
