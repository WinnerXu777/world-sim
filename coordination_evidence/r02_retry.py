"""Retry the retained R0.2 snapshot after sandbox runtime creation failure."""
import json
import os
import subprocess
import time
import r02_verify as v

data = json.loads((v.OUT / 'codex_1010_r02_snapshot.json').read_text())
snap = v.Path(data['snapshot'])
assert v.digest(v.Path(data['archive'])) == data['archive_sha256']
for name, info in {**data['overlays'], **data['support_files']}.items():
    if info.get('deleted'):
        assert not (snap / name).exists(), name
    else:
        assert v.digest(snap / name) == info['sha256'], name
handle = os.open(v.LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
with os.fdopen(handle, 'w') as stream:
    json.dump({'mode': 'NORMAL', 'owner': v.TOKEN, 'pid': os.getpid(), 'started': v.now(),
               'phase': 'R0.2 immutable snapshot retry', 'eta': '10 minutes'}, stream)
try:
    env = {k: val for k, val in os.environ.items() if not k.startswith('EDEN_')}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    runs = []
    for mode in data['strict_modes']:
        log = v.OUT / f'codex_1010_r02_retry_{mode}.log'
        trace = v.OUT / f'codex_1010_r02_retry_{mode}.json'
        command = [str(v.PYTHON), 'tools/golden_trace.py', '--check', '--strict']
        if mode != 'default':
            command.append('--' + mode)
        command += ['--out', str(trace)]
        v.status('retry_running', mode=mode, snapshot=str(snap))
        start = time.monotonic()
        with log.open('w', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=snap, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=1200)
        runs.append(dict(mode=mode, exit_code=result.returncode, seconds=round(time.monotonic()-start, 1),
                         command=command, log=str(log), trace=str(trace),
                         trace_sha256=v.digest(trace) if trace.exists() else None))
        data['retry_results'] = runs
        (v.OUT / 'codex_1010_r02_snapshot.json').write_text(json.dumps(data, indent=2, sort_keys=True))
    failed = any(r['exit_code'] for r in runs)
    with v.REPORT.open('a', encoding='utf-8') as stream:
        stream.write('\n## Runtime-access retry\n\nInitial failures were Windows PermissionError creating ResidentAgents, before any golden comparison. Original logs are preserved. Retried the same hash-verified immutable snapshot with filesystem access.\n\n')
        stream.write('Status: ' + ('FAIL; inspect retry logs.' if failed else 'PASS for this stage snapshot only; no final at-HEAD/full-suite claim.') + '\n\n')
        for r in runs:
            stream.write(f"- {r['mode']}: exit {r['exit_code']}, {r['seconds']} seconds; {r['log']}\n")
    v.status('retry_failed' if failed else 'complete', results=runs, snapshot_sha256=data['snapshot_sha256'])
finally:
    if v.LOCK.exists() and json.loads(v.LOCK.read_text()).get('owner') == v.TOKEN:
        v.LOCK.unlink()
