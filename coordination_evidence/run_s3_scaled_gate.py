"""Immutable scoped S3 real-village strict golden gate, under an owned lock."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

root = Path(__file__).resolve().parents[1]
lock = root / '.runtime/fullsuite.lock'
token = f'NORMAL root-s3-scaled pid={os.getpid()} eta=8min start={time.strftime("%Y-%m-%dT%H:%M:%S")}'
try:
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(token)
except FileExistsError:
    print('LOCK_BUSY: ' + lock.read_text(encoding='utf-8'))
    raise SystemExit(3)
try:
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dest = root / '.tmp' / ('s3-' + uuid.uuid4().hex[:8])
    dest.mkdir(parents=True)
    archive = dest / 'head.zip'
    subprocess.run(['git', 'archive', head, '--format=zip', '-o', str(archive)], cwd=root, check=True)
    shutil.unpack_archive(archive, dest)
    owned = ['at_the_beginning/harness/needs.py', 'tests/test_harness_needs.py']
    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in owned}
    for p in owned:
        shutil.copy2(root / p, dest / p)
    snapshot_hashes = {p: hashlib.sha256((dest / p).read_bytes()).hexdigest() for p in owned}
    after = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in owned}
    if before != snapshot_hashes or before != after:
        raise RuntimeError('Owned source changed while taking snapshot')
    for p in ('myassets', 'tests/fixtures/maps/sprites'):
        if (root / p).exists():
            shutil.copytree(root / p, dest / p, dirs_exist_ok=True)
    scratch = dest / 'temp'
    scratch.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDEN_')}
    env.update(TEMP=str(scratch), TMP=str(scratch))
    py = str(root / '.venv/Scripts/python.exe')
    manifest = {'base': head, 'snapshot': str(dest), 'source_sha256': snapshot_hashes,
                'scope': 'Current committed base plus S3 owned files only; excludes unrelated uncommitted peers, no full integration or timing claim', 'checks': []}
    manifest_path = root / 'coordination_evidence/s3_scaled_gate_result.json'
    with (root / 'coordination_evidence/s3_scaled_gate.log').open('w', encoding='utf-8') as log:
        for mode in ('off', 'on'):
            run_env = dict(env)
            if mode == 'on':
                run_env.update(EDEN_HARNESS='1', EDEN_HARNESS_NEEDS='1')
            for flags in ([], ['--resources'], ['--spaces'], ['--window-hook']):
                command = [py, 'tools/golden_trace.py', '--check', '--strict', *flags]
                log.write(json.dumps({'mode': mode, 'command': command}) + '\n')
                log.flush()
                start = time.monotonic()
                result = subprocess.run(command, cwd=dest, env=run_env, stdout=log, stderr=subprocess.STDOUT)
                check = {'mode': mode, 'flags': flags, 'exit_code': result.returncode, 'seconds': round(time.monotonic() - start, 2)}
                manifest['checks'].append(check)
                manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
                print(json.dumps(check), flush=True)
                if result.returncode:
                    raise SystemExit(result.returncode)
    manifest['complete'] = True
    manifest['live_source_unchanged'] = snapshot_hashes == {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in owned}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
finally:
    if lock.exists() and lock.read_text(encoding='utf-8') == token:
        lock.unlink()
