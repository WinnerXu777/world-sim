"""Strict goldens then full suite on an immutable committed HEAD archive."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
import uuid

root = Path(__file__).resolve().parents[1]
lock = root / '.runtime/fullsuite.lock'
token = f'NORMAL root-r01 pid={os.getpid()} eta=45min start={time.strftime("%Y-%m-%dT%H:%M:%S")}'
try:
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(token)
except FileExistsError:
    print('LOCK_BUSY: ' + lock.read_text(encoding='utf-8'), flush=True)
    raise SystemExit(3)
try:
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dest = root / '.tmp' / ('r01-' + uuid.uuid4().hex[:8])
    dest.mkdir(parents=True)
    archive = dest / 'head.zip'
    subprocess.run(['git', 'archive', head, '--format=zip', '-o', str(archive)], cwd=root, check=True)
    shutil.unpack_archive(archive, dest)
    for relative in ('myassets', 'tests/fixtures/maps/sprites'):
        source = root / relative
        if source.exists():
            shutil.copytree(source, dest / relative, dirs_exist_ok=True)
    scratch = dest / 'temp'
    scratch.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith('EDEN_')}
    env.update(TEMP=str(scratch), TMP=str(scratch))
    python = str(root / '.venv/Scripts/python.exe')
    manifest = {'base': head, 'snapshot': str(dest), 'overlay': [], 'checks': [],
                'scope': 'Committed HEAD archive only; excludes all uncommitted implementations. No timing or final combined implementation acceptance.'}
    result_path = root / 'coordination_evidence/r01_committed_gate_result.json'
    commands = [[python, 'tools/golden_trace.py', '--check', '--strict', *flags]
                for flags in ([], ['--resources'], ['--spaces'], ['--window-hook'])]
    commands.append([python, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'])
    with (root / 'coordination_evidence/r01_committed_gate.log').open('w', encoding='utf-8') as log:
        for command in commands:
            result_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'running': command, 'snapshot': str(dest)}), flush=True)
            log.write(json.dumps({'command': command}) + '\n')
            log.flush()
            started = time.monotonic()
            result = subprocess.run(command, cwd=dest, env=env, stdout=log, stderr=subprocess.STDOUT)
            check = {'command': command, 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 2)}
            manifest['checks'].append(check)
            result_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(check), flush=True)
            if result.returncode:
                manifest['complete'] = False
                result_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
                raise SystemExit(result.returncode)
    manifest['complete'] = True
    manifest['current_head_matches'] = head == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    result_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
finally:
    if lock.exists() and lock.read_text(encoding='utf-8') == token:
        lock.unlink()
