# G-D0-2 migration plan: acquired-instinct bits above 24 (NO CODE WRITTEN)

Status: plan only, awaiting the orchestrator's OK on the file list in section 6. Author: harness worker (837dca).

## 1. The defect (measured, not assumed)
`h_tensor` is float32. Column 19 (`ACQUIRED_INSTINCT_MASK`) stores an integer bit mask as `float(mask)`. float32 holds integers exactly only below 2**24, so a mask whose set bits span more than 24 positions is rounded and low bits vanish (`{0,30}` becomes `{30}`). `tests/test_harness_known_bugs.py` (GD02, 2 tests) pins today's behaviour. `H_PARENT_INSTINCTS` (col 23, copy of the mother's mask at birth) has the same defect. The engine allocates bits 0..63 (`runtime/execution_validation.py:_next_available_instinct_bit`). Not measured: how often a real run grants a bit >= 24 (the stock instincts use low bits).

## 2. Finding that changes the recommendation
I first proposed option B (a separate int64 side table). Reading the code shows two facts that make a simpler option safer:

* `genesis_config.py:105` reserves **columns 25..31** of `h_tensor` (7 free float32 columns). A grep over `at_the_beginning/`, `tests/`, `model_server/` found no code reading columns 25..31 of `h_tensor` (the one `[:, 31]` hit in `tests/test_worldgen_generate.py:186` is a different array).
* Death and despawn zero the **whole row**: `h_tensor[dead] = 0.0` (`instincts_and_tools.py` 1125, 1135, 2736; `systems/health/effects.py:64`), and `spawn_human` zeroes the row first (line 972). A side table indexed by slot would NOT be cleared by those paths (5+ sites that I would have to find and edit, and a missed one lets a dead resident's instincts leak to the next occupant of the slot). Extra columns inside `h_tensor` are cleared by the same statements for free.
* `world_snapshot.capture/validate/restore` saves `h_tensor` whole and checks its shape and dtype only. A side table would add a new payload key plus a migration for old saves; extra columns need neither.

**Recommended option (call it A'): split the mask into 24-bit words across reserved columns.**

| word | bits | h_tensor column | exact in float32 |
|---|---|---|---|
| 0 | 0..23 | 19 (`ACQUIRED_INSTINCT_MASK`, unchanged) | yes (< 2**24) |
| 1 | 24..47 | 25 (new `ACQUIRED_INSTINCT_MASK_1`) | yes |
| 2 | 48..63 | 26 (new `ACQUIRED_INSTINCT_MASK_2`) | yes |
| parent 0 | 0..23 | 23 (`H_PARENT_INSTINCTS`, unchanged) | yes |
| parent 1 | 24..47 | 27 (new `H_PARENT_INSTINCTS_1`) | yes |
| parent 2 | 48..63 | 28 (new `H_PARENT_INSTINCTS_2`) | yes |

Columns 29..31 stay reserved. A new helper module `harness/instinct_bits.py` (mine) provides `read_mask(h, rows) -> int64 tensor` and `write_mask(h, rows, mask_int64)` (and the parent equivalents). Legacy code calls the helper instead of `.long()` / `.float()` on col 19.

Why this is exact: each word is an integer below 2**24, so `float(word)` and `.long()` round-trip exactly. Bit 63 is the int64 sign bit: the helper reassembles with torch int64 shifts (`w0 | w1 << 24 | w2 << 48`) and masks on the way out (`(x >> 48) & 0xFFFF`), so it works for negative values; legacy `1 << bit` for bit 63 would overflow a Python-int-to-int64 conversion, so the helper takes `bit` and builds the one-bit mask as `torch.tensor(1, dtype=torch.int64) << bit`.

### Options compared
| | A' (reserved columns, recommended) | B (int64 side table) | C (per-resident Python set) |
|---|---|---|---|
| exact bits | 0..63 | 0..63 | unbounded |
| h_tensor shape/dtype | unchanged (32 cols) | unchanged | unchanged |
| snapshot change | none; old saves load (new columns are 0) | new payload key + migration for old saves | resident store schema |
| cleared on death/respawn | automatic (row zeroing) | must edit 5+ zeroing sites | must edit store |
| per-tick cost | 3 column reads per bit test (dispatch loop reads col 19 once per registered instinct bit today) | 1 read | Python loop over residents |
| legacy sites edited | 12 (section 4) | 12 + 5 zeroing + snapshot | more |

## 3. Does any save or snapshot store these columns?
Yes, whole-tensor: `persistence/world_snapshot.py` `capture` puts `engine.state.h_tensor` in the payload and `restore` does `h_tensor.copy_(payload["humans"])` after `validate` compares **shape and dtype only**. With option A' the shape stays `(100, 32)`, so: new saves carry the new words; old saves restore with columns 25..28 equal to 0, which is exactly right because bits >= 24 were already lost in them (the loss happened before the save). No schema bump, no migration code. Still true for B only if I add a key; hence A'.
`ENGINE_FIELDS` and `instinct_bits` (name -> bit mapping, in the payload) are unaffected.

## 4. The twelve sites and the exact edit
All line numbers are from today's tree. `M` = `mask`, `read_mask/write_mask` from `harness/instinct_bits.py`.

| # | file:line | today | edit |
|---|---|---|---|
| 1 | `instincts_and_tools.py:2743-2744` `tool_grant_instinct` | `current = h[affected, 19].long(); h[affected, 19] = (current \| (1 << bit)).float()` | `write_mask(h, affected, read_mask(h, affected) \| bit_value(bit))` |
| 2 | `:2749-2750` `tool_revoke_instinct` | `current & ~(1 << bit)` | `read_mask(...) & ~bit_value(bit)` |
| 3 | `:2757-2759` `tool_inherit_instinct` | `parent_bits = h[young, 23].long(); ... \| parent_bits` | `parent = read_parent_mask(h, young)`; OR into `read_mask`; test for "has parent instincts" becomes any of cols 23, 27, 28 non-zero |
| 4 | `:2755` filter `h[:, 23] != 0.0` in the same function | col 23 only | `parent_any_mask(h)` (cols 23, 27, 28) |
| 5 | `:2816-2817` `tool_enlighten` | same as 1 | same as 1 |
| 6 | `:3277` `dispatch_acquired_instincts` | `((h[:, 19].long() >> bit) & 1).bool()` | `test_bit(h, bit)` helper (picks the word) |
| 7 | `:992` `spawn_human` init `r[19] = 0.0` | zero | unchanged (row is already zeroed at 972; new columns are zero too) |
| 8 | `:996` `r[H_PARENT_INSTINCTS] = parent_instincts` | one float | add optional kwargs `parent_instincts_1=0.0, parent_instincts_2=0.0` writing cols 27 and 28 (default keeps all existing callers valid) |
| 9 | `map_test.py:2599` birth copy | `parent_instincts=float(h[mother, 19])` | also pass `parent_instincts_1=float(h[mother, 25]), parent_instincts_2=float(h[mother, 26])` |
| 10 | `systems/social/mating.py:117` | same as 9 | same as 9 |
| 11 | `map_test.py:4511` client payload `"instincts": int(row[19])` | low word only | `"instincts": int(read_mask(h, slot))` (JSON int up to 2**63; the client currently receives at most 2**24, see risk R2) |
| 12 | `runtime/execution_selectors.py:409` and `:573` (string DSL `col19_bit(N) == 1` and structured `instinct_bit`) | `>> bit` on col 19 | `test_bit(tensor, bit)` |

Not edited: `genesis_config.py` gets three new constant pairs (`ACQUIRED_INSTINCT_MASK_1 = 25`, `_2 = 26`, `H_PARENT_INSTINCTS_1 = 27`, `_2 = 28`), and the comment `# 25-31 reserved` becomes `# 29-31 reserved`. The harness adapter (`harness/adapter.py`, mine) adds the new fields; `target_selectors` `bit_set/bit_clear` gain exact support above 2**24 through the helper (mine).

## 5. How the legacy string-DSL bit tests map
`col19_bit(N) == 1` (regex in `execution_selectors.py:406`) and the structured `{"kind": "instinct_bit", "bit": N, "value": 0|1}` both currently shift col 19. After the edit both call `test_bit(tensor, N)`, which for N < 24 reads col 19 exactly as before (same tensor ops, same result), for 24 <= N < 48 col 25, for 48 <= N < 64 col 26. The DSL text and JSON shapes do not change, so stored decision rules and tests keep working. Bits >= 64 stay an error as today (`_next_available_instinct_bit` raises).

## 6. Expected golden-trace effect, and what I will touch
* Golden (`tools/golden_trace.py --check --strict`, seed 1008, 3600 ticks): columns 25..28 are zero throughout and every changed code path computes the same word-0 values with the same operations on the low word, so I expect the hashes to be **identical**. I will verify, not assume; if they differ I stop and report.
* New tests: round-trip of every bit 0..63 and of random multi-bit masks through grant/revoke/inherit/dispatch; despawn/respawn does not leak words 1 and 2 (the row-zeroing property); snapshot capture/restore keeps a mask with bits {0, 30, 50}; old-save simulation (new columns zeroed) loads; the two GD02 known-bug tests flip to "fixed" tests.
* Legacy files I would edit (each needs your OK, section 7): `instincts_and_tools.py` (sites 1-8), `map_test.py` (sites 9, 11, plus nothing else), `systems/social/mating.py` (site 10), `runtime/execution_selectors.py` (site 12), `genesis_config.py` (4 constants and the comment). New file `harness/instinct_bits.py`; tests under `tests/test_harness_*`.

## 7. Risks, stated plainly
* R1: any code that sums, compares or sends the full h_tensor row (hashes, client delta frames) now sees columns 25..28; they are zero unless a high bit is granted, so no change today. Unverified: whether the Godot/JS client assumes columns 25..31 are always zero (I did not read the client; not mine to touch).
* R2: JSON `instincts` value can now exceed 2**24 and 2**53 (JavaScript number precision above 2**53). Bits >= 53 would be inexact in a JS client. Options: send it as a string, or leave `instincts` as the low word plus a new `instincts_hi` field. Needs the client owner's decision; default I would take: keep `instincts` = low 24 bits unchanged and add `instincts_hi` (word 1 and 2 combined as a string).
* R3: three column reads per tested bit instead of one is a small per-tick cost in `dispatch_acquired_instincts` only for registered high bits; low bits read one column exactly as today. I will measure it in MEASURE mode after implementing.
* R4: no one else may start using columns 25..28; the constants make the claim explicit and a test asserts the four are unused by `genesis_config` names.

## 8. Decision requested
OK to implement A' (instead of B) with the exact file list in section 6? If you prefer B anyway, say so; the plan changes to a side tensor plus the 5+ zeroing sites and a snapshot key, which I consider the riskier path.
