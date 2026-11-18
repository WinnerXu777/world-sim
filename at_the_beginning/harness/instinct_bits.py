"""Exact 64-bit acquired-instinct masks stored as three 24-bit words in float32 columns (G-D0-2, option A').

``h_tensor`` is float32, which holds integers exactly only below 2**24, so a 64-bit mask kept in one column loses bits. The mask is
split into three words, each an integer below 2**24 (exact in float32):

    word 0 = bits  0..23  -> column 19 (ACQUIRED_INSTINCT_MASK, unchanged)     parent copy: column 23 (H_PARENT_INSTINCTS)
    word 1 = bits 24..47  -> column 25 (ACQUIRED_INSTINCT_MASK_1)                             column 27 (H_PARENT_INSTINCTS_1)
    word 2 = bits 48..63  -> column 26 (ACQUIRED_INSTINCT_MASK_2)                             column 28 (H_PARENT_INSTINCTS_2)

Bits 0..23 behave exactly as before (same column, same tensor operations), so worlds that never grant a higher bit are unchanged.
Bit 63 is the int64 sign bit: masks are int64 tensors, built with torch shifts so that it round-trips.
Rows are zeroed as a whole on death and respawn, so the new words are cleared with the row.
"""
from __future__ import annotations

import torch

WORD_BITS = 24
WORD_MASK = (1 << WORD_BITS) - 1
TOP_MASK = (1 << 16) - 1                    # word 2 holds bits 48..63 only
MAX_BIT = 63
MASK_COLS = (19, 25, 26)
PARENT_COLS = (23, 27, 28)


def _check_bit(bit: int) -> int:
    if not isinstance(bit, int) or isinstance(bit, bool) or not 0 <= bit <= MAX_BIT:
        raise ValueError(f"instinct bit must be an integer in 0..{MAX_BIT}, got {bit!r}")
    return bit


def bit_value(bit: int) -> torch.Tensor:
    """The one-bit int64 mask for ``bit`` (bit 63 wraps to the sign bit, as a 64-bit mask should)."""
    return torch.tensor(1, dtype=torch.int64) << _check_bit(bit)


def read_mask(h: torch.Tensor, rows, cols=MASK_COLS) -> torch.Tensor:
    """int64 mask of the selected rows (``rows``: bool mask, index tensor or int slot)."""
    w0, w1, w2 = (h[rows, c].long() for c in cols)
    return w0 | (w1 << WORD_BITS) | (w2 << (2 * WORD_BITS))


def write_mask(h: torch.Tensor, rows, mask: torch.Tensor, cols=MASK_COLS) -> None:
    """Store an int64 mask into the selected rows as three exact float32 words."""
    mask = torch.as_tensor(mask, dtype=torch.int64)
    h[rows, cols[0]] = (mask & WORD_MASK).float()
    h[rows, cols[1]] = ((mask >> WORD_BITS) & WORD_MASK).float()
    h[rows, cols[2]] = ((mask >> (2 * WORD_BITS)) & TOP_MASK).float()


def read_parent_mask(h: torch.Tensor, rows) -> torch.Tensor:
    return read_mask(h, rows, PARENT_COLS)


def write_parent_mask(h: torch.Tensor, rows, mask: torch.Tensor) -> None:
    write_mask(h, rows, mask, PARENT_COLS)


def has_parent_bits(h: torch.Tensor) -> torch.Tensor:
    """Bool per row: the parent copy holds at least one bit (any of its three words is non-zero)."""
    return (h[:, PARENT_COLS[0]] != 0.0) | (h[:, PARENT_COLS[1]] != 0.0) | (h[:, PARENT_COLS[2]] != 0.0)


def test_bit(h: torch.Tensor, bit: int, cols=MASK_COLS) -> torch.Tensor:
    """Bool per row: is ``bit`` set. For bits 0..23 this is exactly the legacy expression on column 19."""
    _check_bit(bit)
    word, shift = divmod(bit, WORD_BITS)
    return ((h[:, cols[word]].long() >> shift) & 1).bool()


def grant(h: torch.Tensor, rows, bit: int) -> None:
    write_mask(h, rows, read_mask(h, rows) | bit_value(bit))


def revoke(h: torch.Tensor, rows, bit: int) -> None:
    write_mask(h, rows, read_mask(h, rows) & ~bit_value(bit))


def bits_of(mask: int) -> list:
    """Sorted bit numbers set in a Python int (accepts a signed int64 value)."""
    mask &= (1 << 64) - 1
    return [b for b in range(64) if mask >> b & 1]


def inherit_words(h: torch.Tensor, child: int, mother: int) -> None:
    """Birth: copy the mother's words 1 and 2 (bits 24..63) into the child's parent copy. Word 0 travels through
    ``instinct_born(parent_instincts=...)`` unchanged, so this works with any birth function."""
    h[child, PARENT_COLS[1]] = h[mother, MASK_COLS[1]]
    h[child, PARENT_COLS[2]] = h[mother, MASK_COLS[2]]


def high_payload(row: torch.Tensor) -> dict:
    """Client payload addition for one human row: ``{"instincts_hi": "<decimal string>"}`` when any bit 24..63 is set, else ``{}``.
    The value is the mask shifted right by 24 (bit 24 -> 1), as a string because it can exceed JavaScript's exact integer range
    (2**53). ``instincts`` keeps its meaning: the low 24 bits."""
    hi = int(row[MASK_COLS[1]]) | (int(row[MASK_COLS[2]]) << WORD_BITS)
    return {"instincts_hi": str(hi)} if hi else {}
