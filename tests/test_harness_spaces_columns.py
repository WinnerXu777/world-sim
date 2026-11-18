"""1008 WS-D P2 (D1): the space columns (H_SPACE 29, M_GEN 30, M_SPACE 31), ``pairwise_distances`` with space arguments and the call sites
that pass them. Flag ``EDEN_SPACES`` off (default): every result equals the legacy one bit for bit. On: rows of different spaces are
never within any radius. The mate-attraction fallback in ``instinct_move`` (needs a whole engine tick) is covered by review, not here."""
import os
import random
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
import genesis_config as cfg  # noqa: E402
from harness import numerics  # noqa: E402
from harness.numerics import FAR, pairwise_distances, space_slice, spaces_enabled  # noqa: E402

FLAG = "EDEN_SPACES"
SRC = ROOT / "at_the_beginning"


def flag(on):
    env = {FLAG: "1"} if on else {}
    patcher = mock.patch.dict(os.environ, env, clear=False)
    patcher.start()
    if not on:
        os.environ.pop(FLAG, None)
    return patcher


def section_ints(text, start, stop):
    """{NAME: int} for top-level `NAME = <int>` lines between two marker substrings of genesis_config.py."""
    body = text[text.index(start):text.index(stop)]
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\b", body, re.M)}


class ColumnLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (SRC / "genesis_config.py").read_text(encoding="utf-8")
        cls.human = section_ints(cls.text, "H_TENSOR — HUMAN TENSOR COLUMNS", "AGENT_TYPE_EMPTY = 0")
        cls.entity = section_ints(cls.text, "M_TENSOR — ENTITY TENSOR COLUMNS", "KNOWN M_TYPE VALUES")
        cls.node_columns = {k: v for k, v in section_ints(cls.text, "M_RESOURCE_NODE = 27", "# Animals 40–79").items() if k.startswith(("M_NODE", "M_DEPL"))}

    def test_values(self):
        self.assertEqual((cfg.H_SPACE, cfg.M_GEN, cfg.M_SPACE), (29, 30, 31))

    def test_the_human_space_column_is_used_by_nothing_else(self):
        self.assertIn("H_SPACE", self.human)
        self.assertEqual(cfg.H_RESTRAINED, 30)                # defend Phase 1 (1008_defend_phase1_gap.md); human column 31 is the last free one
        others = {k: v for k, v in self.human.items() if k not in ("H_SPACE", "H_RESTRAINED")}
        self.assertNotIn(29, others.values())
        self.assertNotIn(30, others.values())
        self.assertNotIn(31, others.values())
        self.assertEqual(max(others.values()), 28)            # instinct-mask words end at 28 (G-D0-2)
        self.assertEqual(len(set(self.human.values())), len(self.human), "a human column is defined twice")

    def test_the_entity_columns_30_and_31_are_used_by_nothing_else(self):
        others = {k: v for k, v in self.entity.items() if k not in ("M_GEN", "M_SPACE")}
        self.assertFalse({30, 31} & set(others.values()), others)
        self.assertEqual(cfg.M_GEN, 30)
        self.assertEqual(cfg.M_SPACE, 31)

    def test_species_attribute_range_and_node_columns_do_not_reach_the_new_columns(self):
        self.assertEqual(sorted(self.node_columns.values()), [13, 14, 15, 16])      # G-005 resource nodes
        self.assertTrue(all(v < 29 for v in self.node_columns.values()))
        self.assertIn("# 17–29 reserved for species-specific attrs", self.text)

    def test_no_source_file_indexes_a_tensor_with_a_literal_29_30_or_31(self):
        pattern = re.compile(r"\[[^\]\n]*,\s*(29|30|31)\s*\]")
        hits = []
        for path in SRC.rglob("*.py"):
            rel = path.relative_to(SRC).as_posix()
            if rel.startswith(("worldgen", "systems/worldgen")) or rel == "genesis_config.py" or "__pycache__" in rel:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    hits.append(f"{rel}:{number}: {line.strip()[:90]}")
        self.assertEqual(hits, [])


