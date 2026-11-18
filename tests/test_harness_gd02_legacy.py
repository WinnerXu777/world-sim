"""G-D0-2 option A' through the real legacy code: grant/revoke/enlighten/inherit, the per-tick dispatcher, mating's parent copy,
death and slot reuse, and a save/restore round trip. Bits 0, 23, 24, 47, 48 and 63 are the word boundaries."""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
from harness import instinct_bits as ib  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402
from systems.social.mating import resolve_human_reproduction  # noqa: E402

BITS = (0, 23, 24, 47, 48, 63)


def humans(n=4):
    h = torch.zeros((16, cfg.HUMAN_TENSOR_COLS))
    h[:n, cfg.TYPE] = cfg.AGENT_TYPE_HUMAN
    h[:n, cfg.HP] = 100.0
    return h


def ctx_for(h):
    return {"h_mask": h[:, cfg.TYPE] > 0}


def bits(h, row):
    return ib.bits_of(int(ib.read_mask(h, row)))


class ConstantsTests(unittest.TestCase):
    def test_columns_match_the_helper_and_stay_inside_the_reserved_range(self):
        self.assertEqual(ib.MASK_COLS, (cfg.ACQUIRED_INSTINCT_MASK, cfg.ACQUIRED_INSTINCT_MASK_1, cfg.ACQUIRED_INSTINCT_MASK_2))
        self.assertEqual(ib.PARENT_COLS, (cfg.H_PARENT_INSTINCTS, cfg.H_PARENT_INSTINCTS_1, cfg.H_PARENT_INSTINCTS_2))
        used = {v for k, v in vars(cfg).items() if k.isupper() and isinstance(v, int) and not isinstance(v, bool)}
        for col in (25, 26, 27, 28):
            self.assertLess(col, cfg.HUMAN_TENSOR_COLS)
        self.assertEqual(sorted(c for c in (25, 26, 27, 28, 29, 30, 31) if c in {cfg.ACQUIRED_INSTINCT_MASK_1, cfg.ACQUIRED_INSTINCT_MASK_2,
                                                                              cfg.H_PARENT_INSTINCTS_1, cfg.H_PARENT_INSTINCTS_2}), [25, 26, 27, 28])
        self.assertNotIn(29, {cfg.ACQUIRED_INSTINCT_MASK_1, cfg.ACQUIRED_INSTINCT_MASK_2, cfg.H_PARENT_INSTINCTS_1, cfg.H_PARENT_INSTINCTS_2})
        self.assertGreater(len(used), 20)


class ToolTests(unittest.TestCase):
    def test_grant_revoke_enlighten_keep_every_boundary_bit(self):
        h = humans()
        everyone = torch.tensor([True, True, True, True] + [False] * 12)
        first = torch.tensor([True] + [False] * 15)
        for bit in BITS:
            iat.tool_grant_instinct(ctx_for(h), h, everyone, bit)
        self.assertEqual(bits(h, 0), list(BITS))
        iat.tool_revoke_instinct(ctx_for(h), h, first, 24)
        iat.tool_revoke_instinct(ctx_for(h), h, first, 63)
        self.assertEqual(bits(h, 0), [0, 23, 47, 48])
        self.assertEqual(bits(h, 1), list(BITS))
        iat.tool_enlighten(ctx_for(h), h, 63)             # mask=None: every live human
        self.assertEqual(bits(h, 0), [0, 23, 47, 48, 63])
        self.assertEqual(bits(h, 1), list(BITS))

    def test_low_bits_still_land_in_the_legacy_column_exactly(self):
        h = humans()
        iat.tool_grant_instinct(ctx_for(h), h, torch.tensor([True] + [False] * 15), 5)
        self.assertEqual(float(h[0, cfg.ACQUIRED_INSTINCT_MASK]), 32.0)
        self.assertEqual((float(h[0, cfg.ACQUIRED_INSTINCT_MASK_1]), float(h[0, cfg.ACQUIRED_INSTINCT_MASK_2])), (0.0, 0.0))

    def test_inheritance_ors_the_parent_copy_including_high_words_into_the_young(self):
        h = humans(2)
        h[0, cfg.H_AGE] = 0.5
        ib.write_mask(h, 0, ib.bit_value(3) | ib.bit_value(40))
        ib.write_parent_mask(h, 0, ib.bit_value(30) | ib.bit_value(63) | ib.bit_value(1))
        h[1, cfg.H_AGE] = 5.0
        ib.write_parent_mask(h, 1, ib.bit_value(9))
        iat.tool_inherit_instinct(ctx_for(h), h)
        self.assertEqual(bits(h, 0), [1, 3, 30, 40, 63])
        self.assertEqual(bits(h, 1), [])                                          # not young: untouched

    def test_a_parent_with_only_a_high_word_still_counts(self):
        h = humans(1)
        h[0, cfg.H_AGE] = 0.0
        h[0, cfg.H_PARENT_INSTINCTS_2] = 1.0                                      # bit 48 only
        iat.tool_inherit_instinct(ctx_for(h), h)
        self.assertEqual(bits(h, 0), [48])

    def test_the_dispatcher_runs_instincts_registered_on_high_bits(self):
        h = humans(3)
        seen = []

        def instinct_probe(ctx, h_tensor=None, **_):
            seen.append(ctx["h_mask"].nonzero().flatten().tolist())

        saved = dict(iat.ACQUIRED_INSTINCTS)
        iat.ACQUIRED_INSTINCTS.clear()
        iat.ACQUIRED_INSTINCTS.update({50: instinct_probe})
        try:
            iat.tool_grant_instinct(ctx_for(h), h, torch.tensor([False, True, False] + [False] * 13), 50)
            iat.dispatch_acquired_instincts(ctx_for(h), h)
        finally:
            iat.ACQUIRED_INSTINCTS.clear()
            iat.ACQUIRED_INSTINCTS.update(saved)
        self.assertEqual(seen, [[1]])


