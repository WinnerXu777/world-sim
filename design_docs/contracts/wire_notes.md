# 1008 wire notes (additive changes to what the server sends clients)

Rule for this file: every change here is additive. No existing field changes meaning or type. No Godot or JS edit is required.

## `state.instincts_hi` (G-D0-2, commit "step 4")
Human payload (`_export_human_base` -> `state`). Present only when the resident has an acquired-instinct bit >= 24 set; absent otherwise,
so worlds that never grant such a bit send byte-identical payloads.

* `state.instincts` (int): unchanged, the low 24 bits (bits 0..23) of the mask.
* `state.instincts_hi` (string, decimal): the mask shifted right by 24, i.e. bit 24 -> value 1, bit 47 -> 2**23, bit 63 -> 2**39.
  A string because it can exceed JavaScript's exact integer range (2**53). Client reading: `BigInt(state.instincts_hi)`, bit `n >= 24` is
  set when `(BigInt(hi) >> BigInt(n - 24)) & 1n`.
* Source columns in `h_tensor`: 19/25/26 (mask words) and 23/27/28 (parent copy). Columns 29..31 remain reserved.

Test: `tests/test_harness_gd02_legacy.py` `ClientPayloadTests`.
