from pathlib import Path
import json
import subprocess
from datetime import datetime, timezone
from agy_usage import check_usage

root = Path(__file__).resolve().parents[1]
out = root / 'coordination_evidence'
brief = (out / 'agy_1010_client_brief.txt').read_text(encoding='utf-8')
quota = check_usage()
if quota['exhausted']:
    (out / 'agy_1010_client_status.json').write_text(json.dumps({
        'status': 'quota_exhausted', 'next_owner': 'Codex',
        'tasks': ['R5.1', 'R5.2', 'R5.4'],
        'checked_at': quota['checked_at']}, indent=2), encoding='utf-8')
    raise SystemExit(0)
command = [r'C:\Users\Rita\AppData\Local\agy\bin\agy.exe', '-p', brief,
           '--model', 'gemini-3.1-pro-high', '--mode', 'accept-edits', '--sandbox',
           '--output-format', 'json', '--print-timeout', '30m']
with (out / 'agy_1010_client_worker.json').open('w', encoding='utf-8') as stdout, \
     (out / 'agy_1010_client_stderr.log').open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr)
    (out / 'agy_1010_client_status.json').write_text(json.dumps({
        'status': 'running', 'pid': process.pid, 'model': 'gemini-3.1-pro-high',
        'checkpoint': 'b555adc', 'tasks': ['R5.1', 'R5.2', 'R5.4'],
        'started_at': datetime.now(timezone.utc).isoformat()}, indent=2), encoding='utf-8')
    code = process.wait()
    stdout.flush()
    try:
        worker = json.loads((out / 'agy_1010_client_worker.json').read_text(encoding='utf-8'))
        substantive = worker.get('status') == 'SUCCESS' and bool(worker.get('response', '').strip())
        terminal = 'needs_verification' if code == 0 and substantive else 'failed'
    except Exception:
        terminal = 'failed'
    (out / 'agy_1010_client_status.json').write_text(json.dumps({
        'status': terminal, 'returncode': code,
        'model': 'gemini-3.1-pro-high', 'checkpoint': 'b555adc',
        'tasks': ['R5.1', 'R5.2', 'R5.4'],
        'finished_at': datetime.now(timezone.utc).isoformat()}, indent=2), encoding='utf-8')
try:
    check_usage()
except Exception as error:
    (out / 'agy_1010_usage_error.txt').write_text(str(error), encoding='utf-8')
