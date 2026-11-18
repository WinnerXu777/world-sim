# R0.6 Test Robustness Repair Report: Calendar Harness Environment Isolation

**Date**: 2026-10-10 (TorontoOct10)  
**Author**: Antigravity  
**Task Scope**: R0.6 test robustness repair ONLY  
**Authorization**: Human authorized relevant roadmap source/tests sharing and implementation today TorontoOct10.  
**Files Modified**:
- `tests/test_harness_calendar.py`
- `coordination_evidence/agy_1010_calendar_testfix_report.md` (this report)

All production source code (`harness/calendar.py`, `systems/nature/weather.py`, `systems/schedule/resolver.py`, survival rates, default flags, persistence, and calendar refusal wording DR1 OPEN) and other test suites remained strictly **READ-ONLY**. No production logic was altered to make flag-on consumers legacy, and no assertions were skipped or weakened.

---

## 1. Executive Summary & Root Cause Analysis

Root executed `unittest` with ambient `EDEN_CALENDAR=1`:
- Subsystems passed: `emotion` (25 passed), `care` (passed), `calendar_rates` (10 passed), `calendar_consumers` (3 passed), `calendar_wire` (4 passed).
- `tests/test_harness_calendar.py` (19 tests) encountered **two failures**:
  1. `LegacyIsTodayTests.test_block_matches_the_resolver`: assertion failure at `tick=500` (`LEGACY` `'dawn'` vs `resolver` `'day'`).
  2. `LegacyIsTodayTests.test_season_matches_weather`: assertion failure at `tick=150` (`LEGACY` `'summer'` vs `weather` `'spring'`).

### Root Cause Verification

Source inspection of `harness/calendar.py`, `systems/nature/weather.py`, and `systems/schedule/resolver.py` revealed:

1. **`weather.season_for_tick(tick)` Delegation**:
   - `weather.season_for_tick(tick)` directly calls `harness.calendar.season_for_tick(tick)`, which invokes `active().season_for_tick(tick)`.
   - `active()` checks `calendar_enabled()`, which queries `os.environ.get("EDEN_CALENDAR", "") == "1"`.
   - When `EDEN_CALENDAR=1`, `active()` returns `cal.USER` (where 1 year = 96,000 ticks; 1 season = 24,000 ticks). At `tick=150`, phase is `150 / 96000 = 0.0015625 < 0.25`, which evaluates to `"spring"`.
   - In contrast, `cal.LEGACY.season_for_tick(150)` uses legacy constants (1 year = 600 ticks; 1 season = 150 ticks). At `tick=150`, phase is `(150 % 600) / 600 = 0.25`, which evaluates to `"summer"`.
   - Because `LegacyIsTodayTests.test_season_matches_weather` lacked environment scoping, running with ambient `EDEN_CALENDAR=1` caused `weather.season_for_tick(150)` to return `"spring"`, failing the equality check against `cal.LEGACY.season_for_tick(150)`.

2. **`resolver.tick_to_time_block(tick, ...)` Delegation**:
   - `resolver.tick_to_time_block` checks `_calendar.calendar_enabled()`.
   - When `EDEN_CALENDAR=1` and `day_length_ticks` matches the default (2,400 ticks), `harness.calendar.tick_to_time_block` delegates to `cal.USER.block_for_tick(tick)`.
   - For `cal.USER`, a game day is 12,000 ticks; in spring, daytime is 6,000 ticks with dawn lasting 500 ticks (`[0, 500)`). At `tick=500`, dawn has elapsed and the block is `"day"`.
   - In contrast, `cal.LEGACY.block_for_tick(500)` uses 4 equal quarters of 600 ticks (`500 // 600 == 0`), which evaluates to `"dawn"`.
   - Because `LegacyIsTodayTests.test_block_matches_the_resolver` lacked environment scoping, running with ambient `EDEN_CALENDAR=1` caused `resolver.tick_to_time_block(500)` to return `"day"`, failing the equality check against `cal.LEGACY.block_for_tick(500)`.

3. **Comparison with Existing Flag-Off Tests**:
   - `test_flag_off_the_module_accessors_are_legacy` in `LegacyIsTodayTests` had already used `with mock.patch.dict(os.environ, clear=False): os.environ.pop("EDEN_CALENDAR", None)`.
   - However, `test_season_matches_weather` and `test_block_matches_the_resolver` were unpatched, inadvertently inheriting the ambient runner's `EDEN_CALENDAR=1`.

---

## 2. Exact Changes Implemented

All changes were confined to `tests/test_harness_calendar.py`:

### A. Class-Level Environment Isolation (`setUp` and `addCleanup`)
To ensure test setups cannot leak environment mutations across tests or between test classes:
- Added `setUp` with `patcher = mock.patch.dict(os.environ, clear=False); patcher.start(); self.addCleanup(patcher.stop)` to all four test classes:
  - `LegacyIsTodayTests`
  - `UserCalendarTests`
  - `ResolverDelegationTests`
  - `RatesAndFlagTests`
- This ensures any environment modification made during any test method is guaranteed to be restored to the pre-test ambient state immediately upon completion, even in the event of an unhandled exception.

### B. Explicit Scoping of Flag-Off Assertions Across Absent and `"0"`
In `LegacyIsTodayTests`, all legacy assertions are now explicitly evaluated under both canonical flag-off states:
1. `EDEN_CALENDAR` absent (`os.environ.pop("EDEN_CALENDAR", None)`)
2. `EDEN_CALENDAR="0"` (`os.environ["EDEN_CALENDAR"] = "0"`)

