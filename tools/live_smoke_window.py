"""End-to-end smoke of the streaming window over real HTTP (1008 queue item 3): a real backend process with the four flags
``EDEN_WINDOW EDEN_SPACES EDEN_PERCEPTION_BOUNDED EDEN_MAP_RESOURCES`` plus ``EDEN_CHUNK_ROUTES``.

    .venv/Scripts/python.exe tools/live_smoke_window.py [--port 8021] [--keep]
    .venv/Scripts/python.exe tools/live_smoke_window.py --port 8031 --long-distance 5000 [--walk-seconds 1800] [--evidence out.json]   (R0.5, Gate D)

It starts the backend itself in a fresh isolated data root (never a world you want to keep), then checks over HTTP:
  * ``/bootstrap``: the ``world`` infinite block, ``window_origin`` / ``window_epoch``, ``maps[]`` and ``spaces[]`` rows with ``window_shift``;
  * ``/frame`` and ``/map_delta`` stamps, and that chunk features (ids ``c<cx>_<cy>:...``) arrive as map entities once the window integrated;
  * ``/chunks`` and ``/chunk/{cx}/{cy}``: states, ETag == sha256 of the body, 304 on If-None-Match, identical bytes on a repeat, errors;
  * the 409 path: a request naming another ``window_epoch`` is answered 409 ``stale_window_epoch`` with the current origin and epoch;
  * save and restore: ``/session/save`` then ``/session/continue`` in the same process, then again after the backend process is killed
    and started anew on the same data root (the window origin, epoch, world seed and chunk entity ids must come back equal);
  * the refusal: a backend started WITHOUT the window flags refuses to continue that save (the approved format 3 text), unchanged on disk.
Exit code 0 only when every check passes.
"""
import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MAPS = ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")
ORIGINS = {"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}
FLAGS = {"EDEN_WINDOW": "1", "EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1", "EDEN_MAP_RESOURCES": "1", "EDEN_CHUNK_ROUTES": "1"}
WINDOW_KEYS = {"window_origin", "window_epoch"}
REFUSAL_START = "This save was made with the streaming world (world format 3, EDEN_WINDOW=1), but this session runs without it"

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)
    return bool(ok)


class Backend:
    def __init__(self, port, data_root, flags, shim=False):
        self.port, self.data_root, self.flags = port, data_root, flags
        # shim (the --long-distance walk only): map_test's own app plus the read-only SHIM_ROUTE, see serve_backend()
        self.command = ([sys.executable, str(Path(__file__).resolve()), "--serve-backend"] if shim
                        else [sys.executable, str(ROOT / "at_the_beginning" / "map_test.py")])
        self.proc = None
        self.client = None
        self.session = None

    def start(self, timeout=240.0):
        env = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_")}
        env.update(EDEN_PROFILE="gameplay", EDEN_PORT=str(self.port), EDEN_DATA_ROOT=str(self.data_root), EDEN_MAP="starter_village",
                   EDEN_EMBEDDINGS="lexical", EDEN_CHUNK_WORKERS="1",
                   EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{n}.json") for n in MAPS),
                   EDEN_MAP_ORIGINS=json.dumps(ORIGINS), **self.flags)
        log = open(self.data_root / f"backend-{self.port}-{int(time.time())}.log", "wb")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0       # so CTRL_BREAK reaches this backend alone
        self.proc = subprocess.Popen(self.command, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=flags)
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=60)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"backend exited with {self.proc.returncode}; see {log.name}")
            try:
                self.session = {"X-Eden-Session": self.client.get("/bootstrap").json()["session_capability"]}
                return
            except (httpx.HTTPError, ValueError, KeyError):
                time.sleep(1.0)
        raise RuntimeError("backend did not answer /bootstrap in time")

    def stop(self):
        if self.client is not None:
            self.client.close()
        if self.proc is not None and self.proc.poll() is None:
            # the chunk pool's spawn workers are children: a plain terminate() leaves them orphaned on Windows, so take the tree down
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = self.client = None

    def descendants(self):
        """Pids of every process below the backend (the chunk pool's spawn workers)."""
        if os.name == "nt":
            script = (f"$all=Get-CimInstance Win32_Process;$q=@({self.proc.pid});$out=@();while($q.Count){{$p=$q[0];$q=$q[1..$q.Count];"
                      f"foreach($c in $all|Where-Object{{$_.ParentProcessId -eq $p}}){{$out+=$c.ProcessId;$q+=$c.ProcessId}}}};$out -join ','")
            text = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout.strip()
        else:
            text = subprocess.run(["pgrep", "-P", str(self.proc.pid)], capture_output=True, text=True).stdout.replace(chr(10), ",").strip(",")
        return [int(v) for v in text.split(",") if v.strip().isdigit()]

    def stop_gracefully(self, timeout=90.0):
        """A normal stop (CTRL_BREAK / SIGINT, the uvicorn path): returns (main exited, pids still alive after the main exited)."""
        kids = self.descendants()
        os.kill(self.proc.pid, signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        try:
            self.proc.wait(timeout=timeout)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        deadline = time.time() + 20.0
        alive = kids
        while alive and time.time() < deadline:
            time.sleep(1.0)
            alive = [pid for pid in kids if pid_alive(pid)]
        return exited, kids, alive

    def get(self, path, **kw):
        return self.client.get(path, **kw)

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.session)


def pid_alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def chunk_features(delta):
    return sorted(e["id"] for e in delta.get("upserts", []) if str(e.get("id", "")).startswith("c") and ":" in str(e.get("id", "")))


def wait_for_integration(b, seconds=60.0, want=20):
    """Poll the full map delta until chunk features are in, or the time is up. Returns the last full delta."""
    deadline, delta = time.time() + seconds, {}
    while time.time() < deadline:
        delta = b.get("/map_delta").json()
        if len(chunk_features(delta)) >= want:
            time.sleep(3.0)                                   # let the ring fill, then take a final look
            return b.get("/map_delta").json()
        time.sleep(1.0)
    return delta


def window_facts(b):
    boot = b.get("/bootstrap").json()
    delta = b.get("/map_delta").json()
    return {"world": {k: boot["world"].get(k) for k in ("infinite", "world_seed", "generator_version", "chunk_tiles", "units_per_tile")},
            "origin": boot["world"].get("window_origin"), "epoch": boot["world"].get("window_epoch"),
            "features": chunk_features(delta)}


