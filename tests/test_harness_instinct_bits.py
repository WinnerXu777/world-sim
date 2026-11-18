"""G-D0-2 option A': exact 64-bit acquired-instinct masks as three 24-bit float32 words (helper module)."""
import random
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import instinct_bits as ib  # noqa: E402

EDGE_BITS = (0, 1, 22, 23, 24, 25, 46, 47, 48, 49, 62, 63)


def blank(rows=6):
    return torch.zeros((rows, 32))


class RoundTripTests(unittest.TestCase):
    def test_every_single_bit_round_trips_exactly(self):
        for bit in range(64):
            h = blank()
            ib.grant(h, torch.tensor([True, False, True, False, False, False]), bit)
            got = ib.read_mask(h, torch.arange(6))
            self.assertEqual(ib.bits_of(int(got[0])), [bit], bit)
            self.assertEqual(ib.bits_of(int(got[1])), [], bit)
            self.assertTrue(bool(ib.test_bit(h, bit)[0]) and not bool(ib.test_bit(h, bit)[1]), bit)

    def test_random_multi_bit_masks_round_trip_including_the_ones_float32_loses(self):
        rng = random.Random(1008)
        for _ in range(300):
            bits = sorted(rng.sample(range(64), rng.randrange(1, 12)))
            mask = 0
            for b in bits:
                mask |= 1 << b
            h = blank(1)
            ib.write_mask(h, 0, torch.tensor(mask - (1 << 64) if mask >= 1 << 63 else mask, dtype=torch.int64))
            self.assertEqual(ib.bits_of(int(ib.read_mask(h, 0))), bits)
            self.assertTrue(all(bool(ib.test_bit(h, b)[0]) for b in bits))
            self.assertFalse(any(bool(ib.test_bit(h, b)[0]) for b in range(64) if b not in bits))

    def test_the_legacy_float32_column_does_lose_these_bits(self):
        legacy = torch.zeros((1, 32))
        legacy[0, 19] = float((1 << 0) | (1 << 30))
        self.assertEqual(ib.bits_of(int(legacy[0, 19].long())), [30])      # bit 0 vanished: the defect this module removes

    def test_the_words_are_exact_float32_integers(self):
        h = blank(1)
        ib.write_mask(h, 0, torch.tensor(-1, dtype=torch.int64))          # all 64 bits
        self.assertEqual([int(h[0, c]) for c in ib.MASK_COLS], [(1 << 24) - 1, (1 << 24) - 1, (1 << 16) - 1])
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 0))), list(range(64)))


class GrantRevokeTests(unittest.TestCase):
    def test_grant_is_or_and_revoke_clears_only_that_bit(self):
        h = blank(2)
        rows = torch.tensor([True, True])
        for bit in (0, 23, 24, 47, 48, 63):
            ib.grant(h, rows, bit)
        ib.revoke(h, torch.tensor([True, False]), 24)
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 0))), [0, 23, 47, 48, 63])
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 1))), [0, 23, 24, 47, 48, 63])
        ib.grant(h, torch.tensor([True, False]), 24)                      # idempotent re-grant
        ib.grant(h, torch.tensor([True, False]), 24)
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 0))), [0, 23, 24, 47, 48, 63])

    def test_low_bits_use_column_19_exactly_like_the_legacy_code(self):
        h = blank(2)
        ib.grant(h, torch.tensor([True, False]), 5)
        legacy = blank(2)
        legacy[0, 19] = float(int(legacy[0, 19].long()) | (1 << 5))
        self.assertTrue(torch.equal(h, legacy))
        self.assertTrue(torch.equal(ib.test_bit(h, 5), ((legacy[:, 19].long() >> 5) & 1).bool()))

    def test_bit_arguments_are_validated(self):
        for bad in (-1, 64, 1.5, True, None, "3"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ib.bit_value(bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                ib.test_bit(blank(), bad)


class ParentCopyAndRowClearTests(unittest.TestCase):
    def test_parent_copy_keeps_high_bits_and_inheritance_ors_them_in(self):
        h = blank(2)
        mother = torch.tensor(1 | (1 << 30), dtype=torch.int64) | ib.bit_value(63)
        ib.write_mask(h, 0, mother)
        ib.write_parent_mask(h, 1, ib.read_mask(h, 0))                    # birth copies the mother's mask
        self.assertTrue(bool(ib.has_parent_bits(h)[1]) and not bool(ib.has_parent_bits(h)[0]))
        ib.write_mask(h, 1, ib.read_mask(h, 1) | ib.read_parent_mask(h, 1))
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 1))), [0, 30, 63])

    def test_a_parent_with_only_a_high_word_counts_as_having_parent_bits(self):
        h = blank(1)
        h[0, ib.PARENT_COLS[2]] = 1.0
        self.assertTrue(bool(ib.has_parent_bits(h)[0]))

    def test_zeroing_a_row_clears_every_word_so_a_reused_slot_starts_clean(self):
        h = blank(2)
        for bit in EDGE_BITS:
            ib.grant(h, torch.tensor([True, True]), bit)
        ib.write_parent_mask(h, torch.tensor([True, True]), ib.read_mask(h, torch.tensor([True, True])))
        h[0] = 0.0                                                         # what death/despawn/spawn do to a row
        self.assertEqual(int(ib.read_mask(h, 0)), 0)
        self.assertEqual(int(ib.read_parent_mask(h, 0)), 0)
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 1))), sorted(EDGE_BITS))

    def test_a_snapshot_style_copy_of_the_whole_tensor_preserves_masks(self):
        h = blank(3)
        ib.grant(h, torch.tensor([True, False, True]), 47)
        ib.grant(h, torch.tensor([True, False, True]), 0)
        restored = blank(3)
        restored.copy_(h.clone())
        self.assertEqual(ib.bits_of(int(ib.read_mask(restored, 2))), [0, 47])
        old_save = h.clone()
        old_save[:, 25:29] = 0.0                                           # saves made before this change have zeros there
        self.assertEqual(ib.bits_of(int(ib.read_mask(old_save, 0))), [0])


if __name__ == "__main__":
    unittest.main()