class PairwiseDistanceTests(unittest.TestCase):
    def test_flag_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FLAG, None)
            self.assertFalse(spaces_enabled())
            self.assertIsNone(space_slice(torch.zeros(3, 32), [0, 1], "h"))
        with mock.patch.dict(os.environ, {FLAG: "1"}):
            self.assertTrue(spaces_enabled())
            t = torch.zeros(3, 32)
            t[1, cfg.H_SPACE] = 7.0
            t[2, cfg.M_SPACE] = 9.0
            self.assertEqual(space_slice(t, [0, 1], "h").tolist(), [0.0, 7.0])
            self.assertEqual(space_slice(t, torch.tensor([False, False, True]), "m").tolist(), [9.0])

    def test_without_spaces_the_result_is_the_legacy_matrix_bit_for_bit(self):
        rng = random.Random(3)
        for _ in range(20):
            a = torch.tensor([[rng.uniform(0, 1200), rng.uniform(0, 900)] for _ in range(rng.randint(1, 40))])
            b = torch.tensor([[rng.uniform(0, 1200), rng.uniform(0, 900)] for _ in range(rng.randint(1, 40))])
            legacy = torch.cdist(a, b, compute_mode=numerics.EXACT_MODE)
            self.assertTrue(torch.equal(pairwise_distances(a, b), legacy))
            self.assertTrue(torch.equal(pairwise_distances(a, b, space_a=None, space_b=torch.zeros(len(b))), legacy))
            self.assertTrue(torch.equal(pairwise_distances(a, b, space_a=torch.zeros(len(a))), legacy))
            self.assertTrue(torch.equal(pairwise_distances(a, b, space_a=torch.zeros(len(a)), space_b=torch.zeros(len(b))), legacy))

    def test_equal_space_entries_are_unchanged_and_other_spaces_are_far(self):
        rng = random.Random(4)
        a = torch.tensor([[rng.uniform(0, 300), rng.uniform(0, 300)] for _ in range(30)])
        b = torch.tensor([[rng.uniform(0, 300), rng.uniform(0, 300)] for _ in range(28)])
        sa = torch.tensor([float(rng.randint(0, 2)) for _ in range(30)])
        sb = torch.tensor([float(rng.randint(0, 2)) for _ in range(28)])
        legacy = torch.cdist(a, b, compute_mode=numerics.EXACT_MODE)
        masked = pairwise_distances(a, b, space_a=sa, space_b=sb)
        same = sa.reshape(-1, 1) == sb.reshape(1, -1)
        self.assertTrue(torch.equal(masked[same], legacy[same]))
        self.assertTrue(bool((masked[~same] == FAR).all()))
        self.assertTrue(bool(torch.isfinite(masked).all()))
        self.assertFalse(bool((masked[~same] < 1.0e6).any()))

    def test_a_single_point_with_a_scalar_space(self):
        a = torch.tensor([[0.0, 0.0], [3.0, 4.0]])
        centre = torch.tensor([[0.0, 0.0]])
        out = pairwise_distances(a, centre, space_a=torch.tensor([0.0, 1.0]), space_b=torch.tensor(1.0))     # 0-d tensor
        self.assertEqual(out.squeeze(1).tolist(), [float(torch.tensor(FAR)), 5.0])


def humans(rows):
    """rows: (x, y, space). A 6-slot h_tensor with the given humans in slots 0.."""
    h = torch.zeros(6, 32)
    for i, (x, y, space) in enumerate(rows):
        h[i, cfg.X], h[i, cfg.Y], h[i, cfg.TYPE], h[i, cfg.HP] = x, y, float(cfg.AGENT_TYPE_HUMAN), 100.0
        h[i, cfg.H_STAMINA], h[i, cfg.H_SPACE] = 100.0, float(space)
    return h


def entities(rows):
    """rows: (type, x, y, space) -> a full-size m_tensor (MAX_ENTITIES rows) with the rows in slots 1..; returns (tensor, slots)."""
    m = torch.zeros(cfg.MAX_ENTITIES, 32)
    for i, (kind, x, y, space) in enumerate(rows, start=1):
        m[i, cfg.M_TYPE], m[i, cfg.CX], m[i, cfg.CY], m[i, cfg.M_SPACE] = float(kind), x, y, float(space)
        m[i, cfg.M_HP], m[i, cfg.SCALE] = 100.0, 4.0
    return m