def phase_one(b, out):
    boot = b.get("/bootstrap").json()
    world = boot.get("world", {})
    check("bootstrap.world is the infinite block", world.get("infinite") is True and world.get("chunk_tiles") == 32 and world.get("units_per_tile") == 8
          and isinstance(world.get("world_seed"), str) and isinstance(world.get("generator_version"), str), str(world))
    origin, epoch = world.get("window_origin"), world.get("window_epoch")
    check("bootstrap carries window_origin [int, int] and window_epoch int", isinstance(origin, list) and len(origin) == 2
          and all(isinstance(v, int) for v in origin) and isinstance(epoch, int), f"{origin} {epoch}")
    check("maps[] rows carry window_shift", bool(boot.get("maps")) and all(isinstance(m.get("window_shift"), list) and len(m["window_shift"]) == 2 for m in boot["maps"]),
          str([m.get("window_shift") for m in boot.get("maps", [])]))
    check("spaces[] rows carry window_shift", bool(boot.get("spaces")) and all(isinstance(s.get("window_shift"), list) for s in boot["spaces"]),
          str(len(boot.get("spaces", []))))
    frame = b.get("/frame").json()
    check("/frame is stamped with the window origin and epoch", WINDOW_KEYS <= set(frame) and frame["window_origin"] == origin and frame["window_epoch"] == epoch,
          str({k: frame.get(k) for k in WINDOW_KEYS}))
    t0 = frame.get("tick")
    time.sleep(3.0)
    check("the tick loop is running", b.get("/frame").json().get("tick", 0) > (t0 or 0))
    delta = wait_for_integration(b)
    features = chunk_features(delta)
    check("full /map_delta is stamped and replaces all", WINDOW_KEYS <= set(delta) and delta.get("replace_all") is True, str(sorted(delta)[:12]))
    check("chunk features arrive as map entities after integration", len(features) >= 1, f"{len(features)} features")
    check("no chunk feature id repeats", len(features) == len(set(features)))
    since = {"since_state_version": delta["state_version"], "since_geo_version": delta["geo_version"]}
    again = b.get("/map_delta", params=since).json()
    check("an incremental /map_delta keeps the stamp", WINDOW_KEYS <= set(again), str(sorted(again)[:10]))

    # chunk routes -----------------------------------------------------------------------------------------------------
    listing = {}
    for _ in range(40):
        listing = b.get("/chunks", params=dict(cx0=0, cy0=0, cx1=1, cy1=1)).json()
        if all(c.get("state") != "pending" for c in listing.get("chunks", [])):
            break
        time.sleep(0.5)
    chunks = listing.get("chunks", [])
    check("/chunks lists the rectangle in row order", [c["chunk_id"] for c in chunks] == ["0:0", "1:0", "0:1", "1:1"], str([c.get("chunk_id") for c in chunks]))
    check("/chunks world_seed is a string and agrees with bootstrap", listing.get("world_seed") == world.get("world_seed") and isinstance(listing.get("world_seed"), str))
    ready = [c for c in chunks if c.get("state") == "ready"]
    check("at least one chunk is ready", bool(ready), str([c.get("state") for c in chunks]))
    if ready:
        coord = ready[0]["chunk_id"].split(":")
        first = b.get(f"/chunk/{coord[0]}/{coord[1]}")
        body = first.content
        sha = hashlib.sha256(body).hexdigest()
        check("/chunk ETag is the quoted sha256 of the body, equal to the listing", first.status_code == 200 and first.headers.get("etag") == f'"{sha}"' and sha == ready[0]["sha256"],
              f"{first.status_code} {first.headers.get('etag')}")
        second = b.get(f"/chunk/{coord[0]}/{coord[1]}")
        check("a repeat fetch returns identical bytes", second.content == body)
        cached = b.get(f"/chunk/{coord[0]}/{coord[1]}", headers={"If-None-Match": f'"{sha}"'})
        check("If-None-Match gives 304 with no body", cached.status_code == 304 and not cached.content)
    check("window too large is 400", b.get("/chunks", params=dict(cx0=0, cy0=0, cx1=40, cy1=40)).status_code == 400)
    check("max < min is 400", b.get("/chunks", params=dict(cx0=3, cy0=0, cx1=1, cy1=0)).status_code == 400)
    check("non-integer coordinates are 422", b.get("/chunks", params=dict(cx0="a", cy0=0, cx1=1, cy1=0)).status_code == 422)

    # the 409 path -----------------------------------------------------------------------------------------------------
    view = dict(center_x=300.0, center_y=300.0, view_world_w=640.0, view_world_h=360.0)
    stale = b.post("/view/window", {**view, "window_epoch": epoch + 7})
    check("a request naming another window_epoch is 409 stale_window_epoch", stale.status_code == 409 and stale.json().get("reason") == "stale_window_epoch"
          and stale.json().get("window_epoch") == epoch and stale.json().get("window_origin") == origin, f"{stale.status_code} {stale.text[:120]}")
    fresh = b.post("/view/window", {**view, "window_epoch": epoch})
    check("the current window_epoch is accepted and the reply is stamped", fresh.status_code == 200 and WINDOW_KEYS <= set(fresh.json()), str(fresh.status_code))
    bare = b.post("/view/window", view)
    check("a request without window_epoch counts as current", bare.status_code == 200)
    human = b.post("/human_view/window", {**view, "window_epoch": epoch + 7})
    check("/human_view/window answers 409 too", human.status_code == 409, str(human.status_code))
    out["facts"] = window_facts(b)


def residents_abs(frame):
    ox, oy = frame["window_origin"]
    return {a["id"]: (a["x"] + ox * 256.0, a["y"] + oy * 256.0) for a in frame["agents"] if a.get("space", 0) == 0}


def player_position(frame, player):
    actor = next(a for a in frame['agents'] if a['id'] == player)
    if actor.get('space', 0) != 0:
        raise ValueError('walker left overworld')
    return tuple(frame['window_origin']), (float(actor['x']), float(actor['y']))


def displacement(start, current, chunk_units=256):
    """Subtract integer origins before float conversion, even at large coordinates."""
    origin0, local0 = start
    origin1, local1 = current
    return tuple((int(origin1[i]) - int(origin0[i])) * chunk_units + local1[i] - local0[i] for i in (0, 1))


def distance_result(max_east, final_delta, target, outbound_reached, tolerance=32):
    distance = math.hypot(*final_delta)
    return {'maximum_east_displacement': max_east, 'return_distance': distance,
            'outbound_complete': outbound_reached and max_east >= target,
            'return_complete': outbound_reached and distance <= tolerance}


def stamped_input(b, body, frame, counts, max_refresh=2):
    """Retry only explicit stale-window rejection; never replay ambiguous failures."""
    for attempt in range(max_refresh + 1):
        body['window_epoch'] = frame['window_epoch']
        reply = b.post('/control/input', body)
        payload = reply.json()
        if not isinstance(payload, dict):
            raise RuntimeError('control input returned a malformed payload')
        if reply.status_code == 200 and payload.get('ok'):
            counts['accepted'] += 1
            return frame
        if reply.status_code == 409 and payload.get('reason') == 'stale_window_epoch':
            counts['stale_window'] += 1
            if attempt < max_refresh:
                frame = b.get('/frame').json()
                body['seq'] += 1
                continue
            counts['stale_exhausted'] += 1
            raise RuntimeError('stale-window refresh budget exhausted')
        counts['valid_input_rejected'] += 1
        raise RuntimeError(f'control input rejected: {reply.status_code} {payload}')


