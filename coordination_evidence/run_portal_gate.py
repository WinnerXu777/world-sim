"""Run the authorised real-backend portal check under an owned NORMAL lock."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
lock = root / '.runtime/fullsuite.lock'
token = f'NORMAL root-portal pid={os.getpid()} eta=4min start={time.strftime("%Y-%m-%dT%H:%M:%S")}'
paths = ['at_the_beginning/map_test.py', 'godot_client_2d/tools/run_live_tests.py',
         'godot_client_2d/tests/test_live_portal_spaces.gd',
         'godot_client_2d/scripts/game/game.gd', 'godot_client_2d/scripts/game/actor_view.gd',
         'godot_client_2d/scripts/net/frame_ingest.gd', 'godot_client_2d/data/import_lock.json',
         'godot_client_2d/data/production_index.json']
def hashes():
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
try:
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(token)
except FileExistsError:
    print('LOCK_BUSY: ' + lock.read_text(encoding='utf-8'))
    sys.exit(3)
try:
    before = hashes()
    command = [str(root / '.venv/Scripts/python.exe'), 'godot_client_2d/tools/run_live_tests.py',
               '--port', '8047', 'portal_spaces']
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDEN_')}
    env['EDEN_GODOT'] = r'C:\Users\Rita\Downloads\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64_console.exe'
    start = time.monotonic()
    with (root / 'coordination_evidence/portal_spaces_1010.log').open('w', encoding='utf-8') as output:
        result = subprocess.run(command, cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
    after = hashes()
    evidence = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                'command': command, 'exit_code': result.returncode, 'seconds': round(time.monotonic() - start, 2),
                'source_before': before, 'source_after': after, 'source_changed': before != after,
                'scope': 'Real backend portal-spaces check only; no complete R5 or Gate F claim'}
    (root / 'coordination_evidence/portal_spaces_1010_result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'exit_code': result.returncode, 'source_changed': before != after}))
    sys.exit(result.returncode or (2 if before != after else 0))
finally:
    if lock.exists() and lock.read_text(encoding='utf-8') == token:
        lock.unlink()
