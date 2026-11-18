"""EDEN_DEFEND (defend Phase 0): the guard book, the combat hook on tensors and through the real resolver, the ``defend`` verb on the synthetic Scene, the flag-off behaviour."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

import torch

import genesis_config as cfg
from driver_pin import pin_anchor
from systems.combat import modifiers
from systems.combat.intents import CombatIntent
from systems.combat.resolver import resolve_human_attack_intents
from systems.guard import GUARD_RADIUS, GUARD_TICKS, MIN_HP, TAKE, enabled, modifier
from systems.guard.book import GuardBook
from test_actions_runner import Scene, setrow


class Book(unittest.TestCase):
    def test_one_post_per_guard_and_close_frees_it(self):
        book = GuardBook()
        first = book.open("g", "person", "c", 10, 100)
        self.assertIsNotNone(first)
        self.assertIsNone(book.open("g", "person", "d", 11, 100))
        self.assertEqual([p.id for p in book.for_charge("c")], [first.id])
        self.assertEqual(book.of_guard("g").id, first.id)
        self.assertIsNotNone(book.close(first.id, "expired", 100))
        self.assertIsNone(book.close(first.id, "expired", 101))
        self.assertIsNone(book.of_guard("g"))
        self.assertIsNotNone(book.open("g", "person", "d", 102, 200))
        self.assertEqual(book.counts["opened"], 2)
        self.assertEqual(book.counts["closed:expired"], 1)

    def test_places_need_a_position(self):
        book = GuardBook()
        post = book.open("g", "place", "v:bed", 0, 50)
        self.assertEqual(book.places(), [])
        post.xy = (3.0, 4.0)
        self.assertEqual(book.places(), [post])

    def test_blows_are_bounded(self):
        book = GuardBook()
        for tick in range(5000):
            book.blow(tick, "g", "c", "a", "post_00001")
            book.answered = len(book.blows)
        self.assertLessEqual(len(book.blows), 4096)
        self.assertLessEqual(book.answered, len(book.blows))


class FakeEngine:
    def __init__(self, ids):
        self._human_uid_by_slot = list(ids)
        self.tick = 7

    def _human_slot_for_id(self, human_id):
        return self._human_uid_by_slot.index(human_id) if human_id in self._human_uid_by_slot else None


def tensors(ids, positions):
    h = torch.zeros(len(ids), 32)
    for slot, (x, y) in enumerate(positions):
        h[slot, cfg.TYPE] = float(cfg.AGENT_TYPE_HUMAN)
        h[slot, cfg.X], h[slot, cfg.Y], h[slot, cfg.HP] = float(x), float(y), 100.0
    return h


class Hook(unittest.TestCase):
    """slots: 0 attacker, 1 charge, 2 guard."""

    def setUp(self):
        self.addCleanup(modifiers.set_modifier, None)
        self.engine = FakeEngine(["a", "c", "g"])
        self.book = GuardBook()
        self.hook = modifier.make(self.engine, lambda: self.book)
        self.h = tensors(self.engine._human_uid_by_slot, [(0, 0), (10, 0), (20, 0)])

    def test_no_post_no_change(self):
        self.assertEqual(self.hook(self.h, 0, 1, 20.0), (1, 20.0))

    def test_the_guard_in_reach_takes_a_share_of_the_blow(self):
        self.book.open("g", "person", "c", 0, 100)
        self.assertEqual(self.hook(self.h, 0, 1, 20.0), (2, 20.0 * TAKE))
        self.assertEqual(self.book.counts["intercepted"], 1)
        self.assertEqual((self.book.blows[0].guard, self.book.blows[0].charge, self.book.blows[0].attacker), ("g", "c", "a"))

    def test_out_of_reach_hurt_restrained_dormant_or_the_attacker_does_not_intercept(self):
        self.book.open("g", "person", "c", 0, 100)
        far = self.h.clone()
        far[2, cfg.X] = 10.0 + GUARD_RADIUS + 1
        self.assertEqual(self.hook(far, 0, 1, 20.0), (1, 20.0))
        hurt = self.h.clone()
        hurt[2, cfg.HP] = MIN_HP - 1
        self.assertEqual(self.hook(hurt, 0, 1, 20.0), (1, 20.0))
        held = self.h.clone()
        held[2, cfg.H_RESTRAINED] = 5.0
        self.assertEqual(self.hook(held, 0, 1, 20.0), (1, 20.0))
        self.engine._dormant_h = torch.tensor([False, False, True])
        self.assertEqual(self.hook(self.h, 0, 1, 20.0), (1, 20.0))
        del self.engine._dormant_h
        self.assertEqual(self.hook(self.h, 2, 1, 20.0), (1, 20.0))        # the guard itself attacks the charge: it does not shield from itself

    def test_a_closed_post_does_not_intercept(self):
        post = self.book.open("g", "person", "c", 0, 100)
        self.book.close(post.id, "expired", 100)
        self.assertEqual(self.hook(self.h, 0, 1, 20.0), (1, 20.0))

    def test_a_place_post_covers_whoever_stands_there(self):
        post = self.book.open("g", "place", "v:bed", 0, 100)
        post.xy = (10.0, 0.0)
        self.assertEqual(self.hook(self.h, 0, 1, 20.0), (2, 20.0 * TAKE))
        moved = self.h.clone()
        moved[1, cfg.X] = 10.0 + GUARD_RADIUS + 5
        moved[2, cfg.X] = moved[1, cfg.X]
        self.assertEqual(self.hook(moved, 0, 1, 20.0), (1, 20.0))

    def test_through_the_real_resolver_the_guard_loses_hp_and_the_charge_keeps_its_hp(self):
        self.book.open("g", "person", "c", 0, 100)
        modifiers.set_modifier(self.hook)
        m = torch.zeros(4, 32)
        intent = CombatIntent(source="sim", action="attack", attacker_kind="human", attacker_slot=0, target_kind="human", target_slot=1, target_id="c")
        h = self.h.clone()
        h[0, cfg.X], h[0, cfg.Y], h[1, cfg.X], h[1, cfg.Y] = 0.0, 0.0, 4.0, 0.0
        h[2, cfg.X], h[2, cfg.Y] = 8.0, 0.0
        h[:, cfg.H_STAMINA] = 100.0
        resolve_human_attack_intents([intent], h, m, "cpu", walls=[], attack_range=cfg.ATTACK_RANGE * 4)
        self.assertEqual(float(h[1, cfg.HP]), 100.0)
        self.assertLess(float(h[2, cfg.HP]), 100.0)


class Flag(unittest.TestCase):
    def test_default_off(self):
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("EDEN_DEFEND", None)
            self.assertFalse(enabled())


class DefendVerb(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_DEFEND": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def book(self, scene):
        from systems.guard import runtime
        return runtime.of(scene.services)

    def test_guarding_a_person_opens_a_post_and_says_so(self):
        s = Scene()
        r = s.runner.run("h_a", "defend", {"target": "h_b"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        post = self.book(s).of_guard("h_a")
        self.assertEqual((post.kind, post.charge), ("person", "h_b"))
        self.assertEqual(post.until, post.opened + GUARD_TICKS)
        self.assertIn("began_guarding", [e.type for e in r.report.events])
        self.assertGreater(s.records["h_b"]["relationships"]["h_a"]["closeness"], 0.0)

    def test_a_second_post_is_refused_and_a_far_dead_or_unknown_charge_too(self):
        s = Scene()
        self.assertTrue(s.runner.run("h_a", "defend", {"target": "h_b"}).ok)
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "h_smith"}).code, "illegal:already_guarding")
        s = Scene()
        self.assertFalse(s.runner.run("h_a", "defend", {"target": "h_far"}).ok)
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "h_dead"}).code, "illegal:target_dead")
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "nobody"}).code, "ungrounded_target")
        self.assertEqual(s.runner.run("h_a", "defend", {}).code, "illegal:invalid_params")
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "h_a"}).code, "illegal:self_target")

    def test_a_hurt_guard_does_not_take_a_post(self):
        s = Scene()
        setrow(s.world, "h_a", hp=MIN_HP - 1)
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "h_b"}).code, "illegal:too_hurt")

    def test_guarding_a_place_it_perceives(self):
        s = Scene()
        r = s.runner.run("h_a", "defend", {"place": "v:bed"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual((self.book(s).of_guard("h_a").kind, self.book(s).of_guard("h_a").charge), ("place", "v:bed"))
        s = Scene()
        self.assertEqual(s.runner.run("h_a", "defend", {"place": "nowhere"}).code, "ungrounded_place")

    def test_person_and_place_together_are_invalid(self):
        s = Scene()
        self.assertEqual(s.runner.run("h_a", "defend", {"target": "h_b", "place": "v:bed"}).code, "illegal:invalid_params")

    def test_the_mask_lists_the_neighbours_and_the_own_places(self):
        s = Scene()
        options = [o.params for o in s.runner.aff.options("h_a") if o.verb == "defend"]
        self.assertIn({"target": "h_b"}, options)
        self.assertTrue(any("place" in p for p in options))
        self.assertNotIn({}, options)

    def test_flag_off_is_the_legacy_verdict_and_the_verb_is_not_wired(self):
        os.environ.pop("EDEN_DEFEND")
        s = Scene()
        options = [o.params for o in s.runner.aff.options("h_a") if o.verb == "defend"]
        self.assertEqual(options, [{}])
        before = s.digest()
        self.assertFalse(s.runner.run("h_a", "defend", {"target": "h_b"}).ok)
        self.assertTrue(s.same(before, s.digest()))


if __name__ == "__main__":
    unittest.main()