def memory_sample(pid):
    """Main backend RSS only, not worker-tree RSS; no extra dependency."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                raise OSError(ctypes.get_last_error())
            try:
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    raise OSError(ctypes.get_last_error())
                value, source = int(counters.WorkingSetSize), 'GetProcessMemoryInfo.WorkingSetSize'
            finally:
                kernel.CloseHandle(handle)
        else:
            pages = int(Path(f'/proc/{pid}/statm').read_text().split()[1])
            value, source = pages * os.sysconf('SC_PAGE_SIZE'), '/proc/PID/statm resident pages'
        return {'bytes': value, 'metric': 'main_backend_rss', 'source': source}
    except (OSError, ValueError, IndexError) as exc:
        return {'bytes': None, 'metric': 'main_backend_rss', 'source': None, 'unavailable': str(exc)}


SUBLINEAR_FACTOR = 0.5   # orchestrator ruling 1118 (R0.5 REVISE), not a contract number
NOISE_FLOOR_BYTES = 16 * 2 ** 20   # orchestrator ruling 1118 after run 7: allocator noise (run 7's peak was +10 MiB), not a contract number


def memory_bound(samples):
    """R0.5 plateau rule on main-backend RSS. With growth g1 = max(0, rss(half) - rss(start)) over the outbound leg's first half (a falling
    RSS, e.g. Windows trimming the working set, is no growth: run 7), it passes only when the second half grew clearly sublinearly,
    rss(far) - rss(half) <= max(0.5 * g1, NOISE_FLOOR_BYTES), and the return leg grew no more than the first half,
    rss(end) - rss(far) <= g1 + NOISE_FLOOR_BYTES. The 16 MiB floor is allocator noise (orchestrator ruling after run 7). ``ok`` is None when
    any marked sample is missing."""
    marks = {}
    for sample in samples:
        if sample.get('mark') and sample['mark'] not in marks:
            # a sample of the venv launcher stub (backend_pid fallback) is not the backend's memory: unknown, never evidence
            marks[sample['mark']] = None if sample.get('pid_kind') == 'launcher_fallback' else sample.get('bytes')
    start, half, far, end = (marks.get(key) for key in ('start', 'half', 'far', 'end'))
    values = [s['bytes'] for s in samples if type(s.get('bytes')) is int and s.get('pid_kind') != 'launcher_fallback']
    known = all(type(v) is int for v in (start, half, far, end))
    first = half - start if known else None
    grown = max(0, first) if known else None
    return {'rule': ('g1 = max(0, rss(half) - rss(start)); rss(far) - rss(half) <= max(0.5 * g1, 16 MiB) and rss(end) - rss(far) <= g1 + 16 MiB, '
                     'main backend RSS'),
            'sublinear_factor': SUBLINEAR_FACTOR,
            'sublinear_factor_source': 'orchestrator ruling 1118 (R0.5 REVISE); not a contract number',
            'noise_floor_bytes': NOISE_FLOOR_BYTES,
            'noise_floor_source': 'orchestrator ruling 1118 after run 7 (allocator noise); not a contract number',
            'first_half_growth_clamped': (first < 0) if known else None,
            'start_bytes': start, 'half_bytes': half, 'far_bytes': far, 'end_bytes': end,
            'first_half_growth_bytes': first, 'second_half_growth_bytes': far - half if known else None,
            'return_leg_growth_bytes': end - far if known else None,
            'peak_minus_start_bytes': max(values) - start if values and type(start) is int else None,   # information only
            'ok': (far - half <= max(SUBLINEAR_FACTOR * grown, NOISE_FLOOR_BYTES) and end - far <= grown + NOISE_FLOOR_BYTES) if known else None}


def memory_summary(samples):
    values = [s['bytes'] for s in samples if s.get('bytes') is not None]
    bound = memory_bound(samples)
    missing = ['worker-tree RSS is not sampled (main backend only)']
    if bound['ok'] is None:
        missing.insert(0, 'start, half-way or far-point RSS sample missing: the plateau rule is unknown, not a pass')
    return {'samples': samples, 'start_bytes': samples[0].get('bytes') if samples else None,
            'end_bytes': samples[-1].get('bytes') if samples else None,
            'peak_bytes': max(values) if values else None,
            'plateau': bound, 'peak_minus_start_bytes_information_only': bound['peak_minus_start_bytes'],
            'bounded_growth_acceptance': bound['ok'],
            'missing': missing}


def player_void_delta(before_stats, after_stats, *, before_world_epoch, after_world_epoch,
                      same_manager=False, same_counter_generation=False, sole_controller=False):
    """Prepared stats adapter; not wired to HTTP until attribution/envelope are verified.

    The counter aggregates controlled humans. A run delta needs the same manager
    and world, and the probe's isolated sole-controller scope. Window rebases do
    not reset counters and therefore do not invalidate a delta by themselves.
    """
    result = {'source': 'WindowManager.stats().counters.void_hits_player',
              'player_void_hits': None, 'known': False}
    if not before_world_epoch or before_world_epoch != after_world_epoch or same_manager is not True:
        return {**result, 'unavailable': 'world or window-manager lifetime is not confirmed unchanged'}
    if same_counter_generation is not True:
        return {**result, 'unavailable': 'counter reset generation is not confirmed unchanged'}
    if sole_controller is not True:
        return {**result, 'unavailable': 'counter aggregates controlled humans; sole-controller scope is not confirmed'}
    values = []
    for stats in (before_stats, after_stats):
        counters = stats.get('counters') if isinstance(stats, dict) else None
        if not isinstance(counters, dict):
            return {**result, 'unavailable': 'window stats/counters unavailable'}
        row = [counters.get(key) for key in ('void_hits', 'void_hits_player', 'void_hits_resident')]
        if any(type(value) is not int or value < 0 for value in row):
            return {**result, 'unavailable': 'void counter missing or not a nonnegative integer'}
        if row[0] != row[1] + row[2]:
            return {**result, 'unavailable': 'void counter attribution totals are inconsistent'}
        values.append(row)
    if any(end < start for start, end in zip(*values)):
        return {**result, 'unavailable': 'void counters reset or moved backwards'}
    return {**result, 'known': True, 'player_void_hits': values[1][1] - values[0][1],
            'resident_void_hits': values[1][2] - values[0][2],
            'before': values[0][1], 'after': values[1][1]}


SHIM_ROUTE = '/_smoke/window_stats'
SHIM_SOURCE = f'live_smoke_window --serve-backend shim: GET {SHIM_ROUTE} (read-only, added in the smoke backend process only; map_test.py unchanged)'


def void_from_window_stats(before, after, player):
    """Two shim telemetry replies -> ``player_void_delta``; the scope (same world, same manager, no counter reset, the walker the only
    controller) is decided only from what the shim reported, so a missing or odd reply stays unknown."""
    def get(reply, key):
        return reply.get(key) if isinstance(reply, dict) else None
    manager, generation = get(before, 'manager_id'), get(before, 'counter_generation')
    result = player_void_delta(get(before, 'stats'), get(after, 'stats'),
                               before_world_epoch=get(before, 'world_epoch'), after_world_epoch=get(after, 'world_epoch'),
                               same_manager=manager is not None and manager == get(after, 'manager_id'),
                               same_counter_generation=type(generation) is int and generation == get(after, 'counter_generation'),
                               sole_controller=get(before, 'controlled') == [player] and get(after, 'controlled') == [player])
    return {**result, 'telemetry_source': SHIM_SOURCE}


def left_behind_stable(samples, player, frame=(-1280.0, 1536.0), tolerance=0.01):
    """Residents left behind keep their absolute positions across re-bases. A resident counts once it is outside the fixed window frame
    (window-local [-1280, 1536), harness/window.py WINDOW_FRAME) in three consecutive samples, so it is past the dormancy grace; its absolute
    position must then agree between the last two within ``tolerance`` units. ``ok`` is None unless at least one checked pair spans a re-base."""
    def outside(sample, rid):
        row = sample['residents'].get(rid)
        if not row or row.get('space', 0) != 0 or row.get('absolute') is None:
            return False
        ox, oy = sample['origin']
        lx, ly = row['absolute'][0] - ox * 256.0, row['absolute'][1] - oy * 256.0
        return not (frame[0] <= lx < frame[1] and frame[0] <= ly < frame[1])
    checked, across, drift = 0, 0, []
    for a, b, c in zip(samples, samples[1:], samples[2:]):
        for rid in b['residents']:
            if rid == player or not all(outside(s, rid) for s in (a, b, c)):
                continue
            p, q = b['residents'][rid]['absolute'], c['residents'][rid]['absolute']
            checked += 1
            across += b['epoch'] != c['epoch']
            moved = max(abs(p[0] - q[0]), abs(p[1] - q[1]))
            if moved > tolerance:
                drift.append({'id': rid, 'moved': moved, 'epochs': [b['epoch'], c['epoch']]})
    return {'pairs_checked': checked, 'pairs_across_rebase': across, 'tolerance_units': tolerance, 'drift': drift,
            'ok': False if drift else (True if across else None)}


def live_gate(evidence):
    """Gate D verdict for the long walk: (passed, reasons). Unknown never passes."""
    reasons = []
    if evidence.get('measured_walk_pass') is not True:
        reasons.append('measured east-and-return walk did not pass')
    if type(evidence.get('void_hits')) is not int:
        reasons.append('player void hits unknown')
    elif evidence['void_hits'] != 0:
        reasons.append(f"{evidence['void_hits']} player void hits")
    if (evidence.get('memory') or {}).get('bounded_growth_acceptance') is not True:
        reasons.append(f"memory plateau rule {(evidence.get('memory') or {}).get('bounded_growth_acceptance')}")
    if (evidence.get('left_behind') or {}).get('ok') is not True:
        reasons.append(f"left-behind residents check {(evidence.get('left_behind') or {}).get('ok')}")
    if (evidence.get('input_counts') or {}).get('valid_input_rejected') != 0:
        reasons.append(f"rejected inputs {(evidence.get('input_counts') or {}).get('valid_input_rejected')}")
    return (not reasons, reasons)


class Steer:
    """Capped Pledge wall-follow for one leg of the measured walk (R0.5 amend 2; the gate is net displacement, not a straight line).
    ``move(pos, heading, tick)`` before every input. Feedback is taken only when the frame tick advanced by ``eval_ticks`` (the frame may
    refresh every few ticks): if the walker moved less than ``min_move`` units since the last evaluation it turns ``step`` degrees (turn sum
    +step, rotating the heading towards +y first); if it moved and the turn sum is positive it tries ``step`` back (-step). It walks
    rotate(heading, turn sum) and leaves the wall after ``clear_moves`` free evaluations at turn sum 0. That escapes any finite obstacle,
    pockets included. Caps, so a dead end fails cleanly: an episode is a dead end past ``max_turn`` degrees or ``max_seconds``; at most
    ``max_episodes`` per leg. Every episode is recorded (start/end delta, max turn, duration, outcome)."""

    def __init__(self, name, step=45.0, min_move=0.5, eval_ticks=4, clear_moves=5, max_turn=1080.0, max_seconds=300.0, max_episodes=12,
                 stuck_window=4, stuck_net=1.0, clock=time.monotonic, side=1):
        self.side = 1 if side >= 0 else -1          # +1 turns counter-clockwise (+y first from an east heading), -1 the other way (R0.5 run 7)
        self.name, self.step, self.min_move, self.eval_ticks, self.clear_moves = name, step, min_move, eval_ticks, clear_moves
        self.max_turn, self.max_seconds, self.max_episodes, self.clock = max_turn, max_seconds, max_episodes, clock
        self.stuck_window, self.stuck_net = stuck_window, stuck_net
        self.turn, self.last, self.last_tick, self.free, self.episode = 0.0, None, None, 0, None
        # hysteresis (orchestrator ruling after run 4): one decision per window of ``stuck_window`` evaluations, and the walker counts as
        # stuck when its NET progress over that window is under ``stuck_net`` units; the windows do not overlap, so neither a pinned
        # walker's sub-unit frame wobble nor the motion of an earlier window reads as movement. 0 = the old per-evaluation test.
        self.decide_ticks = eval_ticks * max(1, stuck_window)
        self.threshold = max(min_move, stuck_net) if stuck_window else min_move
        self.episodes, self.exhausted = [], False

    def _feedback(self, pos):
        moved = math.hypot(pos[0] - self.last[0], pos[1] - self.last[1]) >= self.threshold
        if not moved:
            if self.episode is None:
                if len(self.episodes) >= self.max_episodes:
                    self.exhausted = True
                    return
                self.episode = {'leg': self.name, 'start_delta': [round(pos[0], 1), round(pos[1], 1)], 'turn_first': self._label(),
                                'max_turn_degrees': 0.0, 'started': self.clock(), 'duration_s': 0.0, 'end_delta': None, 'outcome': 'open'}
                self.episodes.append(self.episode)
            self.turn += self.step
            self.free = 0
        elif self.turn > 0:
            self.turn -= self.step
            self.free = 0
        else:
            self.free += 1
        episode = self.episode
        if episode is None:
            return
        episode['max_turn_degrees'] = max(episode['max_turn_degrees'], self.turn)
        episode['duration_s'] = round(self.clock() - episode['started'], 2)
        episode['end_delta'] = [round(pos[0], 1), round(pos[1], 1)]
        if self.turn <= 0 and self.free >= self.clear_moves:
            episode['outcome'], self.episode = 'cleared', None
        elif self.turn > self.max_turn or episode['duration_s'] > self.max_seconds:
            episode['outcome'], self.exhausted = 'dead_end', True

    def _label(self):
        return '+y from an east heading' if self.side > 0 else '-y from an east heading'

    def restart(self, side, outcome):
        """Close the open episode with ``outcome`` and start afresh on turn side ``side`` (a back-leg re-route). The caps keep counting."""
        if self.episode is not None:
            self.episode['outcome'], self.episode = outcome, None
        self.side = 1 if side >= 0 else -1
        self.turn, self.free, self.last, self.last_tick = 0.0, 0, None, None

    def move(self, pos, heading, tick):
        if not self.exhausted and (self.last_tick is None or tick - self.last_tick >= self.decide_ticks):
            if self.last is not None:
                self._feedback(pos)
            self.last, self.last_tick = tuple(pos), tick
        if self.exhausted:
            return {'x': 0.0, 'y': 0.0}
        a = math.radians(self.turn * self.side)
        x, y = heading[0] * math.cos(a) - heading[1] * math.sin(a), heading[0] * math.sin(a) + heading[1] * math.cos(a)
        norm = max(1e-9, math.hypot(x, y))
        return {'x': x / norm, 'y': y / norm}


class Breadcrumbs:
    """The outbound leg's path, a point every ``spacing`` units (R0.5 ruling after run 4: the outbound is proven walkable, so the back leg
    retraces it in reverse). ``heading(pos)`` is the unit vector to the current target crumb: the target moves one crumb towards the start
    once within ``reach``, and jumps to the earliest crumb within ``reach`` when the walker stands near one (an outbound loop is not
    replayed). The first crumb is the start itself, so the last target is home. ``Steer`` stays the local fallback between crumbs."""

    def __init__(self, spacing=16.0, reach=12.0):
        self.spacing, self.reach = spacing, reach
        self.points, self.index, self.jumps = [], None, 0

    def record(self, pos):
        if not self.points or math.hypot(pos[0] - self.points[-1][0], pos[1] - self.points[-1][1]) >= self.spacing:
            self.points.append((float(pos[0]), float(pos[1])))

    def heading(self, pos):
        if not self.points:
            norm = max(1e-9, math.hypot(pos[0], pos[1]))
            return (-pos[0] / norm, -pos[1] / norm)
        if self.index is None:
            self.index = len(self.points) - 1
        near = [i for i in range(self.index + 1) if math.hypot(pos[0] - self.points[i][0], pos[1] - self.points[i][1]) <= self.reach]
        if near:
            if near[0] < self.index - 1:
                self.jumps += 1
            self.index = max(0, near[0] - 1)
        tx, ty = self.points[self.index]
        dx, dy = tx - pos[0], ty - pos[1]
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            return (0.0, 0.0)
        return (dx / norm, dy / norm)


class Retrace:
    """The measured walk's back leg (R0.5 after run 7, orchestrator GO): ``Breadcrumbs`` give the target, ``Steer`` the local wall-follow,
    and a progress-aware stall test sits above both. Progress = the target crumb index advanced, or the distance to the target dropped by
    ``stuck_net`` below the best distance banked for that target (best moves only in ``stuck_net`` steps, so a swing that comes back to the
    same distance is no progress, while a slow steady approach is). After ``stall_windows`` decision windows without progress the walker
    re-routes: it walks back to the last crumb reached (proven path), then approaches the stalled crumb again with the Pledge turn side
    flipped. It never skips a crumb: crumbs nearer home are not proven reachable from the stall point. Caps: ``max_per_crumb`` re-routes per
    target crumb, ``max_reroutes`` per leg; one more stall is a dead end (a clean failure). Every re-route is recorded."""

    def __init__(self, crumbs, steer=None, stall_windows=12, stuck_net=1.0, max_per_crumb=2, max_reroutes=6, clock=time.monotonic):
        self.crumbs, self.clock = crumbs, clock
        self.steer = steer if steer is not None else Steer('back', clock=clock)
        self.name = self.steer.name
        self.stall_windows, self.stuck_net, self.max_per_crumb, self.max_reroutes = stall_windows, stuck_net, max_per_crumb, max_reroutes
        self.reroutes, self.per_crumb, self.retreat, self.dead_end = [], {}, None, None
        self.key, self.best, self.stalls, self.last_tick, self.exhausted = None, math.inf, 0, None, False

    @property
    def episodes(self):
        return self.steer.episodes

    @staticmethod
    def _unit(dx, dy):
        norm = math.hypot(dx, dy)
        return (0.0, 0.0) if norm < 1e-9 else (dx / norm, dy / norm)

    def _target(self, pos):
        """(progress key, target point, heading). While re-routing the target is the retreat crumb; once within reach, the stalled crumb."""
        points = self.crumbs.points
        if self.retreat is not None:
            tx, ty = points[self.retreat['retreat_to']]
            if math.hypot(tx - pos[0], ty - pos[1]) > self.crumbs.reach:
                return ('retreat', self.retreat['retreat_to']), (tx, ty), self._unit(tx - pos[0], ty - pos[1])
            self.retreat['outcome'], self.retreat = 'approaching', None
        heading = self.crumbs.heading(pos)
        if not points:
            return ('home', None), (0.0, 0.0), heading
        return ('crumb', self.crumbs.index), points[self.crumbs.index], heading

    def _open_row(self):
        return self.reroutes[-1] if self.reroutes and self.reroutes[-1]['outcome'] in ('retreating', 'approaching') else None

    def _close(self, row, outcome, pos):
        row['outcome'], row['end_delta'] = outcome, [round(pos[0], 1), round(pos[1], 1)]
        row['duration_s'] = round(self.clock() - row['started'], 2)

    def _judge(self, key, dist, pos):
        row = self._open_row()
        if row is not None and key[0] == 'crumb' and key[1] < row['crumb']:
            self._close(row, 'resumed', pos)
        if key != self.key:
            self.key, self.best, self.stalls = key, dist, 0
            return
        if dist <= self.best - self.stuck_net:
            self.best, self.stalls = dist, 0
            return
        self.stalls += 1
        if self.stalls >= self.stall_windows:
            self._stall(key, pos)

    def _stall(self, key, pos):
        row = self._open_row()
        crumb = key[1] if key[0] == 'crumb' else row['crumb']
        if row is not None:
            self._close(row, 'stalled', pos)
        self.retreat, self.key, self.stalls = None, None, 0
        if self.per_crumb.get(crumb, 0) >= self.max_per_crumb or len(self.reroutes) >= self.max_reroutes:
            self.exhausted = True
            self.dead_end = {'leg': self.name, 'crumb': crumb, 'delta': [round(pos[0], 1), round(pos[1], 1)], 'outcome': 'dead_end',
                             'reroutes_on_crumb': self.per_crumb.get(crumb, 0)}
            if self.steer.episode is not None:
                self.steer.episode['outcome'] = 'dead_end'
            return
        self.per_crumb[crumb] = self.per_crumb.get(crumb, 0) + 1
        side = -self.steer.side
        self.steer.restart(side, 'rerouted')
        self.retreat = {'leg': self.name, 'crumb': crumb, 'retreat_to': min(crumb + 1, len(self.crumbs.points) - 1), 'side': side,
                        'start_delta': [round(pos[0], 1), round(pos[1], 1)], 'started': self.clock(), 'duration_s': 0.0, 'end_delta': None,
                        'outcome': 'retreating'}
        self.reroutes.append(self.retreat)

    def move(self, pos, tick):
        if self.exhausted:
            return {'x': 0.0, 'y': 0.0}
        key, point, heading = self._target(pos)
        if key[0] != 'home' and (self.last_tick is None or tick - self.last_tick >= self.steer.decide_ticks):
            if self.last_tick is not None:
                self._judge(key, math.hypot(point[0] - pos[0], point[1] - pos[1]), pos)
                if self.exhausted:
                    return {'x': 0.0, 'y': 0.0}
                if self.retreat is not None and key[0] == 'crumb':
                    key, point, heading = self._target(pos)          # a re-route just began: head for the retreat crumb
            self.last_tick = tick
        if heading == (0.0, 0.0):
            heading = self._unit(-pos[0], -pos[1])
        move = self.steer.move(pos, heading, tick)
        self.exhausted = self.exhausted or self.steer.exhausted
        return move


def route_verdict(route_samples, spawn_chunk=None):
    """Every sampled player chunk must be ``ready`` on /chunks; it must also be in the window's integrated set, with at most a one-sample lag
    (a sprint across a border can sample the new chunk before its integration tick). Samples without a set coherent with the frame neither
    extend nor break a lag run. Every lag is counted; two or more consecutive lagging samples fail (orchestrator ruling 1118).
    ``spawn_chunk`` (R0.5 after run 7: F1 spawns the player inside the pinned starter village): a ``pinned_map`` row naming its map counts as
    ready on that one chunk only. Every sample is taken at the player's own chunk, so that is exactly while the player is in it."""
    lags, run, worst, ready, pinned = [], 0, 0, bool(route_samples), 0
    spawn = list(spawn_chunk) if spawn_chunk is not None else None
    for index, sample in enumerate(route_samples):
        chunk_id = f"{sample['chunk'][0]}:{sample['chunk'][1]}"
        rows = sample.get('route') or []
        row = rows[0] if len(rows) == 1 and rows[0].get('chunk_id') == chunk_id else None
        on_spawn = (row is not None and spawn is not None and list(sample['chunk']) == spawn and row.get('state') == 'pinned_map'
                    and bool(row.get('pinned_map')))
        ready &= row is not None and (row.get('state') == 'ready' or on_spawn)
        pinned += on_spawn
        if not sample.get('coherent_with_frame') or sample.get('integrated') is None:
            continue
        if chunk_id in sample['integrated']:
            run = 0
        else:
            run += 1
            worst = max(worst, run)
            lags.append({'index': index, 'chunk': list(sample['chunk'])})
    return {'ok': bool(ready and worst < 2), 'all_ready': bool(ready), 'lag_samples': len(lags), 'max_consecutive_lag': worst, 'lags': lags,
            'spawn_chunk': spawn, 'pinned_accepted': pinned,
            'rule': ('ready on /chunks always (pinned_map accepted on the spawn chunk only); integrated at that sample or after at most one '
                     'lagging sample')}


