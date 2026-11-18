"""Registry decorators, generated manifest and schemas, scheduling, and the legacy drift check (every instinct_*/tool_* is
declared or the test fails)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import legacy_manifest as lm  # noqa: E402
from harness.registry import Registry, RegistryError, ScheduleError  # noqa: E402
from harness.schema import schema_for_function, validate  # noqa: E402


def fresh():
    return Registry()


class SchemaTests(unittest.TestCase):
    def test_schema_from_signature(self):
        def fn(world, target: str, amount: int = 3, ratio: float = 0.5, flag: bool = False, kind: Literal["a", "b"] = "a",
               tags: list[str] = (), note: Optional[str] = None, **extra):
            """Does a thing."""
        schema = schema_for_function(fn)
        self.assertEqual(schema["required"], ["target"])
        self.assertEqual(sorted(schema["properties"]), ["amount", "flag", "kind", "note", "ratio", "tags", "target"])  # world/**extra skipped
        self.assertEqual(schema["properties"]["kind"], {"enum": ["a", "b"], "default": "a"})
        self.assertEqual(schema["properties"]["amount"], {"type": "integer", "default": 3})
        self.assertFalse(schema["additionalProperties"])

    def test_validate_catches_the_usual_model_mistakes(self):
        def fn(target: str, amount: int = 3, kind: Literal["a", "b"] = "a"):
            pass
        schema = schema_for_function(fn)
        self.assertEqual(validate(schema, {"target": "x"}), [])
        self.assertTrue(validate(schema, {}))                                   # missing required
        self.assertTrue(validate(schema, {"target": 5}))                        # wrong type
        self.assertTrue(validate(schema, {"target": "x", "amount": True}))      # bool is not an integer
        self.assertTrue(validate(schema, {"target": "x", "amount": 1.5}))
        self.assertTrue(validate(schema, {"target": "x", "kind": "c"}))         # outside the enum
        self.assertTrue(any("unknown field" in e for e in validate(schema, {"target": "x", "typo": 1})))   # no silent ignore

    def test_numeric_limits_arrays_and_any_of(self):
        schema = {"type": "object", "properties": {"n": {"type": "number", "minimum": 0, "maximum": 10},
                                                   "xs": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                                                   "o": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
        self.assertEqual(validate(schema, {"n": 5, "xs": [1], "o": None}), [])
        self.assertTrue(validate(schema, {"n": 11}))
        self.assertTrue(validate(schema, {"n": float("nan")}))
        self.assertTrue(validate(schema, {"xs": []}))
        self.assertTrue(validate(schema, {"xs": ["a"]}))
        self.assertTrue(validate(schema, {"o": 3}))


class DecoratorTests(unittest.TestCase):
    def test_manifest_covers_systems_actions_powers_deterministically(self):
        from harness import registry as r
        reg = fresh()

        @r.system("hunger", phase="needs", reads=["humans.hunger"], writes=["humans.hunger"], registry=reg)
        def hunger(world):
            """Hunger rises each tick."""

        @r.action("eat", precondition="has_food", cost=1.0, registry=reg)
        def eat(world, item: str = "bread"):
            """Eat a held item."""

        @r.power("smite", risk="destructive", registry=reg)
        def smite(world, target: str):
            """Kill a resident."""
        manifest = reg.manifest()
        self.assertEqual(json.dumps(manifest, sort_keys=True), json.dumps(reg.manifest(), sort_keys=True))
        self.assertEqual([s["id"] for s in manifest["systems"]], ["hunger"])
        self.assertEqual(manifest["systems"][0]["phase"], "needs")
        self.assertEqual(manifest["actions"][0]["audience"], "resident")
        self.assertEqual((manifest["powers"][0]["audience"], manifest["powers"][0]["risk"]), ("god", "destructive"))
        self.assertIn("Kill a resident.", manifest["powers"][0]["retrieval_text"])
        self.assertEqual(manifest["powers"][0]["args"]["required"], ["target"])

    def test_validate_call(self):
        from harness import registry as r
        reg = fresh()

        @r.action(registry=reg)
        def give(world, item: str, qty: int):
            """Give items."""
        self.assertEqual(reg.validate_call("give", {"item": "bread", "qty": 2}), [])
        self.assertTrue(reg.validate_call("give", {"item": "bread"}))
        self.assertIn("unknown action", reg.validate_call("steal", {})[0])
        self.assertIn("unknown power", reg.validate_call("steal", {}, kind="power")[0])

    def test_bad_declarations_fail_at_import_time(self):
        from harness import registry as r
        reg = fresh()
        with self.assertRaises(RegistryError):
            r.system("x", phase="nonsense", registry=reg)(lambda world: None)
        with self.assertRaises(RegistryError):
            r.system("x", phase="act", reads=["hunger"], registry=reg)(lambda world: None)   # not 'table.field'
        with self.assertRaises(RegistryError):
            r.system("x", phase="act", every=0, registry=reg)(lambda world: None)
        r.system("x", phase="act", registry=reg)(lambda world: None)
        with self.assertRaises(RegistryError):
            r.system("x", phase="act", registry=reg)(lambda world: None)                    # duplicate
        with self.assertRaises(RegistryError):
            r.power("p", risk="spicy", registry=reg)(lambda world: None)


class ScheduleTests(unittest.TestCase):
    def build(self, specs):
        from harness import registry as r
        reg = fresh()
        for name, kwargs in specs:
            r.system(name, registry=reg, **kwargs)(lambda world: None)
        return reg

    def order(self, reg, tick=None):
        return [s.name for s in reg.schedule(tick)]

    def test_phases_run_in_declared_order_and_writer_precedes_reader(self):
        reg = self.build([("record_it", dict(phase="record")), ("move", dict(phase="act", reads=["humans.hunger"])),
                          ("hunger", dict(phase="act", writes=["humans.hunger"])), ("sense_it", dict(phase="sense"))])
        self.assertEqual(self.order(reg), ["sense_it", "hunger", "move", "record_it"])

    def test_write_write_conflict_is_a_build_error_until_ordered(self):
        specs = [("a", dict(phase="act", writes=["humans.hp"])), ("b", dict(phase="act", writes=["humans.hp"]))]
        with self.assertRaises(ScheduleError) as ctx:
            self.build(specs).schedule()
        self.assertIn("humans.hp", str(ctx.exception))
        ordered = self.build([specs[0], ("b", dict(phase="act", writes=["humans.hp"], after=["a"]))])
        self.assertEqual(self.order(ordered), ["a", "b"])

    def test_wildcard_writes_conflict_with_specific_fields(self):
        reg = self.build([("a", dict(phase="act", writes=["humans.*"])), ("b", dict(phase="act", writes=["humans.hp"]))])
        with self.assertRaises(ScheduleError):
            reg.schedule()

    def test_cycles_and_unknown_after_are_errors(self):
        with self.assertRaises(ScheduleError):
            self.build([("a", dict(phase="act", after=["b"])), ("b", dict(phase="act", after=["a"]))]).schedule()
        with self.assertRaises(ScheduleError):
            self.build([("a", dict(phase="act", after=["ghost"]))]).schedule()
        with self.assertRaises(ScheduleError):   # reader/writer pair that would need a cycle
            self.build([("a", dict(phase="act", reads=["humans.x"], writes=["humans.y"])),
                        ("b", dict(phase="act", reads=["humans.y"], writes=["humans.x"]))]).schedule()

    def test_every_filters_by_tick_and_order_is_deterministic(self):
        reg = self.build([("slow", dict(phase="world", every=10)), ("fast", dict(phase="world"))])
        self.assertEqual(self.order(reg, tick=3), ["fast"])
        self.assertEqual(self.order(reg, tick=20), ["fast", "slow"])
        self.assertEqual(self.order(reg), self.order(reg))


class LegacyDriftTests(unittest.TestCase):
    def test_every_legacy_function_is_declared_and_classified(self):
        names = lm.legacy_names()
        self.assertEqual((len([n for n in names if n.startswith("instinct_")]), len([n for n in names if n.startswith("tool_")])), (46, 74))
        report = lm.drift()
        self.assertEqual({k: v for k, v in report.items() if v}, {}, "legacy instincts/tools drifted from legacy_signatures.json or the triage; "
                         "update both deliberately (python at_the_beginning/harness/legacy_manifest.py --write)")

    def test_rows_are_complete_json_and_account_for_their_effects(self):
        rows = lm.legacy_entries()
        self.assertEqual(len(rows), 120)
        json.dumps(rows)
        for row in rows:
            self.assertIn(row["audience"], ("system", "god", "internal", "resident"), row["id"])
            self.assertTrue(row["reads"] or row["writes"] or row["delegates_tensors_to"], f"{row['id']} touches no tensor and delegates nothing")
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["instinct_hunger"]["writes"], ["humans.HUNGER"])
        self.assertIn("humans.X", by_id["instinct_move"]["writes"])
        self.assertEqual(by_id["tool_cull"]["audience"], "god")
        self.assertEqual(by_id["tool_cull"]["disposition"], "keep_destructive")
        self.assertEqual(by_id["instinct_frontier_expand"]["disposition"], "retire")

    def test_drift_detects_added_removed_and_changed_functions(self):
        source = lm.IAT.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            mutated = Path(tmp) / "iat.py"
            text = source.replace("def tool_set_mood(", "def tool_set_mood(extra_arg, ", 1) if "def tool_set_mood(" in source else source
            text += "\n\ndef tool_brand_new(ctx):\n    pass\n"
            text = text.replace("def instinct_age(", "def renamed_instinct_age(", 1)
            mutated.write_text(text, encoding="utf-8")
            report = lm.drift(mutated)
        self.assertEqual(report["undeclared_new"], ["tool_brand_new"])
        self.assertEqual(report["declared_but_gone"], ["instinct_age"])
        self.assertEqual(report["signature_changed"], ["tool_set_mood"])
        self.assertEqual(report["unclassified"], ["tool_brand_new"])

    def test_triage_for_a_name_that_no_longer_exists_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            trimmed = Path(tmp) / "iat.py"
            trimmed.write_text(lm.IAT.read_text(encoding="utf-8").replace("def tool_cull(", "def not_a_tool(", 1), encoding="utf-8")
            report = lm.drift(trimmed)
        self.assertIn("tool_cull", report["triage_for_unknown"])


if __name__ == "__main__":
    unittest.main()
