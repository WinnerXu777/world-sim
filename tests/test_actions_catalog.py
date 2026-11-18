"""The three descriptions of the verb vocabulary must not drift: Appendix A.2 of 1008implementation.md, the tables of 1008_actions.md section 2,
and ``systems/actions/catalog.py``; and every registered Action must match its catalog row and its affordance predicate."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.actions import BY_ID, CATALOG, REGISTRY, S1, counts  # noqa: E402
from systems.affordance import VERBS  # noqa: E402


def read(name):
    return (ROOT / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def appendix_a2_ids():
    text = read("1008implementation.md")
    block = text[text.index("**A.2 Resident verbs"):text.index("**A.3 God and world tools")]
    return re.findall(r"`([A-Za-z_]+)`", block.split("\n", 1)[1])


def doc_table_rows():
    text = read("1008_actions.md")
    section = text[text.index("## 2. Vocabulary"):text.index("**Counts**")]
    return re.findall(r"^\| `([A-Za-z_]+)` \|", section, flags=re.M)


class CatalogDriftTests(unittest.TestCase):
    def test_the_three_sources_list_the_same_65_ids(self):
        a2, doc, cat = appendix_a2_ids(), doc_table_rows(), [row.id for row in CATALOG]
        self.assertEqual(len(a2), 65)
        self.assertEqual(len(set(a2)), 65)
        self.assertEqual(sorted(a2), sorted(doc), "1008implementation.md A.2 vs 1008_actions.md tables")
        self.assertEqual(sorted(a2), sorted(cat), "A.2 vs systems/actions/catalog.py")
        self.assertEqual(len(set(cat)), len(cat))

    def test_counts_match_the_document(self):
        self.assertEqual(counts(), {"total": 65, "now": 37, "glue": 13, "new": 15})
        text = read("1008_actions.md")
        self.assertIn("65 verbs; `now` 37, `glue` 13, `new` 15", text)

    def test_the_s1_list_matches_the_document_and_the_registry(self):
        text = read("1008_actions.md")
        listed = re.findall(r"`([a-z_]+)`", text[text.index("The 17 `S1` verbs"):].split("\n\n", 1)[0].split("(first slice):", 1)[1])
        batches = [v for line in re.findall(r"^Batch \d+ verbs: (.*)$", text, flags=re.M) for v in re.findall(r"`([a-z_]+)`", line)]
        self.assertEqual(len(listed), 17)
        self.assertEqual(sorted(listed + batches), sorted(S1))
        self.assertEqual(len(set(listed + batches)), len(listed + batches))
        self.assertEqual(sorted(REGISTRY.actions), sorted(S1))

    def test_destructive_verbs_are_the_d3_set(self):
        destructive = {row.id for row in CATALOG if row.risk == "destructive"}
        self.assertEqual(destructive, {"attack", "retaliate", "steal_when_safe", "arrest_or_restrain", "PLOT"})

    def test_every_registered_action_matches_its_row_and_predicate(self):
        for name, spec in REGISTRY.actions.items():
            row = BY_ID[name]
            self.assertEqual(spec.extra["risk"], row.risk, name)
            self.assertEqual(spec.extra["precondition"], row.predicate, name)
            self.assertIn(name, VERBS, f"{name} has no affordance predicate")
            self.assertEqual(VERBS[name].predicate_id, row.predicate, name)
            self.assertIn(row.status, ("now", "glue"), name)
            self.assertNotIn("ctx", spec.schema["properties"], name)          # the actor is never a model-supplied value
            self.assertNotIn("world", spec.schema["properties"], name)
            self.assertFalse(spec.schema["additionalProperties"], name)

    def test_rows_are_well_formed(self):
        for row in CATALOG:
            self.assertIn(row.group, ("survival", "work", "economy", "social", "conflict", "exploration", "cognitive"))
            self.assertIn(row.status, ("now", "glue", "new"))
            self.assertIn(row.duration, ("instant", "task"))
            self.assertIn(row.risk, ("reversible", "destructive", "irreversible"))


if __name__ == "__main__":
    unittest.main()