def backend_pid(stats, fallback):
    """The pid whose RSS is the backend's: the shim reports its own interpreter's pid (``.venv\\Scripts\\python.exe`` is a launcher stub that
    spawns it, so ``Popen.pid`` is the stub's). Without it the launcher pid is returned, labelled, and its samples never count as evidence."""
    pid = stats.get('pid') if isinstance(stats, dict) else None
    return (pid, 'backend_interpreter') if type(pid) is int and pid > 0 else (fallback, 'launcher_fallback')


def window_stats(b):
    """One shim telemetry read; any failure is recorded, never raised (the counters then stay unknown)."""
    try:
        reply = b.get(SHIM_ROUTE)
        payload = reply.json()
        return payload if reply.status_code == 200 and isinstance(payload, dict) else {'unavailable': f'{reply.status_code}'}
    except (httpx.HTTPError, ValueError) as exc:
        return {'unavailable': str(exc)}


def resident_snapshot(frame):
    positions = residents_abs(frame)
    return {a['id']: {'absolute': positions.get(a['id']), 'space': a.get('space', 0),
                     'slot': a.get('slot', a.get('row_slot'))} for a in frame['agents']}


def phase_long_walk(b, target, seconds, evidence):
    """Measured east-and-return legs through the real control API, with bounded time."""
    evidence.update(target_east_units=target, deadline_seconds=seconds, return_tolerance_units=32,
                    samples=[], route_samples=[], memory_samples=[],
                    input_counts=dict(accepted=0, stale_window=0, stale_exhausted=0, valid_input_rejected=0),
                    missing_metrics=['void hit counters come only through the smoke shim route, not the game API',
                                     'resident row slots are recorded only when exposed'], void_hits=None,
                    void_telemetry_ready=False,
                    live_gate_complete=False)
    counts = evidence['input_counts']
    start = current = None
    max_east, max_distance, outbound = 0.0, 0.0, False
    epochs = set()
    player, stats_before, half_marked = None, None, False
    legs = {'out': Steer('out'), 'back': Steer('back')}
    crumbs = Breadcrumbs()
    retrace = Retrace(crumbs, legs['back'])
    path_length, max_lateral, last = 0.0, 0.0, None
    mem_pid, mem_kind = getattr(getattr(b, 'proc', None), 'pid', None), 'launcher_fallback'

    def mem(**extra):
        return {**memory_sample(mem_pid), 'pid': mem_pid, 'pid_kind': mem_kind, **extra}
    try:
        claim = b.post('/control/claim', {'mode': 'incarnate', 'preferred_name': 'LongWalker'})
        if claim.status_code != 200:
            raise RuntimeError(f'incarnation failed: {claim.status_code} {claim.text[:120]}')
        control = claim.json()
        player = control['target_id']
        stats_before = window_stats(b)
        mem_pid, mem_kind = backend_pid(stats_before, mem_pid)
        evidence['memory_pid'] = {'pid': mem_pid, 'kind': mem_kind, 'launcher_pid': getattr(getattr(b, 'proc', None), 'pid', None)}
        frame = b.get('/frame').json()
        start = current = player_position(frame, player)
        evidence['spawn_chunk'] = [int(start[0][0]) + math.floor(start[1][0] / 256), int(start[0][1]) + math.floor(start[1][1] / 256)]
        evidence['memory_samples'].append(mem(mark='start', delta_east=0.0))
        evidence['player_id'] = player
        evidence['residents_start'] = resident_snapshot(frame)
        deadline = time.monotonic() + seconds
        seq = 0
        iteration = 0
        while time.monotonic() < deadline:
            frame = b.get('/frame').json()
            current = player_position(frame, player)
            dx, dy = displacement(start, current)
            if last is not None:
                path_length += math.hypot(dx - last[0], dy - last[1])
            last = (dx, dy)
            max_lateral = max(max_lateral, abs(dy))
            max_east = max(max_east, dx)
            max_distance = max(max_distance, math.hypot(dx, dy))
            epochs.add(frame['window_epoch'])
            if not half_marked and dx >= target / 2:
                half_marked = True
                evidence['memory_samples'].append(mem(mark='half', delta_east=dx))
            if not outbound:
                crumbs.record((dx, dy))                               # the proven-walkable outbound path, every 16 units
            if dx >= target and not outbound:
                outbound = True
                evidence['memory_samples'].append(mem(mark='far', delta_east=dx))
            if outbound and math.hypot(dx, dy) <= 32:
                break
            steer = retrace if outbound else legs['out']                 # back leg: retrace the outbound crumbs in reverse (Retrace)
            if iteration % 20 == 0:
                evidence['samples'].append({'elapsed': seconds - (deadline - time.monotonic()),
                    'epoch': frame['window_epoch'], 'origin': list(current[0]), 'delta': [dx, dy],
                    'residents': resident_snapshot(frame)})
                evidence['memory_samples'].append(mem(delta_east=dx))
                # Read-only route query at the player's actual absolute chunk.
                cx = int(current[0][0]) + math.floor(current[1][0] / 256)
                cy = int(current[0][1]) + math.floor(current[1][1] / 256)
                route = b.get('/chunks', params=dict(cx0=cx, cy0=cy, cx1=cx, cy1=cy))
                if route.status_code != 200:
                    raise RuntimeError(f'chunk route failed: {route.status_code}')
                rows = route.json().get('chunks', [])
                delta = b.get('/map_delta').json()
                integrated = delta.get('window', {}).get('integrated')
                coherent = delta.get('window_epoch') == frame['window_epoch'] and delta.get('window_origin') == frame['window_origin']
                evidence['route_samples'].append({'chunk': [cx, cy], 'route': rows, 'integrated': integrated,
                    'coherent_with_frame': coherent, 'state_version': delta.get('state_version')})
            tick = int(frame.get('tick', 4 * iteration))
            move = retrace.move((dx, dy), tick) if outbound else legs['out'].move((dx, dy), (1.0, 0.0), tick)
            if steer.exhausted:
                raise RuntimeError(f'wall-follow cap reached on the {steer.name} leg at delta {[round(dx, 1), round(dy, 1)]}: dead end '
                                   f'({len(steer.episodes)} episodes, {len(retrace.reroutes) if outbound else 0} re-routes, '
                                   f'last {steer.episodes[-1] if steer.episodes else None})')
            seq += 1
            body = dict(protocol_version=1, world_epoch=control['world_epoch'], possession_epoch=control['possession_epoch'],
                        target_kind='human', target_id=player, seq=seq, move=move,
                        buttons={'sprint': True}, intent_state={'moving': True, 'sprinting': True})
            frame = stamped_input(b, body, frame, counts)
            seq = body['seq']
            iteration += 1
            time.sleep(0.1)
        # A real stop command ends locomotion before the final measured frame.
        stop_body = dict(protocol_version=1, world_epoch=control['world_epoch'], possession_epoch=control['possession_epoch'],
                         target_kind='human', target_id=player, seq=seq+1, move={'x': 0.0, 'y': 0.0},
                         buttons={'sprint': False}, intent_state={'moving': False, 'sprinting': False})
        frame = stamped_input(b, stop_body, frame, counts)
        time.sleep(0.1)  # allow the accepted stop to enter a normal tick; no movement shortcut
        evidence['window_stats_after'] = window_stats(b)
        frame = b.get('/frame').json()
        current = player_position(frame, player)
        dx, dy = displacement(start, current)
        max_east, max_distance = max(max_east, dx), max(max_distance, math.hypot(dx, dy))
        epochs.add(frame['window_epoch'])
        evidence['residents_end'] = resident_snapshot(frame)
        evidence['resident_ids_restored'] = set(evidence['residents_start']) <= set(evidence['residents_end'])
        exposed = {key: value['slot'] for key, value in evidence['residents_start'].items() if value['slot'] is not None}
        evidence['resident_slots_stable'] = all(evidence['residents_end'].get(key, {}).get('slot') == slot for key, slot in exposed.items()) if exposed else None
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, StopIteration) as exc:
        evidence['error'] = str(exc)
    finally:
        evidence['memory_samples'].append(mem(mark='end'))
        evidence['memory'] = memory_summary(evidence.pop('memory_samples'))
        evidence['path'] = {'gate': 'net displacement (>= target east, then back within 32 units), not a straight line',
                            'total_path_length': round(path_length, 1), 'max_lateral_offset': round(max_lateral, 1),
                            'steering': ('outbound heads east; the back leg retraces the outbound breadcrumbs in reverse; capped Pledge wall-follow '
                                         '(Steer) only as the local fallback between crumbs: 45 degree turns, caps 1080 degrees / 300 s per episode, '
                                         f'12 episodes per leg; stuck only if net progress < {legs["out"].stuck_net} unit over '
                                         f'{legs["out"].stuck_window} inputs (hysteresis, non-overlapping windows); back leg: progress-aware '
                                         f'stall test (no >= {retrace.stuck_net} unit gain on the best distance to the target crumb over '
                                         f'{retrace.stall_windows} decision windows) re-routes to the last crumb reached and retries with the turn '
                                         f'side flipped, never skips a crumb; caps {retrace.max_per_crumb} per crumb, {retrace.max_reroutes} per leg'),
                            'breadcrumbs': {'count': len(crumbs.points), 'spacing': crumbs.spacing, 'reach': crumbs.reach,
                                            'index_reached': crumbs.index, 'jumps': crumbs.jumps},
                            'detours': [{k: v for k, v in e.items() if k != 'started'} for e in legs['out'].episodes + legs['back'].episodes],
                            'reroutes': [{k: v for k, v in r.items() if k != 'started'} for r in retrace.reroutes],
                            'reroute_caps': {'stall_windows': retrace.stall_windows, 'per_crumb': retrace.max_per_crumb,
                                             'per_leg': retrace.max_reroutes},
                            'dead_end': retrace.dead_end,
                            'episode_budget_per_leg': legs['out'].max_episodes,
                            'exhausted': [n for n, s in (('out', legs['out']), ('back', retrace)) if s.exhausted]}
        if 'window_stats_after' not in evidence and stats_before is not None:
            evidence['window_stats_after'] = window_stats(b)          # the walk failed early: void must still be known
            evidence['window_stats_after_read_on_error_path'] = True
        evidence['window_stats_before'] = stats_before
        void = void_from_window_stats(stats_before, evidence.get('window_stats_after'), player)
        evidence['void'] = void
        evidence['void_telemetry_ready'] = void['known']
        evidence['void_hits'] = void['player_void_hits']
        evidence['left_behind'] = left_behind_stable(evidence['samples'], player)
        evidence['maximum_absolute_displacement'] = max_distance
        final_delta = displacement(start, current) if start is not None and current is not None else (0, 0)
        evidence.update(distance_result(max_east, final_delta, target, outbound))
        evidence['rebase_epochs'] = sorted(epochs)
        coherent_sets = [set(s['integrated']) for s in evidence['route_samples']
                         if s['coherent_with_frame'] and s['integrated'] is not None]
        evidence['residency_transitions'] = [
            {'added': sorted(after-before), 'removed': sorted(before-after)}
            for before, after in zip(coherent_sets, coherent_sets[1:]) if before != after]
        evidence['residency_changed'] = bool(evidence['residency_transitions'])
        evidence['route_verdict'] = route_verdict(evidence['route_samples'], evidence.get('spawn_chunk'))
        evidence['routes_ready'] = evidence['route_verdict']['ok']
        measured_ok = (evidence['outbound_complete'] and evidence['return_complete'] and len(epochs) > 1
                       and evidence['routes_ready'] and evidence['residency_changed'] and evidence.get('resident_ids_restored')
                       and evidence.get('resident_slots_stable') is not False
                       and not evidence.get('error') and counts['valid_input_rejected'] == 0)
        evidence['measured_walk_pass'] = bool(measured_ok)
        check('long walk reaches measured east target and returns', bool(measured_ok),
              f"max east {max_east:.1f}, return {evidence['return_distance']:.1f}, error {evidence.get('error')}")
        gate, reasons = live_gate(evidence)
        evidence['live_gate_complete'], evidence['live_gate_reasons'] = gate, reasons
        plateau = evidence['memory']['plateau']
        print(f"INFO  epochs {len(epochs)}, inputs {counts}, player void hits {evidence['void_hits']} (resident {void.get('resident_void_hits')}; "
              f"via the smoke shim), RSS growth first/second half/return {plateau['first_half_growth_bytes']}/{plateau['second_half_growth_bytes']}/"
              f"{plateau['return_leg_growth_bytes']} (rule factor {plateau['sublinear_factor']}, orchestrator ruling), "
              f"peak-start {plateau['peak_minus_start_bytes']} (information only), left-behind pairs {evidence['left_behind']['pairs_checked']} "
              f"({evidence['left_behind']['pairs_across_rebase']} across a re-base), path {evidence['path']['total_path_length']} units, "
              f"max lateral {evidence['path']['max_lateral_offset']}, detours {len(evidence['path']['detours'])}, route lags "
              f"{evidence['route_verdict']['lag_samples']} (max {evidence['route_verdict']['max_consecutive_lag']} in a row), memory pid "
              f"{evidence.get('memory_pid')}", flush=True)
        check('Gate D: 0 player void hits, memory plateaus, residents left behind keep absolute positions, 0 rejected inputs', gate, '; '.join(reasons))


