# Stage 1 local delivery — 2026-10-07

The first playable Eden Godot 2D build is implemented and accepted for local evaluation through P0–P7 / Gate H. The coordinator reviewed the recorded integration evidence and final C9 artifacts; this is not a claim of an independent coordinator rerun of every live test. Models remain disabled: the verified gameplay runs use the rules decision provider. A4 running and door animation generation is a separate enhancement and has not been imported into this accepted build.

## Launch and Continue

From the repository root, with the configured `.venv` and installed Godot available on PATH or through `EDEN_GODOT`:

```powershell
powershell -ExecutionPolicy Bypass -File .\play.ps1
```

Choose New Game. The launcher prints `PLAY_DATA_ROOT` and owns the backend process. Use the in-game Save controls before quitting. To reopen that saved world, pass the actual printed directory and choose Continue:

```powershell
powershell -ExecutionPolicy Bypass -File .\play.ps1 -DataRoot .runtime\play-YYYYMMDD-HHMMSS
```

The timestamp above is a placeholder. Continue validates saved map revisions/hashes; a changed map may require an explicit New Game. The client README and in-game help describe possession, movement, interactions, god controls, deliberate Space+click attack, and Credits.

## Accepted evidence

| Requirement | Evidence and scope |
|---|---|
| Shared authored world | Coordinator validated all four canonical maps together with zero errors; eight residents, shared walls/anchors/portals, 48px tiles / 8 world units, foot-point coordinates and radius2.4. Current imported art/map hashes match the recorded build. |
| Normal gameplay and smith persistence | `godot_client_2d/evidence/gate_h/final/20261007-153224/`: actual client/backend, rules provider, normal45s forge, 12 segments / 101 checks / zero failures. Video1207.73s (20:07.7), bot1207.75s; actual backend restart and Continue preserve inventories/orders/memory without duplicate collection. Earlier failed recording attempts remain preserved. |
| Final client hardening | `godot_client_2d/C9_REPORT.md`: initial14-test batch10PASS/4FAIL preserved; corrected Heal/Credits, transport, scene and god reruns all PASS. Additional final persist rerun proves Continue and a rejected New preserve the previous world. These are split focused results, not a single new14/14 batch. Coordinator read PASS markers and checked final affected logs for ERROR lines; none found. |
| Actual healing | Final `evidence/c9_heal_proof.json`: real attack receipt at tick99, unpossessed ElsaHP83, Heal17 to100 at tick110, actual divine_heal event, matching visible memory and rendered attack/hit. The recording's earlier full-health heal was a no-op; this focused proof supplies actual restoration. The final one-tick attack_hit frame event was missed, explicitly retained as false. |
| Fault handling | Final sustained/transient/freshness reports all passed; coordinator checked structured results and logs. Lost collect records exactly one incoming collect attempt. Selective frame loss is detected around3.18s despite healthy other requests; delayed6s/12s old frames cannot roll back current state. No prediction or mutation replay. |
| Cleanup and notices | Final `evidence/c9_cleanup.json` reports successful process enumeration, no owned client-test processes, no port58261 listener or owned temporary roots. Credits expose notices copied byte-for-byte from `myassets/ASSET_NOTICES.md`. |
| Backend and performance | Coordinator executed557tests with no assertion failures but13sandboxPermissionErrors across10cases; all10affectedcases passed outside the sandbox. Claude separately reports a clean557-test suite and13/13 live harness before C9. Existing backend30/90-game-minute soaks report p99 below28ms and no deaths; these do not establish sustained client60fps or exact2x40Hz. |

The existing normal-duration recording plus final focused C9 evidence satisfies the agreed closure contract in scratchpad X-060. No redundant new20-minute recording ran. Final C9 changes are client-only; source art, backend, canonical maps and roster were preserved. Claude's proposed independent post-C9 verification remains an optional corroborating run after the A4 resource slot, not an additional implementation gate.

## Limits and follow-on work

This delivery uses the user's chosen generated art for local evaluation. Source/tool/model/settings and license status are recorded in `myassets/A3_FINAL_PROVENANCE_REVIEW.md` and `myassets/ASSET_NOTICES.md`; public distribution clearance is unclaimed. The ObjectDB-at-exit warning remains nonblocking. Model-driven decisions, prediction/replay, legacy3D/web maintenance and public publishing are outside this delivery. The recovery snapshot is local commit `9259455f99181fd559fda754ccba63088966e8c3` on `codex/legacy-3d-1006`, with tag `legacy-3d-1006`; no new commit or push was performed for this handoff.

A4 is assigned to the existing asset chat: original local-generated running, door-use, entry/exit and door-state frames, stable pivots and simple image sequences. Its first pilots will be reviewed before expansion or any coordinated client integration.