class SiteTests(unittest.TestCase):
    def setUp(self):
        import instincts_and_tools as iat
        self.iat = iat

    # human-human pairwise pass ---------------------------------------------------------------------------------------------
    def test_shared_human_pairwise_pass(self):
        h = humans([(0, 0, 1), (3, 0, 1), (4, 0, 0)])
        mask = h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN
        for on in (False, True):
            patcher = flag(on)
            self.addCleanup(patcher.stop)
            out = self.iat._build_human_pairwise(h, mask)
            within = out["within_infection"]
            self.assertTrue(bool(within[0, 1]) and bool(within[1, 0]))                       # same space, 3 apart
            self.assertEqual(bool(within[0, 2]), not on, f"flag {on}: 0 and 2 are 4 apart in different spaces")
            self.assertEqual(float(out["dists"][0, 2]), float(torch.tensor(FAR)) if on else 4.0)
            patcher.stop()

    def test_instinct_proximity(self):
        h = humans([(0, 0, 1), (4, 0, 0), (50, 0, 1)])
        src = torch.tensor([True, False, False, False, False, False])
        tgt = torch.tensor([False, True, True, False, False, False])
        for on in (False, True):
            patcher = flag(on)
            result = self.iat.instinct_proximity(h, src, tgt, 10.0)
            patcher.stop()
            self.assertEqual(result.tolist(), [not on])          # off: human 1 is 4 away; on: it is in another space, human 2 is 50 away

    # animals ---------------------------------------------------------------------------------------------------------------
    def attack(self, on, tiger_space, human_space):
        h = humans([(10, 10, human_space)])
        m = entities([(cfg.M_TIGER, 12, 10, tiger_space)])
        a_mask = m[:, cfg.M_TYPE] == cfg.M_TIGER
        ctx = {"a_mask": a_mask, "h_mask": h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN}
        patcher = flag(on)
        try:
            self.iat.animal_instinct_predator_attack(ctx, m, h, [1], [2], "cpu")
        finally:
            patcher.stop()
        return float(h[0, cfg.HP])

    def test_predators_only_attack_humans_in_their_space(self):
        self.assertEqual(self.attack(False, 0, 1), 85.0)            # flag off: legacy, the other space is ignored by nobody
        self.assertEqual(self.attack(True, 0, 1), 100.0)            # flag on, different spaces: untouched
        self.assertEqual(self.attack(True, 1, 1), 85.0)             # flag on, same space: bitten
        self.assertEqual(self.attack(True, 0, 0), 85.0)

    def test_predators_and_prey_animals(self):
        for on, tiger_space, expected in ((False, 1, 85.0), (True, 1, 100.0), (True, 0, 85.0)):
            m = entities([(cfg.M_TIGER, 12, 10, tiger_space), (cfg.M_SHEEP, 10, 10, 0)])
            a_mask = (m[:, cfg.M_TYPE] == cfg.M_TIGER) | (m[:, cfg.M_TYPE] == cfg.M_SHEEP)
            h = humans([])
            ctx = {"a_mask": a_mask, "h_mask": h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN}
            patcher = flag(on)
            try:
                self.iat.animal_instinct_predator_attack(ctx, m, h, [0], [3], "cpu")
            finally:
                patcher.stop()
            self.assertEqual(float(m[2, cfg.M_HP]), expected, (on, tiger_space))

    def test_animals_mate_only_inside_one_space(self):
        for on, female_space, born in ((False, 1, 1), (True, 1, 0), (True, 0, 1)):
            m = entities([(cfg.M_SHEEP, 10, 10, 0), (cfg.M_SHEEP, 12, 10, female_space)])
            for slot, sex in ((1, 0.0), (2, 1.0)):
                m[slot, cfg.A_AGE], m[slot, cfg.A_SEX], m[slot, cfg.A_COOLDOWN] = cfg.ANIMAL_MATURE_TICKS + 1.0, sex, 0.0
            ctx = {"a_mask": m[:, cfg.M_TYPE] == cfg.M_SHEEP}
            count = [3]
            patcher = flag(on)
            try:
                self.iat.animal_tool_reproduce(ctx, m, count, "cpu")
            finally:
                patcher.stop()
            self.assertEqual(count[0] - 3, born, (on, female_space))

    # nature ----------------------------------------------------------------------------------------------------------------
    def test_fire_spreads_only_inside_a_space(self):
        from systems.nature import hazards
        for on, forest_space, spreads in ((False, 1, True), (True, 1, False), (True, 0, True)):
            m = entities([(cfg.M_FOREST, 10, 10, 0), (cfg.M_FOREST, 20, 10, forest_space)])
            m[1, cfg.M_BURNING] = 1.0
            ctx = {"h_mask": torch.zeros(6, dtype=torch.bool)}
            patcher = flag(on)
            try:
                with mock.patch.object(hazards, "FIRE_SPREAD_PROB", 2.0):
                    hazards.apply_fire_tick(ctx, m, humans([]), device="cpu")
            finally:
                patcher.stop()
            self.assertEqual(float(m[2, cfg.M_BURNING]) > 0.0, spreads, (on, forest_space))

    def test_flood_expands_only_into_the_same_space(self):
        from systems.nature import disasters
        import map_geo
        for on, land_space, floods in ((False, 1, True), (True, 1, False), (True, 0, True)):
            m = entities([(cfg.M_SEA, 10, 10, 0), (cfg.M_GRASS, 40, 10, land_space)])
            m[2, cfg.M_RESOURCE_FOOD] = 5.0
            patcher = flag(on)
            try:
                with mock.patch.object(map_geo, "geo_mutate", lambda *a, **k: None), mock.patch.object(map_geo, "unregister_entity", lambda *a, **k: None):
                    disasters.apply_flood({"h_mask": torch.zeros(6, dtype=torch.bool)}, humans([]), m, device="cpu", expand_radius=100.0)
            finally:
                patcher.stop()
            self.assertEqual(float(m[2, cfg.M_TYPE]) == float(cfg.M_SEA), floods, (on, land_space))

    # perception, creation --------------------------------------------------------------------------------------------------
    def test_radial_helpers_take_an_optional_space(self):
        from systems.perception import queries
        h = humans([(10, 10, 0), (12, 10, 1)])
        h_mask = h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN
        m = entities([(cfg.M_FOREST, 10, 10, 0), (cfg.M_FOREST, 12, 10, 1)])
        for on in (False, True):
            patcher = flag(on)
            try:
                everyone = queries.agent_radial_mask(h, h_mask, 11.0, 10.0, 5.0, "cpu").nonzero().flatten().tolist()
                unfiltered = queries.entity_radial_ids(m, 11.0, 10.0, 5.0).tolist()
                in_zero = queries.agent_radial_mask(h, h_mask, 11.0, 10.0, 5.0, "cpu", space=0).nonzero().flatten().tolist()
                in_one = queries.entity_radial_ids(m, 11.0, 10.0, 5.0, space=1).tolist()
            finally:
                patcher.stop()
            self.assertEqual(everyone, [0, 1])                                              # no space argument: unchanged in both modes
            self.assertEqual(unfiltered, [1, 2])
            self.assertEqual(in_zero, [0] if on else [0, 1])
            self.assertEqual(in_one, [2] if on else [1, 2])

    def test_nearest_matching_entity_search_space(self):
        from systems.map import create
        m = entities([(cfg.M_FOREST, 10, 10, 1), (cfg.M_FOREST, 60, 10, 0)])
        for on in (False, True):
            patcher = flag(on)
            try:
                unrestricted = create._nearest_matching_entity(m, near_type=cfg.M_FOREST, search_x=11.0, search_y=10.0)
                in_zero = create._nearest_matching_entity(m, near_type=cfg.M_FOREST, search_x=11.0, search_y=10.0, search_space=0)
            finally:
                patcher.stop()
            self.assertEqual(unrestricted, 1)
            self.assertEqual(in_zero, 2 if on else 1)


if __name__ == "__main__":
    unittest.main()
