"""Typed selectors (harness.target_selectors; not named selectors.py, which would shadow the stdlib module when the harness dir is on sys.path): validation errors, masks, ordering, limits, near-queries, stable ids and re-resolution."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import effects as fx  # noqa: E402
from harness import target_selectors as sel  # noqa: E402
from harness.world import World  # noqa: E402


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.w = World.synthetic(seed=3)
        self.ids = {}
        for name, (x, y, hunger) in {"a": (10, 10, 80), "b": (20, 10, 60), "c": (30, 10, 40), "d": (400, 400, 95), "e": (12, 12, 10)}.items():
            self.ids[name] = self.w.add_row("humans", x=x, y=y, hp=100, hunger=hunger, space=0 if name != "e" else 1)
        self.w.add_row("entities", x=15, y=10, food=500)

    def names(self, resolution):
        inverse = {v: k for k, v in self.ids.items()}
        return [inverse[i] for i in resolution.ids]

    def test_where_order_and_limit(self):
        r = sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": ">", "value": 50}], "order_by": {"field": "hunger", "dir": "desc"}}, self.w)
        self.assertEqual(self.names(r), ["d", "a", "b"])
        r = sel.resolve({"of": "humans", "order_by": {"field": "hunger"}, "limit": 2}, self.w)
        self.assertEqual(self.names(r), ["e", "c"])
        self.assertEqual(sel.resolve({"of": "humans", "limit": 0}, self.w).ids, ())

    def test_default_order_is_by_id_and_ties_break_by_id(self):
        r = sel.resolve({"of": "humans", "where": [{"field": "hp", "op": "==", "value": 100}]}, self.w)
        self.assertEqual(list(r.ids), sorted(r.ids))
        r = sel.resolve({"of": "humans", "order_by": {"field": "hp", "dir": "desc"}}, self.w)
        self.assertEqual(list(r.ids), sorted(r.ids))

    def test_near_point_and_near_anchor_and_space(self):
        near = {"of": "humans", "near": {"anchor": {"point": [10, 10]}, "radius": 12}}
        self.assertEqual(self.names(sel.resolve(near, self.w)), ["a", "b", "e"])
        self.assertEqual(self.names(sel.resolve({**near, "space": 0}, self.w)), ["a", "b"])
        anchored = {"of": "humans", "near": {"anchor": {"id": self.ids["a"]}, "radius": 11}}
        self.assertEqual(self.names(sel.resolve(anchored, self.w)), ["a", "b", "e"])
        cross = {"of": "humans", "near": {"anchor": {"id": self.w.table("entities").ids[0], "table": "entities"}, "radius": 6}}
        self.assertEqual(self.names(sel.resolve(cross, self.w)), ["a", "b", "e"])  # no space filter here

    def test_in_not_in_bit_ops_and_explicit_ids(self):
        self.assertEqual(self.names(sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": "in", "value": [10, 40]}]}, self.w)), ["c", "e"])
        self.assertEqual(len(sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": "not_in", "value": [10, 40]}]}, self.w).ids), 3)
        self.assertEqual(self.names(sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": "bit_set", "value": 4}]}, self.w)), ["a", "b", "d"])  # 80, 60, 95 have bit 4 (16)
        self.assertEqual(self.names(sel.resolve({"of": "humans", "ids": [self.ids["c"], self.ids["a"], "h_999999"]}, self.w)), ["a", "c"])

    def test_dead_rows_are_never_selected(self):
        self.w.apply([fx.despawn("humans", self.ids["a"])])
        self.assertNotIn(self.ids["a"], sel.resolve({"of": "humans"}, self.w).ids)

    def test_validation_errors_are_structured(self):
        bad = {"of": "ghosts"}
        self.assertTrue(sel.check(bad, self.w)[0].startswith("$.of"))
        errors = sel.check({"of": "humans", "where": [{"field": "nope", "op": "~", "value": 1}], "limit": -1, "extra": 1}, self.w)
        text = " | ".join(errors)
        for needle in ("op", "limit", "extra"):
            self.assertIn(needle, text)
        self.assertTrue(any("no field" in e for e in sel.check({"of": "humans", "where": [{"field": "nope", "op": ">", "value": 1}]}, self.w)))
        self.assertTrue(any("exactly one" in e for e in sel.check({"of": "humans", "near": {"anchor": {}, "radius": 1}}, self.w)))
        self.assertTrue(any("unknown anchor" in e for e in sel.check({"of": "humans", "near": {"anchor": {"id": "zz"}, "radius": 1}}, self.w)))
        self.assertTrue(any("bit index" in e for e in sel.check({"of": "humans", "where": [{"field": "hp", "op": "bit_set", "value": 99}]}, self.w)))
        self.assertTrue(any("list of numbers" in e for e in sel.check({"of": "humans", "where": [{"field": "hp", "op": "in", "value": 5}]}, self.w)))
        with self.assertRaises(sel.SelectorError):
            sel.resolve(bad, self.w)

    def test_reresolve_drops_the_dead_the_changed_and_the_replaced_but_never_adds(self):
        r = sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": ">", "value": 50}], "limit": 5}, self.w)   # a, b, d
        self.w.apply([fx.despawn("humans", self.ids["a"]), fx.delta("humans", self.ids["b"], "hunger", -30)])
        newcomer = self.w.apply([fx.Spawn("humans", {"type": 1, "hunger": 99, "x": 1, "y": 1})]).spawned[0][1]   # takes a's slot
        again = sel.reresolve(r, self.w)
        self.assertEqual(again.kept, (self.ids["d"],))
        self.assertEqual(dict(again.dropped), {self.ids["a"]: "gone", self.ids["b"]: "no_longer_matches"})
        self.assertNotIn(newcomer, again.kept)    # same slot, different entity: not mistaken for the old one
        self.assertFalse(again.unchanged)

    def test_reresolve_unchanged_and_resolution_records_revision(self):
        r = sel.resolve({"of": "humans", "near": {"anchor": {"point": [10, 10]}, "radius": 15}}, self.w)
        self.w.apply([fx.delta("humans", self.ids["d"], "hp", -1)])
        self.assertTrue(sel.reresolve(r, self.w).unchanged)
        self.assertEqual((r.revision, self.w.revision), (0, 1))

    def test_selector_applies_to_effects_end_to_end(self):
        r = sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": ">", "value": 50}], "order_by": {"field": "hunger", "dir": "desc"}, "limit": 2}, self.w)
        self.w.apply([fx.delta("humans", sel.reresolve(r, self.w).kept, "hunger", -50)])
        self.assertEqual([self.w.table("humans").get(i, "hunger") for i in r.ids], [45.0, 30.0])  # d 95->45, a 80->30


if __name__ == "__main__":
    unittest.main()
