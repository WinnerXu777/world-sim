# R0.2 strict golden verification — 2026-10-10

Status: PASS for the captured stage snapshot after runtime-access retry. All four strict modes passed. This is not final at-HEAD/full-suite evidence; initial environment-failure logs are preserved below.

Captured 2026-10-10T08:35:01-04:00 (America/Toronto). HEAD `b555adc33776696f529ae9e4047c88acdb42f408`. Snapshot `C:\Users\Rita\Desktop\caleb\world_simulator\.runtime\codex-r02-dba1ebaf73`.
Archive SHA-256 `bde85015e7241c1e1affc598c8aa73f3e902641947f8e8ba28ded51fa39051de`. Composite snapshot SHA-256 `c386c6ba115cb477de80ae6bab30f28ec2e7fb731caa4429f2fa7d5497db72ab`.
Full overlay and support-file hashes are in `coordination_evidence/codex_1010_r02_snapshot.json`.

Snapshot is git archive HEAD plus every modified tracked path and untracked source/test path under at_the_beginning, model_server, tools, tests and world_data, plus required myassets and fixture sprites. No client snapshot/visual acceptance claimed. All inherited EDEN_* variables removed in the child environment; each mode sets only its intended flags and headless isolation.

| Mode | Exit | Seconds |
| --- | --- | --- |
| default | 1 | 4.1 |
| resources | 1 | 2.2 |
| spaces | 1 | 2.2 |
| window-hook | 1 | 2.2 |

Each command used `tools/golden_trace.py --check --strict` with default seed 1008 / 3600 ticks and its indicated mode, saving fresh traces with `--out` and complete logs. No record mode, default flag change or reference rewrite.

Working source changed after capture: False. These results cover the immutable snapshot, including all recorded ownership overlays; they do not certify later edits, R0.1 full suite, live client/portal behavior, ecology or final HEAD.

Owned NORMAL lock acquired atomically once after the economy worker released it, held throughout capture/tests, and released only if its owner token still matched. No other lock removed. Snapshot, HEAD archive, manifest, traces and logs retained. No commits/pushes or code repairs performed.

## Runtime-access retry

Initial failures were Windows PermissionError creating ResidentAgents, before any golden comparison. Original logs are preserved. Retried the same hash-verified immutable snapshot with filesystem access.

Status: PASS for this stage snapshot only; no final at-HEAD/full-suite claim.

- default: exit 0, 49.0 seconds; C:\Users\Rita\Desktop\caleb\world_simulator\coordination_evidence\codex_1010_r02_retry_default.log
- resources: exit 0, 55.1 seconds; C:\Users\Rita\Desktop\caleb\world_simulator\coordination_evidence\codex_1010_r02_retry_resources.log
- spaces: exit 0, 51.8 seconds; C:\Users\Rita\Desktop\caleb\world_simulator\coordination_evidence\codex_1010_r02_retry_spaces.log
- window-hook: exit 0, 59.6 seconds; C:\Users\Rita\Desktop\caleb\world_simulator\coordination_evidence\codex_1010_r02_retry_window-hook.log

## Root ancestry check
Root independently verified git merge-base --is-ancestor for7a81dee(sleep),2ca80d9(darkness),59d9796(clothing), each exit0 against HEADb555adc. Thus the captured snapshot includes the three commits named by R0.2. The four no-drift strict traces close this stage's flag-off check for those commits; later ration/telemetry changes still require their own checks, and R0.1 fullsuite/current-HEAD gate remains unproved.
