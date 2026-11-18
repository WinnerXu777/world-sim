from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess

directory = Path(__file__).resolve().parent
now = datetime.now(timezone.utc).isoformat()
path = directory / '1009_agy_queue.json'
queue = json.loads(path.read_text(encoding='utf-8-sig'))
queue['current_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=directory.parent, text=True).strip()
queue['updated_at'] = now
for item in queue['assignments']:
    if item['id'] == 'agy_1010_void_secondfix':
        item['state'] = 'terminal_18_tests_pass_root_fixture_corrections'
    elif item['id'] in ('agy_1010_aux_foundation', 'agy_1010_aux_fix'):
        item['state'] = '27_tests_pass_repaired_pure_storage_foundation_production_integration_pending'
    elif item['id'] == 'calendar-flag-sensitive-tests':
        item['verification'] = 'Calendar19passbothflags, emotion25/care/rates10/consumers3/wire4/scenario7pass; market3of4pass with inherited EMOTION-C5 long-calendar out_of_stock exception documented.'
    elif 's3' in item['id']:
        item['state'] = 'committed_scoped_verified_74fc2ea_14_tests_8_strict_goldens'
for item in ({'id': 'agy_1010_retaliate', 'items': ['R6.1'], 'state': 'agy_running',
              'status_file': 'coordination_evidence/agy_1010_retaliate_status.json',
              'scope': 'Existing attack task with factual same-target harm/goal justification through actual affordance/runner, opt-in; other missing verbs pending'},
             {'id': 'r01-committed-head-gate', 'items': ['R0.1'], 'state': 'running',
              'pid': 33068, 'session_id': 88503,
              'evidence': 'coordination_evidence/r01_committed_gate_result.json',
              'scope': 'Immutable committed74fc2ea archive, fourstrictgoldens then fullsuite, no uncommitted overlay'}):
    if not any(existing['id'] == item['id'] for existing in queue['assignments']):
        queue['assignments'].append(item)
path.write_text(json.dumps(queue, indent=2) + '\n', encoding='utf-8')
with (directory / '1010_orchestration_log.md').open('a', encoding='utf-8') as stream:
    stream.write(f'\nRoot {now}: pathspec-only local74fc2ea records verified scaledS3 and matching design/ledger/roadmap; no peer source or push. AGY-first R6.1 retaliate assigned and livePID23052; latest native quota03:06UTC weekly72.60%/fivehour10.65%remaining, not exhausted. R0.1 exact committed-HEAD clean archive gate startedsession88503/PID33068, atomicNORMALlock eta45min, fourstrictgoldens then fullsuite, excludes uncommitted peers. Source/code sharing remains within TorontoOct10 authority, OPENdecisions unchanged. Prior goal turn made concrete state/evidence progress.\n')
