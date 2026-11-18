"""Per-system tick profile of the legacy engine on the seeded headless starter village (WS-H P0).

    .venv/Scripts/python.exe tools/profile_tick.py [--ticks 108000] [--seed 1008] [--md 1008_tick_profile.md]
                                                    [--json .runtime/tick-profile.json] [--no-instrument]

108000 ticks = 90 game minutes at 20 Hz (the tick budget is 50 ms). "Systems" are every ``Engine._registry`` entry (the
``default_registry_entries`` functions) plus the non-registry parts of ``Engine.step`` (command drain, world-agent queues,
talk and escalation agents, the slide reconcile loop, step/post-step hooks, id/event sync, payload builds). Each part is
wrapped with a perf_counter timer; the wall time of the whole ``step()`` is measured separately and the difference is
reported as "residual (unattributed)". Probes (``world_contract``, ``spatial_slide``) are nested timers attributed to the
part that called them. Resident files are written by a background pool between ticks, as the gameplay server does, and that
work is not part of the tick figures. ``--no-instrument`` times only the whole step (to measure the timers' own overhead).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))


def percentile(values, p):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(round(len(ordered) * p / 100.0 + 0.5)) - 1))] if ordered else 0.0


class Profiler:
    def __init__(self):
        self.cur: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.active: str | None = None
        self.series: dict[str, list[float]] = defaultdict(list)
        self.names: list[str] = []
        self.probe_cur: dict[str, float] = defaultdict(float)
        self.probe_series: dict[str, list[float]] = defaultdict(list)
        self.probe_calls: dict[str, int] = defaultdict(int)
        self.ticks = 0

    def part(self, name, fn):
        """Wrap a top-level part of the tick."""
        if name not in self.names:
            self.names.append(name)

        def wrapped(*args, **kwargs):
            previous, self.active = self.active, name
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.cur[name] += time.perf_counter() - started
                self.calls[name] += 1
                self.active = previous
        wrapped.__name__ = getattr(fn, "__name__", name)
        wrapped.__wrapped__ = fn
        return wrapped

    def probe(self, name, fn):
        """Wrap a nested function; time is attributed to ``name@<calling part>``."""
        def wrapped(*args, **kwargs):
            key = f"{name}@{self.active or 'step (direct)'}"
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.probe_cur[key] += time.perf_counter() - started
                self.probe_calls[key] += 1
        wrapped.__name__ = getattr(fn, "__name__", name)
        wrapped.__wrapped__ = fn
        return wrapped

    def end_tick(self):
        for name in self.names:
            self.series[name].append(self.cur.get(name, 0.0) * 1000.0)
        for key in set(self.probe_series) | set(self.probe_cur):
            column = self.probe_series[key]
            if len(column) < self.ticks:
                column.extend([0.0] * (self.ticks - len(column)))
            column.append(self.probe_cur.get(key, 0.0) * 1000.0)
        self.cur.clear()
        self.probe_cur.clear()
        self.ticks += 1


def instrument(engine, backend, prof: Profiler):
    """Wrap registry entries and the non-registry parts of Engine.step. Returns the list of top-level part names."""
    from simulation.dispatch import DISPATCH
    for entry in engine._registry:
        entry["fn"] = prof.part(f"registry:{entry['priority']:g} {entry['fn'].__name__}", entry["fn"])
    DISPATCH.step_hooks[:] = [(n, prof.part(f"hook(step):{n}", fn)) for n, fn in DISPATCH.step_hooks]
    DISPATCH.post_step_hooks[:] = [(n, prof.part(f"hook(post_step):{n}", fn)) for n, fn in DISPATCH.post_step_hooks]
    patches = [
        (engine.player_control, "tick_maintenance", "step: player_control.tick_maintenance"),
        (engine.player_control, "begin_tick_inputs", "step: player_control.begin_tick_inputs"),
        (engine.command_inbox, "drain", "step: command_inbox.drain"),
        (engine, "_build_kwargs", "step: _build_kwargs"),
        (engine.world_agent, "process_queues", "step: world_agent.process_queues"),
        (engine, "_current_masks", "step: _current_masks"),
        (engine.talk_agent, "process_tick", "step: talk_agent.process_tick"),
        (engine.human_agent, "process_escalations", "step: human_agent.process_escalations"),
        (engine.player_control, "build_tick_context", "step: player_control.build_tick_context"),
        (engine, "_apply_manual_control_human_actions", "step: _apply_manual_control_human_actions"),
        (engine, "_sync_slot_ids_and_events", "step: _sync_slot_ids_and_events"),
        (engine, "_refresh_actor_render_hints", "step: _refresh_actor_render_hints"),
        (engine.player_control, "commit_tick_inputs", "step: player_control.commit_tick_inputs"),
        (engine, "_build_frame_payload", "step: _build_frame_payload"),
        (engine, "_build_map_delta_payload", "step: _build_map_delta_payload"),
    ]
    for owner, attr, label in patches:
        setattr(owner, attr, prof.part(label, getattr(owner, attr)))
    # Names imported into map_test's namespace: patch the module attribute (nested probes, attributed to the caller).
    backend.world_contract = prof.probe("world_contract", backend.world_contract)
    backend.spatial_slide = prof.probe("spatial_slide", backend.spatial_slide)
    import systems.movement.spatial as spatial
    spatial.wall_boxes = prof.probe("wall_boxes", spatial.wall_boxes)  # called through module globals by _compose
    import json as _json
    spatial.json = type("J", (), {"dumps": staticmethod(prof.probe("sha_json_dumps", _json.dumps)), "loads": staticmethod(_json.loads)})
    return list(prof.names)


async def run(args):
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    backend, engine = await boot_engine(args.seed)
    import torch
    prof = Profiler()
    if not args.no_instrument:
        instrument(engine, backend, prof)
    engine.resident_store.background_writes = True  # exactly what the gameplay server's lifespan does
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-resident-writer")
    from runtime.resident_store import write_resident_batch
    futures, totals, started = [], [], time.perf_counter()
    for _ in range(args.ticks):
        t0 = time.perf_counter()
        engine.step()
        totals.append((time.perf_counter() - t0) * 1000.0)
        if not args.no_instrument:
            prof.end_tick()
        if engine.tick % 20 == 10:  # ResidentWriter.flush_once, once per game second, outside the tick figures
            for future in [f for f in futures if f.done()]:
                futures.remove(future)
                engine.resident_store.acknowledge_writes(future.result())
            jobs = engine.resident_store.capture_dirty(engine.tick, force=True, limit=16)
            if jobs:
                futures.append(pool.submit(write_resident_batch, jobs))
        if engine.tick % 6000 == 0:
            print(f"tick {engine.tick} p50 {percentile(totals, 50):.2f} ms p99 {percentile(totals, 99):.2f} ms elapsed {time.perf_counter() - started:.0f} s", flush=True)
    pool.shutdown(wait=True)
    return prof, totals, {"torch": torch.__version__, "python": platform.python_version(), "platform": platform.platform(),
                          "device": engine.state.device, "residents": int((engine.state.h_tensor[:, 2] == 1).sum()),
                          "entities": int((engine.state.m_tensor[:, 2] > 0).sum()), "wall_seconds": round(time.perf_counter() - started, 1)}


def stats(values):
    return {"mean": statistics.fmean(values), "p50": percentile(values, 50), "p95": percentile(values, 95),
            "p99": percentile(values, 99), "max": max(values)}


def build_report(args, prof: Profiler, totals, meta):
    total_stats = stats(totals)
    rows = []
    for name in prof.names:
        series = prof.series[name]
        if not series:
            continue
        s = stats(series)
        nonzero = [v for v in series if v > 0]
        rows.append({"name": name, **s, "share_of_mean_pct": 100.0 * s["mean"] / total_stats["mean"] if total_stats["mean"] else 0.0,
                     "calls_per_tick": prof.calls[name] / max(1, len(series)),
                     "mean_when_called": statistics.fmean(nonzero) if nonzero else 0.0})
    attributed = [sum(prof.series[n][i] for n in prof.names if prof.series[n]) for i in range(len(totals))] if prof.names else []
    residual = [max(0.0, t - a) for t, a in zip(totals, attributed)] if attributed else []
    probes = []
    for key, series in prof.probe_series.items():
        series.extend([0.0] * (len(totals) - len(series)))
        s = stats(series)
        probes.append({"name": key, **s, "calls_per_tick": prof.probe_calls[key] / max(1, len(totals))})
    probes.sort(key=lambda r: -r["mean"])
    return {"args": {"ticks": args.ticks, "seed": args.seed, "instrumented": not args.no_instrument}, "meta": meta, "total": total_stats,
            "overruns": {"over_25ms": sum(v > 25 for v in totals), "over_50ms": sum(v > 50 for v in totals)},
            "parts": sorted(rows, key=lambda r: -r["mean"]), "residual": stats(residual) if residual else None, "probes": probes}


def fmt(v):
    return f"{v:.3f}"


def markdown(report) -> str:
    t, meta, a = report["total"], report["meta"], report["args"]
    out = ["# 1008 tick profile: per-system wall time of the legacy engine", "",
           f"Generated by `tools/profile_tick.py` (seed {a['seed']}, {a['ticks']} ticks = {a['ticks'] / 1200:.1f} game minutes at 20 Hz; tick budget 50 ms). "
           f"{'Instrumented with perf_counter timers on every part.' if a['instrumented'] else 'NOT instrumented: whole-step time only.'} "
           f"World: authored starter village + 3 interiors, {meta['residents']} residents, {meta['entities']} entities at the end, device `{meta['device']}`, "
           f"torch {meta['torch']}, Python {meta['python']}, {meta['platform']}. Run took {meta['wall_seconds']} s of wall time. "
           "No player, no models, no network: this is the Stage 1 rules-only simulation on its own. All times in milliseconds per tick.", "",
           "## Whole tick", "", "| mean | p50 | p95 | p99 | max | ticks > 25 ms | ticks > 50 ms |", "| --- | --- | --- | --- | --- | --- | --- |",
           f"| {fmt(t['mean'])} | {fmt(t['p50'])} | {fmt(t['p95'])} | {fmt(t['p99'])} | {fmt(t['max'])} | {report['overruns']['over_25ms']} | {report['overruns']['over_50ms']} |", ""]
    if report["parts"]:
        out += ["## Parts of the tick, sorted by mean cost", "",
                "Per-tick cost including ticks where the part did not run (so p50 of a part that runs rarely is 0). `share` = share of the mean tick. `when called` = mean over ticks where it ran.", "",
                "| part | mean | p50 | p95 | p99 | max | share | calls/tick | when called |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in report["parts"]:
            out.append(f"| `{r['name']}` | {fmt(r['mean'])} | {fmt(r['p50'])} | {fmt(r['p95'])} | {fmt(r['p99'])} | {fmt(r['max'])} | {r['share_of_mean_pct']:.1f}% | {r['calls_per_tick']:.2f} | {fmt(r['mean_when_called'])} |")
        res = report["residual"]
        out.append(f"| *residual (unattributed: slide reconcile loop, copies, glue)* | {fmt(res['mean'])} | {fmt(res['p50'])} | {fmt(res['p95'])} | {fmt(res['p99'])} | {fmt(res['max'])} | {100 * res['mean'] / t['mean']:.1f}% | | |")
        out += ["", "### Top offenders", ""]
        for title, key in (("by mean", "mean"), ("by p99", "p99"), ("by max", "max")):
            top = sorted(report["parts"], key=lambda r: -r[key])[:5]
            out.append(f"- **{title}:** " + "; ".join(f"`{r['name']}` {fmt(r[key])} ms" for r in top))
        out += ["", "## Nested probes (time is included in the part that called them)", "",
                "| probe @ calling part | mean | p50 | p99 | max | calls/tick |", "| --- | --- | --- | --- | --- | --- |"]
        for r in report["probes"][:20]:
            out.append(f"| `{r['name']}` | {fmt(r['mean'])} | {fmt(r['p50'])} | {fmt(r['p99'])} | {fmt(r['max'])} | {r['calls_per_tick']:.2f} |")
        out += ["", "`sha_json_dumps` is the `json.dumps` inside `spatial.world_contract` that feeds the wall-box revision hash.", ""]
    out += ["## What this is not", "",
            "- Eight residents on the Stage 1 maps only; it says nothing yet about 100 residents, chunk streaming, or models.",
            "- Wall-clock times on one Windows machine with CPU torch; absolute numbers will differ elsewhere, ratios between parts should hold.",
            "- Timers add their own cost (see the `--no-instrument` comparison in the notes below if present).", ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=108000)
    parser.add_argument("--seed", type=int, default=1008)
    parser.add_argument("--json", type=Path, default=ROOT / ".runtime" / "tick-profile.json")
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--no-instrument", action="store_true")
    args = parser.parse_args()
    prof, totals, meta = asyncio.run(run(args))
    report = build_report(args, prof, totals, meta)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    text = markdown(report)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
