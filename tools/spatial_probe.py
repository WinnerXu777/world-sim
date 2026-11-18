"""Window engine (real chunks, workers=0) + N extra humans; per-part profile. usage: spatial_probe.py N TICKS [window|legacy]"""
import asyncio, os, sys, time, statistics, random
ROOT = os.environ.get("PROBE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # PROBE_ROOT: another checkout (e.g. a git archive of an older commit)
sys.path.insert(0, ROOT + r"\tools"); sys.path.insert(0, ROOT + r"\at_the_beginning")
n, ticks = int(sys.argv[1]), int(sys.argv[2])
mode = sys.argv[3] if len(sys.argv) > 3 else "window"          # window | roster (window + roster-bound extra residents, EDEN_ROSTER_DRIVER = argv[4]: anchor | agent)
if mode == "roster":
    os.environ["EDEN_ROSTER_DRIVER"] = sys.argv[4] if len(sys.argv) > 4 else "anchor"
if mode in ("window", "roster"):
    os.environ.update(EDEN_WINDOW="1", EDEN_SPACES="1", EDEN_PERCEPTION_BOUNDED="1", EDEN_MAP_RESOURCES="1", EDEN_CHUNK_WORKERS="0")
import profile_tick as pt

async def main():
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    backend, engine = await boot_engine(1008)
    import genesis_config as cfg, torch
    h = engine.state.h_tensor
    live = int((h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN).sum())
    rng = random.Random(7)
    free = torch.where(h[:, cfg.TYPE] == 0)[0].tolist()
    base = [(float(h[i, cfg.X]), float(h[i, cfg.Y])) for i in range(h.shape[0]) if float(h[i, cfg.TYPE]) == 1.0]
    cx = sum(p[0] for p in base) / len(base); cy = sum(p[1] for p in base) / len(base)
    if mode == "roster":          # extra residents bound to the real roster anchors (work / talk / sleep), not legacy-managed clones
        import dataclasses
        from systems.roster.apply import apply_roster, roster_for_map
        base = roster_for_map("starter_village")
        extras, k = [], 0
        while live + len(extras) < n:
            template = base.residents[k % len(base.residents)]
            extras.append(dataclasses.replace(template, key=f"{template.key}_x{k}", name=f"{template.name}{k}", sex=(template.sex + k // len(base.residents)) % 2))
            k += 1
        for i in range(0, len(extras), 8):          # a spawn anchor has 13 ring places: seat eight at a time
            apply_roster(engine, "starter_village", dataclasses.replace(base, residents=tuple(extras[i:i + 8])))
        free = []
    for slot in free[:max(0, n - live)]:
        h[slot, :] = h[0, :]
        h[slot, cfg.X] = cx + rng.uniform(-220, 220); h[slot, cfg.Y] = cy + rng.uniform(-220, 220)
        engine._human_uid_by_slot[slot] = None
    for _ in range(40): engine.step()          # let the ring integrate
    if os.environ.get('MICRO'):
        import math
        from genesis_config import X, Y, TYPE, HP, THREAT, H_SEX, H_AGE, H_COOLDOWN, HUNGER, THIRST, H_STAMINA, AGENT_TYPE_HUMAN
        ht = engine.state.h_tensor
        slots = torch.where(ht[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist()
        t0 = time.perf_counter(); old = [engine._resolve_nearby_help_target(sl) for sl in slots]; t_old = (time.perf_counter() - t0) * 1000
        def fast_help(sl, radius=72.0):
            a = ht[:, [X, Y, HP, THREAT]].numpy() if False else None
        # snapshot once per tick, query per resident
        t0 = time.perf_counter()
        snap = ht[slots][:, [X, Y, HP, THREAT]].double().numpy()
        import numpy as np
        t_snap = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); new = []
        for i, sl in enumerate(slots):
            d = np.hypot(snap[:, 0] - snap[i, 0], snap[:, 1] - snap[i, 1])
            ok = (d <= 72.0) & ~((snap[:, 2] >= 78.0) & (snap[:, 3] < 42.0)); ok[i] = False
            idx = np.nonzero(ok)[0]
            if not len(idx): new.append(None); continue
            best = min(idx, key=lambda j: (snap[j, 2], d[j]))
            new.append(slots[best])
        t_new = (time.perf_counter() - t0) * 1000
        agree = sum(1 for o, nw in zip(old, new) if (o is None and nw is None) or (o is not None and nw == o['slot']))
        print(f"help target x{len(slots)}: old {t_old:.1f} ms total ({t_old/len(slots):.3f}/call), vectorised {t_new + t_snap:.2f} ms total (snapshot {t_snap:.2f}); agree {agree}/{len(slots)}")
        ids = len(__import__('map_geo').MAP_GEO)
        import map_geo
        t0 = time.perf_counter()
        for sl in slots: map_geo.entities_in_radius(float(ht[sl, X]), float(ht[sl, Y]), 72.0, engine.state.m_tensor)
        t_er = (time.perf_counter() - t0) * 1000
        print(f"entities_in_radius x{len(slots)} ({ids} geo entities): {t_er:.1f} ms ({t_er/len(slots):.3f}/call)")
        t0 = time.perf_counter(); 
        for _ in range(61): engine._current_masks()
        print(f"_current_masks x61: {(time.perf_counter()-t0)*1000:.1f} ms")
        t0 = time.perf_counter(); r = [engine._resolve_mate_candidate(sl) for sl in slots]; print(f"mate candidates x{len(slots)}: {(time.perf_counter()-t0)*1000:.1f} ms")
        return
    import cProfile, pstats
    if os.environ.get('CPROF'):
        pr=cProfile.Profile(); pr.enable()
        for _ in range(ticks): engine.step()
        pr.disable(); st=pstats.Stats(pr)
        if os.environ.get('CUM'):
            pstats.Stats(pr).sort_stats('cumulative').print_stats(45); return
        want=['_sync_occupation_provisioning','_sync_managed_resident_tasks','_resolve_mate_candidate','_slot_ready_for_mating','_resolve_nearby_help_target','entities_in_radius','nearby_entity_ids','ensure_resident','_nearest_structure_slot','plan_path','process_escalations','_current_masks','spatial_slide','world_contract']
        out={}
        for (f,l,name),(cc,nc,tt,ct,callers) in st.stats.items():
            if name in want: out[name]=(nc,tt/ticks*1000,ct/ticks*1000)
        tot=sum(v[2] for k,v in out.items() if k=='_sync_occupation_provisioning')
        print('N',n,'  name: calls/tick, self ms/tick, cum ms/tick')
        for k in want:
            if k in out: print(f'  {k:34s} {out[k][0]/ticks:9.1f} {out[k][1]:8.2f} {out[k][2]:8.2f}')
        st.sort_stats('tottime').print_stats(8); return
    prof = pt.Profiler(); pt.instrument(engine, backend, prof)
    engine.resident_store.background_writes = True      # as the server's lifespan does: the resident files are written by a pool between ticks, not inside the tick
    totals = []
    for _ in range(ticks):
        t0 = time.perf_counter(); engine.step(); totals.append((time.perf_counter() - t0) * 1000); prof.end_tick()
    mgr = getattr(engine, "_window", None)
    print(f"mode={mode} humans={int((h[:, cfg.TYPE] == 1).sum())} entities={int((engine.state.m_tensor[:, cfg.M_TYPE] > 0).sum())} chunks={len(mgr.chunks) if mgr else '-'}")
    print(f"tick mean {statistics.fmean(totals):.2f} p50 {pt.percentile(totals,50):.2f} p99 {pt.percentile(totals,99):.2f} max {max(totals):.2f}")
    rows = sorted(((statistics.fmean(s), k) for k, s in prof.series.items() if s), reverse=True)[:14]
    for m, k in rows: print(f"  {m:7.3f} ms  {k}")
    tail = sorted(((pt.percentile(sr, 99), k) for k, sr in prof.series.items() if sr), reverse=True)[:4]
    print("  p99 by part: " + "; ".join(f"{k} {v:.1f}" for v, k in tail))
    pr = sorted(((statistics.fmean(s + [0.0] * (len(totals) - len(s))), k, prof.probe_calls[k] / len(totals)) for k, s in prof.probe_series.items()), reverse=True)[:6]
    for m, k, c in pr: print(f"  probe {m:7.3f} ms  {k}  ({c:.1f}/tick)")
asyncio.run(main())
