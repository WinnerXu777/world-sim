"""Seeded headless golden trace of the legacy engine (WS-H characterization).

    .venv/Scripts/python.exe tools/golden_trace.py --record            # (re)write tests/golden/trace_seed<N>.json
    .venv/Scripts/python.exe tools/golden_trace.py --check             # compare a fresh run with the stored golden
    .venv/Scripts/python.exe tools/golden_trace.py --out run.json      # just write the trace of a fresh run
    .venv/Scripts/python.exe tools/golden_trace.py --resources --check # same with EDEN_MAP_RESOURCES=1 against trace_seed<N>_resources.json
    .venv/Scripts/python.exe tools/golden_trace.py --sparse-geo --check [--resources|--spaces]   # sparse map_geo masks: same golden files, strict equal
    .venv/Scripts/python.exe tools/golden_trace.py --spaces --check    # EDEN_SPACES=1 + EDEN_PERCEPTION_BOUNDED=1 against trace_seed<N>_spaces.json
    .venv/Scripts/python.exe tools/golden_trace.py --window-hook --check --strict   # the streaming-window hook on the finite world: equals trace_seed<N>_resources_spaces.json

Runs the real two-map starter village (8 residents, no player) for ``--ticks`` ticks in a fresh process with all global
RNGs seeded, and records at checkpoint ticks: exact sha256 of ``h_tensor``/``m_tensor``, a rounded numeric summary that
survives harmless float noise, and the key per-resident state. A golden file is the reference for "did this change
alter the simulation"; ``tests/test_harness_golden.py`` runs ``--check`` in a subprocess.

Exact hashes are bit-for-bit and only meaningful on the same torch/numpy build; the summary comparison uses a stated
tolerance (``TOLERANCE``) and is what the test enforces by default (set ``EDEN_GOLDEN_STRICT=1`` to also require the exact
hashes).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

DEFAULT_SEED = 1008
DEFAULT_TICKS = 3600
CHECKPOINTS = (0, 1, 20, 100, 300, 600, 1200, 1800, 2400, 3000, 3600)
TOLERANCE = 1e-3
GOLDEN_DIR = ROOT / "tests" / "golden"
SCHEMA = 1


def golden_path(seed: int, resources: bool = False, spaces: bool = False) -> Path:
    return GOLDEN_DIR / f"trace_seed{seed}{'_resources' if resources else ''}{'_spaces' if spaces else ''}.json"


def _sha(tensor) -> str:
    return hashlib.sha256(tensor.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def snapshot(engine, cfg, state) -> dict:
    """Checksums and a tolerance-comparable summary of the world at the current tick."""
    h, m = engine.state.h_tensor, engine.state.m_tensor
    live_h = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()
    residents = {}
    for slot in live_h:
        uid = engine._human_uid_by_slot[slot]
        record = engine.resident_store.get(uid) if uid else None
        name = record["profile"]["name"] if record else f"slot{slot}"
        row = h[slot]
        residents[name] = {
            "slot": slot, "x": round(float(row[cfg.X]), 4), "y": round(float(row[cfg.Y]), 4), "hp": round(float(row[cfg.HP]), 3),
            "hunger": round(float(row[cfg.HUNGER]), 3), "thirst": round(float(row[cfg.THIRST]), 3),
            "stamina": round(float(row[cfg.H_STAMINA]), 3), "mood": round(float(row[cfg.MOOD]), 3),
            "goal": state.goal_key.get(uid) if state is not None else None,
            "at_anchor": state.at_anchor.get(uid) if state is not None else None}
    live_m = m[:, cfg.M_TYPE] > 0
    types = {}
    for value in m[live_m, cfg.M_TYPE].tolist():
        types[str(int(value))] = types.get(str(int(value)), 0) + 1
    return {
        "tick": engine.tick,
        "h_sha256": _sha(h), "m_sha256": _sha(m),
        "humans": len(live_h), "entities": int(live_m.sum()), "entity_types": types,
        "m_sums": {"cx": round(float(m[live_m, cfg.CX].sum()), 3), "cy": round(float(m[live_m, cfg.CY].sum()), 3),
                   "hp": round(float(m[live_m, cfg.M_HP].sum()), 3), "food": round(float(m[live_m, cfg.M_RESOURCE_FOOD].sum()), 3),
                   "water": round(float(m[live_m, cfg.M_RESOURCE_WATER].sum()), 3)},
        "residents": residents,
    }


class _NullService:
    """A ChunkService that never produces a chunk: the window hook runs (plan, re-base check, contract publish) over the finite world."""
    world_seed = 1008
    def apply_plan(self, plan): pass
    def pump(self): pass
    def peek(self, coord): return None
    def stats(self): return {}
    def close(self): pass


def _finite_window() -> None:
    """1008 5.7 item 6: ``EDEN_WINDOW=1`` with the window equal to the whole legacy frame and no chunk source. Nothing may change."""
    import genesis_config
    import map_geo
    from harness import window, window_manager
    map_geo.configure_window(genesis_config.GRID_W, genesis_config.GRID_H, (0, 0), sparse=True)   # the hook then leaves the frame alone
    window_manager.REBASE_AT = 10 ** 9                       # the legacy frame is wider than two chunks: never shift it
    window_manager.shared_service = _NullService
    window.REBASE_AT = 10 ** 9
    # The window loader seats interiors in the pocket pool; a finite window keeps them where the legacy EDEN_MAP_ORIGINS puts them
    # (pocket k = the k-th origin, in load order), so the trace is comparable with the non-window run.
    from harness import headless
    window.POCKET_ORIGINS = [tuple(float(v) for v in origin) for origin in headless.MAP_ORIGINS.values()]
    window.authored_pocket = lambda index: index
    window.POCKET_UNITS = 10.0 ** 9


async def run_trace(seed: int, ticks: int, unscaled: bool = False, sparse_geo: bool = False, window_hook: bool = False) -> dict:
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    if window_hook:
        _finite_window()
    if sparse_geo:       # 1008 P4: the legacy full frame with sparse bounding-box masks must reproduce the default golden bit for bit
        import genesis_config
        import map_geo
        map_geo.configure_window(genesis_config.GRID_W, genesis_config.GRID_H, (0, 0), sparse=True)
    if unscaled:         # starter_village residents have needs_scale 0.015: drop it so the hunger/thirst drain (S3) is exercised in full
        from systems.roster import driver
        driver.needs_scale_vector = lambda engine, h_tensor: None
    backend, engine = await boot_engine(seed)
    import genesis_config as cfg
    from systems.roster.driver import runtime
    state = runtime(engine)
    checkpoints = sorted({c for c in CHECKPOINTS if c <= ticks} | {ticks})
    trace, started = [], time.perf_counter()
    for tick in range(ticks + 1):
        if tick in checkpoints:
            trace.append(snapshot(engine, cfg, state))
        if tick < ticks:
            engine.step()
    if window_hook:      # the point of the run: the hook really ticked every step, integrated nothing, and never shifted the origin
        manager = getattr(engine, "_window", None)
        if manager is None or len(manager.step_ms) != ticks or manager.counters["integrated"] or manager.epoch:
            raise SystemExit(f"--window-hook: the window manager did not run as a finite no-op: {None if manager is None else manager.stats()}")
    import platform
    import torch
    return {"schema": SCHEMA, "seed": seed, "ticks": ticks, "checkpoints": trace,
            "meta": {"torch": torch.__version__, "python": platform.python_version(), "platform": platform.platform(),
                     "wall_seconds": round(time.perf_counter() - started, 1)}}


def _close(a, b, path, problems):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                problems.append(f"{path}.{key}: present in only one side")
            else:
                _close(a[key], b[key], f"{path}.{key}", problems)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if abs(a - b) > TOLERANCE:
            problems.append(f"{path}: {a} vs {b}")
    elif a != b:
        problems.append(f"{path}: {a!r} vs {b!r}")


def compare(golden: dict, fresh: dict, strict: bool = False) -> list[str]:
    """Differences beyond tolerance (and, when ``strict``, any exact-hash difference). Empty list means no drift."""
    problems: list[str] = []
    if golden["seed"] != fresh["seed"] or golden["ticks"] != fresh["ticks"]:
        return [f"different run parameters: golden seed/ticks {golden['seed']}/{golden['ticks']} vs {fresh['seed']}/{fresh['ticks']}"]
    for old, new in zip(golden["checkpoints"], fresh["checkpoints"], strict=True):
        tick = old["tick"]
        summary_old = {k: v for k, v in old.items() if not k.endswith("_sha256")}
        summary_new = {k: v for k, v in new.items() if not k.endswith("_sha256")}
        _close(summary_old, summary_new, f"tick{tick}", problems)
        if strict:
            for key in ("h_sha256", "m_sha256"):
                if old[key] != new[key]:
                    problems.append(f"tick{tick}.{key}: exact hash differs")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="write the golden file for this seed")
    mode.add_argument("--check", action="store_true", help="compare a fresh run with the golden file (exit 1 on drift)")
    parser.add_argument("--strict", action="store_true", help="with --check, also require identical exact hashes")
    parser.add_argument("--out", type=Path, help="write the fresh trace here")
    parser.add_argument("--resources", action="store_true", help="run with EDEN_MAP_RESOURCES=1 (G-005) and use trace_seed<N>_resources.json")
    parser.add_argument("--spaces", action="store_true",
                        help="run with EDEN_SPACES=1 and EDEN_PERCEPTION_BOUNDED=1 (1008 P3, interiors as spaces) and use trace_seed<N>_spaces.json")
    parser.add_argument("--sparse-geo", action="store_true",
                        help="run with map_geo sparse masks on the full legacy frame (1008 P4); compares against the same golden file as without it")
    parser.add_argument("--window-hook", action="store_true",
                        help="run with EDEN_WINDOW=1 over the finite world (window = the whole frame, no chunks; implies --resources --spaces); "
                             "compares against trace_seed<N>_resources_spaces.json, which a plain --resources --spaces run records")
    parser.add_argument("--unscaled", action="store_true", help="run with roster needs scaling removed (not comparable to the golden file)")
    args = parser.parse_args()
    import os
    if args.window_hook:
        args.resources = args.spaces = True
        os.environ["EDEN_WINDOW"] = "1"
    if args.resources:
        os.environ["EDEN_MAP_RESOURCES"] = "1"
    if args.spaces:
        os.environ["EDEN_SPACES"] = "1"
        os.environ["EDEN_PERCEPTION_BOUNDED"] = "1"
    fresh = asyncio.run(run_trace(args.seed, args.ticks, unscaled=args.unscaled, sparse_geo=args.sparse_geo, window_hook=args.window_hook))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(fresh, indent=1, sort_keys=True), encoding="utf-8")
    if args.record:
        if args.window_hook:
            parser.error("--record writes a reference: record with --resources --spaces, check with --window-hook")
        path = golden_path(args.seed, args.resources, args.spaces)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fresh, indent=1, sort_keys=True), encoding="utf-8")
        print(f"recorded {path} ({len(fresh['checkpoints'])} checkpoints, {fresh['meta']['wall_seconds']} s)")
    if args.check:
        golden = json.loads(golden_path(args.seed, args.resources, args.spaces).read_text(encoding="utf-8"))
        problems = compare(golden, fresh, strict=args.strict)
        if problems:
            print(f"DRIFT: {len(problems)} difference(s) from {golden_path(args.seed, args.resources, args.spaces)}")
            for line in problems[:40]:
                print("  " + line)
            return 1
        print(f"no drift ({len(fresh['checkpoints'])} checkpoints, {fresh['meta']['wall_seconds']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