- **`test_season_matches_weather`**:
  - Full loop over `({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"})`.
  - Preserved **all** original exhaustive tick assertions:
    - 5,000 linear ticks (`0..4999`),
    - 2,000 pseudorandom ticks (`rng.randrange(0, 10_000_000)` with seed 1008),
    - Boundary ticks (`[599, 600, 601, 149, 150, 299, 300, 449, 450, 2399, 2400]`),
    - Float boundary ticks `(0.0, 149.999, 150.0, 599.5, 1234.75)`.

- **`test_block_matches_the_resolver`**:
  - Full loop over `({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"})`.
  - Preserved **all** original exhaustive tick assertions:
    - Default day length across all 7,000+ ticks in `self.ticks()`,
    - Custom lengths `(4, 5, 7, 100, 1000, 2400, 9999)` for `range(0, 300, 7)`.

- **`test_flag_off_the_module_accessors_are_legacy`**:
  - Scoped across both `EDEN_CALENDAR` absent and `"0"`.

- **`ResolverDelegationTests.test_flag_off_is_the_old_function`**:
  - Scoped across both `EDEN_CALENDAR` absent and `"0"`.

### C. Meaningful Nested External Flag-On Restoration Assertions
To satisfy the requirement for meaningful nested external restoration (without relying on trivial self-mirroring assertions that merely check `os.environ` keys):
- In `test_season_matches_weather`:
  ```python
  with mock.patch.dict(os.environ, ON):
      self.assertEqual(weather.season_for_tick(150), "spring")
      self.assertEqual(weather.season_for_tick(150), cal.USER.season_for_tick(150))
      with mock.patch.dict(os.environ, clear=False):
          os.environ.pop("EDEN_CALENDAR", None)
          self.assertEqual(weather.season_for_tick(150), "summer")
          self.assertEqual(weather.season_for_tick(150), cal.LEGACY.season_for_tick(150))
      self.assertEqual(weather.season_for_tick(150), "spring")
      self.assertEqual(weather.season_for_tick(150), cal.USER.season_for_tick(150))
  ```
- In `test_block_matches_the_resolver`:
  ```python
  with mock.patch.dict(os.environ, ON):
      self.assertEqual(resolver.tick_to_time_block(500), "day")
      self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))
      with mock.patch.dict(os.environ, clear=False):
          os.environ.pop("EDEN_CALENDAR", None)
          self.assertEqual(resolver.tick_to_time_block(500), "dawn")
          self.assertEqual(resolver.tick_to_time_block(500), cal.LEGACY.block_for_tick(500))
      self.assertEqual(resolver.tick_to_time_block(500), "day")
      self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))
  ```
- In `test_flag_off_the_module_accessors_are_legacy`:
  ```python
  with mock.patch.dict(os.environ, ON):
      self.assertIs(cal.active(), cal.USER)
      with mock.patch.dict(os.environ, clear=False):
          os.environ.pop("EDEN_CALENDAR", None)
          self.assertIs(cal.active(), cal.LEGACY)
      self.assertIs(cal.active(), cal.USER)
  ```
- In `ResolverDelegationTests.test_flag_off_is_the_old_function`:
  ```python
  with mock.patch.dict(os.environ, ON):
      self.assertEqual(resolver.tick_to_time_block(500), "day")
      with mock.patch.dict(os.environ, clear=False):
          os.environ.pop("EDEN_CALENDAR", None)
          self.assertEqual(resolver.tick_to_time_block(500), "dawn")
      self.assertEqual(resolver.tick_to_time_block(500), "day")
  ```

These verify:
1. Outer flag-on mode causes real subsystems (`weather`, `resolver`, `cal`) to return USER profile behavior.
2. An inner nested flag-off block causes those subsystems to revert to LEGACY behavior.
3. Exiting the nested inner block fully restores the outer flag-on behavior.
4. Exiting the outer block fully restores whatever ambient environment existed prior to the test.

---

## 3. Flag-Sensitive Behavior Matrix

| Subsystem Call | Flag-Off (`EDEN_CALENDAR` absent / `0`) | Flag-On (`EDEN_CALENDAR=1`) | Verification Note |
|---|---|---|---|
| `cal.active()` | `cal.LEGACY` | `cal.USER` | Tested in `RatesAndFlagTests` & accessors |
| `weather.season_for_tick(150)` | `"summer"` (150/600 = 0.25) | `"spring"` (150/96000 = 0.00156) | Scoped flag-off + nested flag-on restoration |
| `resolver.tick_to_time_block(500)` (default length 2400) | `"dawn"` (500 < 600) | `"day"` (500 in `[500, 5500)` spring) | Scoped flag-off + nested flag-on restoration |
| `resolver.tick_to_time_block(t, day_length_ticks=1000)` | 4 equal quarters of 250 ticks | 4 equal quarters of 250 ticks | Custom day length caller preserves quarters in both modes |
| `cal.rate_scale("needs")` | `1.0` | `0.21` | Tested in `RatesAndFlagTests` |
| `cal.age_step()` | `1.0 / 600` | `1.0 / 12000` | Decoupled 1 life-year per game day in USER mode |

---

## 4. Test Invariant & Robustness Checklist

- [x] **Zero Production Alterations**: Production rates, flags, constants, consumer delegates, and refusal strings are untouched.
- [x] **No Skipped or Weakened Assertions**: All 7,000+ random and edge ticks remain strictly asserted.
- [x] **Total Test Count Preserved**: Exactly 19 tests in `tests/test_harness_calendar.py`.
- [x] **Bidirectional Environment Compatibility**:
  - When executed under `EDEN_CALENDAR=1`, all 19 tests pass without inheriting flag pollution.
  - When executed under `EDEN_CALENDAR` absent or `0`, all 19 tests pass without leaking flag state.
- [x] **R0.6 Status Note**: Repair is restricted to test harness robustness. Whole R0.6 remains pending separate calendar scenario and market-scenario subprocess check under long calendar.