def phase_walk(b, seconds=150.0, chunks_away=3):
    """Incarnate a player and walk east (sidestepping obstacles): input is accepted past the village rectangle, the window re-bases to follow the
    player, the stamps change, the residents left behind keep their absolute positions."""
    claim = b.client.post("/control/claim", json={"mode": "incarnate", "preferred_name": "Walker"}, headers=b.session)
    check("incarnating a player works", claim.status_code == 200, claim.text[:120])
    if claim.status_code != 200:
        return
    c = claim.json()
    start = b.get("/frame").json()
    before = residents_abs(start)
    player = c["target_id"]
    start_x = before[player][0]
    seq, side, flips, still, last, rejected = 0, 0.0, 0, 0, None, 0
    epochs, origins, deadline = {start["window_epoch"]}, [tuple(start["window_origin"])], time.time() + seconds
    frame = start
    while time.time() < deadline:
        seq += 1
        reply = b.client.post("/control/input", headers=b.session, json={
            "protocol_version": 1, "world_epoch": c["world_epoch"], "possession_epoch": c["possession_epoch"], "target_kind": "human",
            "target_id": player, "seq": seq, "move": {"x": 1.0, "y": side}, "buttons": {"sprint": True}, "intent_state": {"moving": True, "sprinting": True}})
        rejected += 0 if reply.json().get("ok") else 1
        if seq % 20 == 0:
            frame = b.get("/frame").json()
            epochs.add(frame["window_epoch"])
            if tuple(frame["window_origin"]) != origins[-1]:
                origins.append(tuple(frame["window_origin"]))
            here = residents_abs(frame).get(player)
            if here is not None and last is not None and abs(here[0] - last[0]) < 0.5 and abs(here[1] - last[1]) < 0.5:
                still += 1
                if still >= 2:
                    flips, still = flips + 1, 0
                    side = 1.0 if (flips // 2) % 2 == 0 else -1.0
            else:
                still = 0
            last = here
            if here is not None and here[0] - start_x > chunks_away * 256.0 + 400.0 and len(epochs) >= 2:
                break
        time.sleep(0.1)
    after = residents_abs(frame)
    gone = after.get(player, (start_x, 0))[0] - start_x
    check("control input is accepted past the village rectangle", rejected == 0, f"{rejected} rejected")
    check("the player walks more than three chunks east", gone > chunks_away * 256.0, f"{gone:.0f} units")
    check("the window re-based to follow the player", len(epochs) >= 2 and len(origins) >= 2, f"epochs {sorted(epochs)}, origins {origins}")
    check("/frame was stamped with the origin and epoch throughout", WINDOW_KEYS <= set(frame))
    everyone = {a["id"] for a in frame["agents"]}
    left = [i for i in before if i != player and i in after]            # still in space 0 (some walked into an interior meanwhile)
    moved = {i: max(abs(after[i][0] - before[i][0]), abs(after[i][1] - before[i][1])) for i in left}
    check("every resident is still in the frame payload", set(before) <= everyone, str(sorted(set(before) - everyone)))
    check("the residents left behind kept their absolute positions (no snapping)", all(v < 400.0 for v in moved.values()), str({i[-2:]: round(v) for i, v in moved.items()}))
    far = [i for i in left if abs(after[i][0] - after[player][0]) > 5 * 256.0]
    print(f"INFO  {len(far)} of {len(left)} space-0 residents ended more than 5 chunks from the player (outside the window)", flush=True)
    # dormancy: a resident outside the fixed frame does nothing (bit-identical position) while the player is away
    time.sleep(2.0)                                                     # the player stops (input timeout), the window settles
    t0, f0 = time.time(), b.get("/frame").json()
    time.sleep(6.0)
    f1 = b.get("/frame").json()
    check("the simulation keeps its pace while residents are dormant", f1["tick"] - f0["tick"] >= 0.7 * 20 * (time.time() - t0), f"{f1['tick'] - f0['tick']} ticks in 6 s")
    check("the window is still while the player stands", f0["window_origin"] == f1["window_origin"], f"{f0['window_origin']} {f1['window_origin']}")
    if f0["window_origin"] == f1["window_origin"]:
        a0 = {a["id"]: (a["x"], a["y"]) for a in f0["agents"] if a.get("space", 0) == 0}
        a1 = {a["id"]: (a["x"], a["y"]) for a in f1["agents"] if a.get("space", 0) == 0}
        outside = [i for i, (x, y) in a0.items() if i != player and not (-1280 <= x < 1536 and -1280 <= y < 1536) and i in a1]
        check("residents outside the frame do not move while the player is away (dormant)", bool(outside) and all(a0[i] == a1[i] for i in outside),
              f"{len(outside)} outside, max move {max([abs(a1[i][0] - a0[i][0]) + abs(a1[i][1] - a0[i][1]) for i in outside] or [0]):.3f}")


def phase_save(b, out):
    reply = b.post("/session/save", {})
    check("/session/save succeeds", reply.status_code == 200, f"{reply.status_code} {reply.text[:160]}")
    saves = b.get("/session").json().get("saves", [])
    check("the save is listed", bool(saves), str(len(saves)))
    out["save_id"] = (saves[0].get("save_id") or saves[0].get("id")) if saves else None
    return out["save_id"]


def same_window(label, before, after):
    check(f"{label}: world seed, generator, window origin and epoch are unchanged", before["world"] == after["world"] and before["origin"] == after["origin"] and before["epoch"] == after["epoch"],
          f"{before['origin']}/{before['epoch']} vs {after['origin']}/{after['epoch']}")
    shared = set(before["features"]) & set(after["features"])
    check(f"{label}: the chunk features come back", len(shared) >= max(1, int(0.8 * len(before["features"]))), f"{len(shared)} of {len(before['features'])}")


def serve_backend():
    """The long-walk backend (``--serve-backend``, started by ``Backend(shim=True)``): imports ``map_test`` exactly as its script does, adds ONE
    read-only route, ``GET /_smoke/window_stats``, to the app object in this process only, then serves it like map_test's own ``__main__``. The
    game's source and its app as shipped are unchanged; the route reports the window manager's void and wall counters, which no game route
    exposes. ``counter_generation`` counts calls to ``WindowManager.reset_void_counters`` in this process, so a reset is never read as 0 hits.
    Everything happens under the caller's ``__main__`` guard: the chunk pool's spawn workers re-import this file without building an engine."""
    sys.path.insert(0, str(ROOT / "at_the_beginning"))
    import uvicorn
    import map_test
    from harness import window_manager
    generation = [0]
    reset = window_manager.WindowManager.reset_void_counters

    def counted_reset(self):
        generation[0] += 1
        return reset(self)
    window_manager.WindowManager.reset_void_counters = counted_reset

    @map_test.app.get(SHIM_ROUTE)
    async def smoke_window_stats():
        engine = map_test.engine
        manager = getattr(engine, "_window", None)
        sessions = getattr(getattr(engine, "player_control", None), "sessions_by_controller", None) or {}
        controlled = sorted(str(s.get("target_id")) for s in sessions.values() if hasattr(s, "get") and s.get("target_kind") == "human")
        return {"world_epoch": getattr(engine, "world_epoch", None), "manager_id": id(manager) if manager is not None else None,
                "counter_generation": generation[0], "controlled": controlled, "stats": manager.stats() if manager is not None else None,
                "pid": os.getpid(), "source": SHIM_SOURCE}       # the backend interpreter, not the .venv launcher stub that spawned it

    uvicorn.run(map_test.app, host=map_test.LAUNCH_CONFIG.host, port=map_test.LAUNCH_CONFIG.port, access_log=False)
    return 0


def main():
    if sys.argv[1:] == ["--serve-backend"]:
        return serve_backend()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--keep", action="store_true", help="leave the data root in place")
    parser.add_argument('--long-distance', type=float, help='walk at least 5000 units east and return; preserve short default when absent')
    parser.add_argument('--walk-seconds', type=float, default=1800, help='total long-walk deadline, seconds')
    parser.add_argument('--evidence', type=Path, help='structured long-walk evidence JSON (retained outside temporary data root)')
    args = parser.parse_args()
    if args.long_distance is not None and (not math.isfinite(args.long_distance) or args.long_distance < 5000):
        parser.error('--long-distance must be finite and at least 5000')
    if not math.isfinite(args.walk_seconds) or args.walk_seconds <= 0:
        parser.error('--walk-seconds must be finite and positive')
    data_root = ROOT / ".runtime" / f"smoke-window-{uuid.uuid4().hex[:8]}"
    data_root.mkdir(parents=True)
    print(f"data root {data_root}", flush=True)
    out = {}
    b = Backend(args.port, data_root, FLAGS)
    try:
        b.start()
        reply = b.post("/session/new", {"name": "window-smoke"})
        check("/session/new starts a world under the four flags", reply.status_code == 200, f"{reply.status_code} {reply.text[:120]}")
        phase_one(b, out)
        save_id = phase_save(b, out)
        if save_id:
            before = out["facts"]
            cont = b.post("/session/continue", {"save_id": save_id})
            check("/session/continue in the same process succeeds", cont.status_code == 200, f"{cont.status_code} {cont.text[:160]}")
            time.sleep(2.0)
            wait_for_integration(b, 60.0, want=max(1, len(before["features"]) // 2))
            same_window("same-process continue", before, window_facts(b))
        b.stop()
        b = Backend(args.port, data_root, FLAGS)
        b.start()
        if save_id:
            cont = b.post("/session/continue", {"save_id": save_id})
            check("/session/continue after a backend restart succeeds", cont.status_code == 200, f"{cont.status_code} {cont.text[:160]}")
            time.sleep(2.0)
            wait_for_integration(b, 90.0, want=max(1, len(out["facts"]["features"]) // 2))
            same_window("restart continue", out["facts"], window_facts(b))
        b.stop()
        plain_flags = {k: v for k, v in FLAGS.items() if k == "EDEN_CHUNK_ROUTES"}
        b = Backend(args.port, data_root, plain_flags)
        b.start()
        if save_id:
            refused = b.post("/session/continue", {"save_id": save_id})
            check("a session without the window flags refuses the format 3 save with the approved text", refused.status_code == 400 and REFUSAL_START in refused.text,
                  f"{refused.status_code} {refused.text[:200]}")
            check("the refusal leaves the save listed and unchanged", any((s.get("save_id") or s.get("id")) == save_id for s in b.get("/session").json().get("saves", [])))
        b.stop()
        b = Backend(args.port, data_root, {**FLAGS, "EDEN_WINDOW_DORMANCY": "1"}, shim=args.long_distance is not None)
        b.start()
        b.post("/session/new", {"name": "walk"})
        time.sleep(3.0)
        if args.long_distance is None:
            phase_walk(b)
        else:
            evidence = {'command': [sys.executable, *sys.argv], 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                        'working_tree_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--binary'], cwd=ROOT)).hexdigest(),
                        'data_root': str(data_root)}
            destination = args.evidence or ROOT / 'coordination_evidence' / f'long-walk-{int(time.time())}.json'
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                phase_long_walk(b, args.long_distance, args.walk_seconds, evidence)
            finally:
                destination.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
                print(f'long-walk evidence {destination}', flush=True)
        time.sleep(2.0)
        exited, kids, alive = b.stop_gracefully()
        check("a normal stop ends the backend", exited)
        check("the chunk pool has workers to stop", len(kids) >= 1, str(kids))
        check("a normal stop leaves no chunk worker running", not alive, f"still alive: {alive}")
    finally:
        b.stop()
        if not args.keep:
            import shutil
            shutil.rmtree(data_root, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks passed", flush=True)
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
