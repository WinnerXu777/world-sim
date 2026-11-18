"""Scoped roadmap dispatcher; quota checks do not use an LLM prompt."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import subprocess
from agy_usage import AGY, EVIDENCE, check_usage

parser = argparse.ArgumentParser()
parser.add_argument('--id', required=True)
parser.add_argument('--brief', required=True)
parser.add_argument('--items', nargs='+', required=True)
args = parser.parse_args()
if not args.id.replace('-', '').replace('_', '').isalnum():
    raise SystemExit('Invalid assignment id')
root = EVIDENCE.parent
brief_path = (root / args.brief).resolve()
if not brief_path.is_relative_to(EVIDENCE):
    raise SystemExit('Brief must be inside coordination_evidence')
prefix = EVIDENCE / args.id
status_path = Path(str(prefix) + '_status.json')

def status(state, **fields):
    status_path.write_text(json.dumps({
        'status': state, 'items': args.items, 'updated_at': datetime.now(timezone.utc).isoformat(),
        **fields}, indent=2), encoding='utf-8')

quota = check_usage()
if quota['exhausted']:
    status('quota_exhausted', next_owner='Codex')
    raise SystemExit(0)
command = [AGY, '-p', brief_path.read_text(encoding='utf-8'),
           '--model', 'gemini-3.1-pro-high', '--mode', 'accept-edits', '--sandbox',
           '--output-format', 'json', '--print-timeout', '30m']
worker_path = Path(str(prefix) + '_worker.json')
with worker_path.open('w', encoding='utf-8') as stdout, \
     Path(str(prefix) + '_stderr.log').open('w', encoding='utf-8') as stderr:
    process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr)
    status('running', pid=process.pid)
    code = process.wait()
    stdout.flush()
try:
    worker = json.loads(worker_path.read_text(encoding='utf-8'))
    substantive = worker.get('status') == 'SUCCESS' and bool(worker.get('response', '').strip())
    status('needs_verification' if code == 0 and substantive else 'failed', returncode=code,
           conversation_id=worker.get('conversation_id'), denied_actions=worker.get('denied_actions', []))
except Exception as error:
    status('failed', returncode=code, error=str(error))
try:
    check_usage()
except Exception as error:
    Path(str(prefix) + '_usage_error.txt').write_text(str(error), encoding='utf-8')