class DeathAndReuseTests(unittest.TestCase):
    def test_death_clears_every_word_and_a_respawn_in_the_slot_starts_clean(self):
        h = humans(2)
        for bit in BITS:
            ib.grant(h, 0, bit)
        ib.write_parent_mask(h, 0, ib.bit_value(40) | ib.bit_value(63))
        h[0, cfg.HP] = 0.0
        pop = [2]
        iat.instinct_hp_death(ctx_for(h), h, pop)
        self.assertEqual((bits(h, 0), int(ib.read_parent_mask(h, 0)), pop[0]), ([], 0, 1))
        self.assertTrue(iat.instinct_born(h, pop, 1.0, 1.0, 0.0, 50.0))
        self.assertEqual((bits(h, 0), int(ib.read_parent_mask(h, 0))), ([], 0))


class MatingTests(unittest.TestCase):
    def test_the_child_receives_the_mothers_full_mask_as_its_parent_copy(self):
        h = humans(2)
        h[0, cfg.H_SEX], h[1, cfg.H_SEX] = 1.0, 0.0
        h[:2, cfg.X], h[:2, cfg.Y] = 100.0, 100.0
        for bit in (0, 23, 24, 47, 48, 63):
            ib.grant(h, 0, bit)
        pairwise = {"live_idx": torch.tensor([0, 1]), "within_mate": torch.ones((2, 2), dtype=torch.bool),
                    "seek_ready": torch.tensor([True, True]), "female": torch.tensor([True, False]),
                    "male": torch.tensor([False, True])}
        pop = [2]
        births = resolve_human_reproduction(h, pop, pairwise, birth_fn=iat.instinct_born)
        self.assertEqual(len(births), 1)
        child = births[0]["child_slot"]
        self.assertEqual(ib.bits_of(int(ib.read_parent_mask(h, child))), list(BITS))
        iat.tool_inherit_instinct(ctx_for(h), h)
        self.assertEqual(bits(h, child), list(BITS))


class SaveRestoreTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")

    def round_trip(self, mutate=None):
        payload = codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))
        if mutate:
            mutate(payload)
        world_snapshot.validate(payload, backend.engine)
        backend.engine.reset_world()
        world_snapshot.restore(payload, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)

    def test_a_save_keeps_high_bits_and_an_old_save_with_zero_high_words_loads(self):
        engine = backend.engine
        slot = int((engine.state.h_tensor[:, cfg.TYPE] > 0).nonzero()[0])
        for bit in BITS:
            ib.grant(engine.state.h_tensor, slot, bit)
        self.round_trip()
        self.assertEqual(bits(engine.state.h_tensor, slot), list(BITS))

        def as_old_save(payload):                                                # saves made before this change have zeros in 25..28
            payload["humans"][:, 25:29] = 0.0
        self.round_trip(as_old_save)
        self.assertEqual(bits(engine.state.h_tensor, slot), [0, 23])             # exactly what the old format could keep
        engine.step()


class DslTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """The legacy string DSL ``col19_bit(N) == 1`` and the structured ``instinct_bit`` selector see every bit 0..63."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")

    def test_string_and_structured_selectors_see_high_bits(self):
        engine = backend.engine
        agent = engine.execution_agent
        h = engine.state.h_tensor
        a, b = [int(i) for i in (h[:, cfg.TYPE] > 0).nonzero().flatten()[:2]]
        for bit in (3, 47):
            ib.grant(h, a, bit)
        ib.grant(h, b, 63)
        for bit, expected in ((3, [a]), (47, [a]), (63, [b]), (24, []), (0, [])):
            by_string = agent._resolve_human_selector(engine, f"col19_bit({bit}) == 1").nonzero().flatten().tolist()
            by_struct = agent._resolve_human_selector(engine, {"kind": "instinct_bit", "bit": bit, "value": 1}).nonzero().flatten().tolist()
            self.assertEqual((bit, by_string), (bit, expected))
            self.assertEqual((bit, by_struct), (bit, expected))
        clear = agent._resolve_human_selector(engine, {"kind": "instinct_bit", "bit": 63, "value": 0}).nonzero().flatten().tolist()
        self.assertNotIn(b, clear)
        self.assertIn(a, clear)


class ClientPayloadTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """Additive wire change: ``state.instincts`` stays the low 24 bits; ``state.instincts_hi`` (string) appears only when bit >= 24 is set."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")

    def test_instincts_hi_is_absent_without_high_bits_and_a_string_with_them(self):
        engine = backend.engine
        h = engine.state.h_tensor
        a, b = [int(i) for i in (h[:, cfg.TYPE] > 0).nonzero().flatten()[:2]]
        ib.grant(h, a, 5)
        ib.grant(h, b, 5)
        ib.grant(h, b, 24)
        ib.grant(h, b, 63)
        state_a = engine._export_human_base(a)["state"]
        state_b = engine._export_human_base(b)["state"]
        self.assertEqual((state_a["instincts"], "instincts_hi" in state_a), (32, False))
        self.assertEqual(state_b["instincts"], 32)                                   # low 24 bits, unchanged meaning
        self.assertEqual(state_b["instincts_hi"], str(1 | (1 << 39)))                # bit 24 -> 1, bit 63 -> 2**39
        self.assertIsInstance(state_b["instincts_hi"], str)


if __name__ == "__main__":
    unittest.main()
