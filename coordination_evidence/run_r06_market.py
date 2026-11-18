"""Run the pending long-calendar market checks on the verified economy snapshot."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
snapshot = root / '.tmp/r63_fixed_goldens'
manifest = json.loads((root / 'coordination_evidence/r63_fixed_goldens_manifest.json').read_text(encoding='utf-8'))
if Path(manifest['archive']).resolve() != snapshot.resolve():
    raise SystemExit('Unexpected snapshot path')
for rel, digest in manifest['source_sha256'].items():
    if hashlib.sha256((snapshot / rel).read_bytes()).hexdigest() != digest:
        raise SystemExit('Snapshot no longer matches economy manifest: ' + rel)
lock = root / '.runtime/fullsuite.lock'
token = f'NORMAL root-r06-market pid={os.getpid()} eta=6min start={time.strftime("%Y-%m-%dT%H:%M:%S")}'
try:
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(token)
except FileExistsError:
    print('LOCK_BUSY: ' + lock.read_text(encoding='utf-8'))
    raise SystemExit(3)
try:
    paths = ['tests/test_market_ladder.py', 'model_server/s1_family_farm.py',
             'at_the_beginning/harness/calendar.py', 'at_the_beginning/instincts_and_tools.py',
             'at_the_beginning/map_test.py']
    def hashes():
        return {p: hashlib.sha256((snapshot / p).read_bytes()).hexdigest() for p in paths}
    before = hashes()
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDEN_')}
    scratch = root / '.tmp/r06_market_temp'
    scratch.mkdir(exist_ok=True)
    env.update(EDEN_CALENDAR='1', TEMP=str(scratch), TMP=str(scratch))
    command = [str(root / '.venv/Scripts/python.exe'), '-m', 'unittest', 'discover',
               '-s', 'tests', '-p', 'test_market_ladder.py', '-v']
    start = time.monotonic()
    with (root / 'coordination_evidence/r06_market.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=snapshot, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    after = hashes()
    evidence = {'base': manifest['base'], 'snapshot': str(snapshot), 'command': command,
                'EDEN_CALENDAR': '1', 'exit_code': result.returncode,
                'seconds': round(time.monotonic() - start, 2), 'source_before': before,
                'source_after': after, 'snapshot_changed': before != after,
                'scope': 'R0.6 market scenario on the immutable economy overlay snapshot; excludes later peer edits, not current HEAD integration/full suite'}
    (root / 'coordination_evidence/r06_market_result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'exit_code': result.returncode, 'snapshot_changed': before != after}))
    raise SystemExit(result.returncode or (2 if before != after else 0))
finally:
    if lock.exists() and lock.read_text(encoding='utf-8') == token:
        lock.unlink()
