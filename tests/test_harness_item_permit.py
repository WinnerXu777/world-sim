"""H-Q1: declared consume/produce permission for item Transfers (eat/craft need it), per apply, with caps and a manifest declaration."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import effects as fx  # noqa: E402
from harness.effects import ItemPermit  # noqa: E402
from harness.registry import Registry, RegistryError, action, power  # noqa: E402
from harness.world import World  # noqa: E402


def world_with(**stock):
    w = World.synthetic(seed=3)
    a = w.add_row("humans", x=10, y=10, hp=100)
    b = w.add_row("humans", x=20, y=10, hp=100)
    for item, qty in stock.items():
        w.items.add(a, item, qty)
    return w, a, b


def totals(w, *items):
    return {i: w.items.total(i) for i in items}


class PermitDeclarationTests(unittest.TestCase):
    def test_validation_of_a_permit(self):
        for bad in ({"": 1}, {"bread": 0}, {"bread": -2}, {"bread": 1.5}, {"bread": True}, {3: 1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                ItemPermit(consume=bad)
        self.assertFalse(ItemPermit())
        self.assertTrue(ItemPermit.of(consume=["bread"]))
        self.assertEqual(ItemPermit.of(consume=["bread"], produce={"coin": 3}).as_dict(), {"consume": {"bread": None}, "produce": {"coin": 3}})


class ConsumeProduceTests(unittest.TestCase):
    def test_eat_consume_needs_the_declaration(self):
        w, a, b = world_with(bread=3)
        denied = w.apply([fx.Transfer("bread", 1, a, None)])                       # no permit at all
        self.assertEqual([s.reason for s in denied.skipped], ["creation_not_allowed"])
        wrong = w.apply([fx.Transfer("bread", 1, a, None)], items=ItemPermit.of(consume=["apple"]))
        self.assertEqual([s.reason for s in wrong.skipped], ["consume_not_declared"])
        self.assertEqual(totals(w, "bread"), {"bread": 3})
        ok = w.apply([fx.Transfer("bread", 1, a, None)], items=ItemPermit.of(consume=["bread"]))
        self.assertTrue(ok.ok)
        self.assertEqual((ok.destroyed, totals(w, "bread"), w.items.quantity(a, "bread")), ({"bread": 1}, {"bread": 2}, 2))

    def test_craft_consumes_inputs_and_produces_the_output_atomically(self):
        w, a, b = world_with(wood=4)
        permit = ItemPermit(consume={"wood": 2}, produce={"plank": 1})
        report = w.apply([fx.Transfer("wood", 2, a, None), fx.Transfer("plank", 1, None, a)], atomic=True, items=permit)
        self.assertTrue(report.ok)
        self.assertEqual((report.destroyed, report.created), ({"wood": 2}, {"plank": 1}))
        self.assertEqual(totals(w, "wood", "plank"), {"wood": 2, "plank": 1})

    def test_produce_and_consume_are_separate_permissions(self):
        w, a, b = world_with(wood=4)
        only_consume = ItemPermit.of(consume=["wood"])
        r = w.apply([fx.Transfer("plank", 1, None, a)], items=only_consume)
        self.assertEqual([s.reason for s in r.skipped], ["produce_not_declared"])
        only_produce = ItemPermit.of(produce=["plank"])
        r = w.apply([fx.Transfer("wood", 1, a, None)], items=only_produce)
        self.assertEqual([s.reason for s in r.skipped], ["consume_not_declared"])
        self.assertEqual(totals(w, "wood", "plank"), {"wood": 4, "plank": 0})

    def test_caps_are_summed_over_the_whole_apply(self):
        w, a, b = world_with(wood=9)
        permit = ItemPermit(consume={"wood": 3})
        r = w.apply([fx.Transfer("wood", 2, a, None), fx.Transfer("wood", 2, a, None)], atomic=True, items=permit)
        self.assertEqual([s.reason for s in r.skipped], ["consume_over_cap"])
        self.assertTrue(r.rolled_back)
        self.assertEqual(totals(w, "wood"), {"wood": 9})                           # atomic: nothing consumed
        r = w.apply([fx.Transfer("wood", 2, a, None), fx.Transfer("wood", 2, a, None)], items=permit)   # non-atomic
        self.assertEqual(([s.reason for s in r.skipped], r.destroyed, totals(w, "wood")), (["consume_over_cap"], {"wood": 2}, {"wood": 7}))

    def test_transfers_between_owners_never_need_a_permit_and_do_not_use_the_cap(self):
        w, a, b = world_with(bread=3)
        r = w.apply([fx.Transfer("bread", 1, a, b), fx.Transfer("bread", 3, None, a)], items=ItemPermit(produce={"bread": 3}))
        self.assertTrue(r.ok, [(s.reason, s.detail) for s in r.skipped])
        self.assertEqual((w.items.quantity(a, "bread"), w.items.quantity(b, "bread")), (5, 1))

    def test_other_checks_still_apply_under_a_permit(self):
        w, a, b = world_with(bread=1)
        r = w.apply([fx.Transfer("bread", 2, a, None)], items=ItemPermit.of(consume=["bread"]))
        self.assertEqual([s.reason for s in r.skipped], ["insufficient"])
        r = w.apply([fx.Transfer("bread", 0, None, a)], items=ItemPermit.of(produce=["bread"]))
        self.assertEqual([s.reason for s in r.skipped], ["invalid_quantity"])
        self.assertEqual(totals(w, "bread"), {"bread": 1})

    def test_the_permit_lasts_for_one_apply_only(self):
        w, a, b = world_with(bread=3)
        w.apply([fx.Transfer("bread", 1, a, None)], items=ItemPermit.of(consume=["bread"]))
        self.assertIsNone(w.effects._permit)
        again = w.apply([fx.Transfer("bread", 1, a, None)])
        self.assertEqual([s.reason for s in again.skipped], ["creation_not_allowed"])
        with self.assertRaises(RuntimeError):                                       # a failing apply still clears it
            class Boom(Exception):
                pass
            w.items.total = lambda item: (_ for _ in ()).throw(RuntimeError("store failed"))
            w.apply([fx.Transfer("bread", 1, a, None)], items=ItemPermit.of(consume=["bread"]))
        self.assertIsNone(w.effects._permit)

    def test_validate_without_applying_uses_the_permit_and_changes_nothing(self):
        w, a, b = world_with(bread=3)
        before = (w.revision, totals(w, "bread"))
        self.assertEqual(w.effects.validate([fx.Transfer("bread", 1, a, None)]), w.effects.validate([fx.Transfer("bread", 1, a, None)], None))
        self.assertEqual([p.reason for p in w.effects.validate([fx.Transfer("bread", 1, a, None)])], ["creation_not_allowed"])
        self.assertEqual(w.effects.validate([fx.Transfer("bread", 1, a, None)], ItemPermit.of(consume=["bread"])), [])
        self.assertEqual((w.revision, totals(w, "bread")), before)

    def test_unrestricted_flag_still_works_and_a_permit_overrides_it(self):
        w = World.synthetic(allow_item_creation=True)
        a = w.add_row("humans", x=1, y=1, hp=10)
        self.assertTrue(w.apply([fx.Transfer("coin", 5, None, a)]).ok)              # legacy unrestricted flag
        r = w.apply([fx.Transfer("coin", 5, None, a)], items=ItemPermit.of(produce=["gem"]))   # a declared permit is strict
        self.assertEqual([s.reason for s in r.skipped], ["produce_not_declared"])


class RegistryDeclarationTests(unittest.TestCase):
    def build(self):
        reg = Registry()

        @action("eat", consumes=["bread", "apple"], registry=reg)
        def eat(world, actor: str):
            """Eat food you carry."""

        @action("wave", registry=reg)
        def wave(world, actor: str):
            """Wave."""

        @power("bless_harvest", produces={"wheat": 50}, registry=reg)
        def bless_harvest(world, targets: dict):
            """Make wheat appear."""
        return reg

    def test_manifest_lists_declarations_and_omits_them_when_empty(self):
        manifest = self.build().manifest()
        actions = {a["id"]: a for a in manifest["actions"]}
        self.assertEqual(actions["eat"]["consumes"], ["apple", "bread"])
        self.assertNotIn("consumes", actions["wave"])
        self.assertNotIn("produces", actions["wave"])
        self.assertEqual({p["id"]: p for p in manifest["powers"]}["bless_harvest"]["produces"], ["wheat"])

    def test_permit_is_checked_against_the_declaration(self):
        reg = self.build()
        self.assertEqual(reg.check_item_permit("eat", ItemPermit(consume={"bread": 1})), [])
        problems = reg.check_item_permit("eat", ItemPermit(consume={"bread": 1, "gold": 1}, produce={"plate": 1}))
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("gold" in p for p in problems) and any("plate" in p for p in problems))
        self.assertEqual(len(reg.check_item_permit("wave", ItemPermit(consume={"bread": 1}))), 1)
        self.assertEqual(reg.check_item_permit("nope", ItemPermit()), ["unknown action 'nope'"])

    def test_bad_declarations_are_refused(self):
        with self.assertRaises(RegistryError):
            @action("bad", consumes=[""], registry=Registry())
            def bad(world):
                """x"""


if __name__ == "__main__":
    unittest.main()
