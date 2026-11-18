# AGY 1010 Portal Report

## 1. What Changed
- Adapted and placed the spaces-aware portal regression test (`test_live_portal_spaces.gd`) into `godot_client_2d/tests/`, preserving its exact original semantics from `godot_client_2d/evidence/stage2_parity/test_live_portal_spaces.gd`.
- The test verifies that map lookup respects space-constraints and interior residents are properly tracked when interiors are separated from the main map.

## 2. Required Exact Validation Command
To validate the test, Codex should launch the backend with the required features and run the headless Godot client.

**Prerequisites (Backend):**
The backend must be running on a local port (e.g., 8080) with spaces flags enabled:
`EDEN_SPACES=1 EDEN_PERCEPTION_BOUNDED=1 EDEN_CHUNK_ROUTES=1`

**Client Test Command:**
Assuming the Godot executable is available as `godot` and the backend is listening on `http://127.0.0.1:8080`, execute the following from the `world_simulator` directory:
```bash
godot --headless --path godot_client_2d --script res://tests/test_live_portal_spaces.gd -- --backend-url=http://127.0.0.1:8080
```

*Alternatively, if integrated into the local test runner:*
```bash
python godot_client_2d/tools/run_live_tests.py portal_spaces
```
(Ensure the backend launched by the runner is configured with the `EDEN_SPACES=1`, `EDEN_PERCEPTION_BOUNDED=1`, and `EDEN_CHUNK_ROUTES=1` flags as done in `run_parity.py`'s `run2` phase).

## 3. Why It Depends on a Spaces-Enabled Backend
The test logic evaluates the C2 contract rules for spaces outlined in `1008_client_contract.md`. Without spaces (`EDEN_SPACES=0`), interior zones share the same coordinate layer as the main overworld, leading to coordinate overlaps and failures. With `EDEN_SPACES=1`, interiors are assigned distinct identity spaces that do not overlap with the main village. The test explicitly verifies this isolation by asserting that an inquiry at interior coordinates returns `""` when the active space is `starter_village`, and validates that only residents associated with the actively drawn space are tracked.

## 4. Verification Status
**Status:** IMPLEMENTED / validation owed

**What I have verified:**
- I have accurately placed the spaces-aware portal test into the client tests folder.
- The `res://` and scene paths remain structurally correct for the `tests/` directory environment.
- Evaluated necessary environment conditions and command-line execution contexts based on Stage 2 parity configurations and `run_parity.py`.

**What I have NOT verified:**
- The actual execution of the Godot test suite. Execution is delegated to the next Codex run, matching the non-execution constraints provided.
- Backend flag propagation within the `tools/run_live_tests.py` pipeline (must be supplied manually or configured in the runner logic).

## 5. Unresolved User Decisions (`1001decisios.md`)
None of the currently open user decisions block the validation of this independent test.
