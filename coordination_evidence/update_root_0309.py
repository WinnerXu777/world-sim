from pathlib import Path
from datetime import datetime, timezone
import json

directory = Path(__file__).resolve().parent
now = datetime.now(timezone.utc).isoformat()
queue_path = directory / '1009_agy_queue.json'
queue = json.loads(queue_path.read_text(encoding='utf-8-sig'))
queue['updated_at'] = now
for item in queue['assignments']:
    if item['id'] == 'disaster-power-ports':
        item['state'] = 'root_rejected_23_tests_3fail_3error_agy_repair_running'
        item['active_assignment'] = 'agy_1010_disaster_fix'
    if item['id'] in ('settlement-construction', 'agy_1010_settlement_construction'):
        item['state'] = 'root_rejected_41_tests_33error_1fail_mock_engine_gap_agy_repair_running'
        item['active_assignment'] = 'agy_1010_construction_fix'
for assignment in ('agy_1010_disaster_fix', 'agy_1010_construction_fix'):
    if not any(item['id'] == assignment for item in queue['assignments']):
        queue['assignments'].append({'id': assignment, 'items': ['R6.8' if 'disaster' in assignment else 'R6.4'],
                                     'state': 'agy_running', 'status_file': f'coordination_evidence/{assignment}_status.json'})
queue_path.write_text(json.dumps(queue, indent=2) + '\n', encoding='utf-8')
notes = {
    'agy_1010_disaster_ports_report.md': 'Root rejects completion claim: initial nonexistent oracle imports corrected to actual function aliases;23tests run with3FAIL3ERROR. Compact oracle tensor layouts invalid; actual space-isolation failure unresolved. Terrain tensor-only mutation lacks required production geometry cache synchronization, so not a faithful complete live port. Repair assigned AGY disaster_fix; no whole R6.8 acceptance.',
    'agy_1010_settlement_construction_report.md': 'Root rejects integration/completion claims:41tests run with33ERROR1FAIL. Production source calls nonexistent registry.records/projects and incorrectly unpacks list_settlements records. Test IsolatedTestEngine is a mock, not actual map_test.Engine; original required real-engine integration remains unproved. Repair assigned AGY construction_fix without changing actual registry APIs. No whole R6.4 acceptance.'
}
for filename, note in notes.items():
    with (directory / filename).open('a', encoding='utf-8') as stream:
        stream.write(f'\nRoot {now}: {note}\n')
with (directory / '1010_orchestration_log.md').open('a', encoding='utf-8') as stream:
    stream.write(f'\nRoot {now}: Actual root checks reject disaster23tests3FAIL3ERROR and construction41tests33ERROR1FAIL; grounded repairs AGY-first livePID468 and20660. No narrow green tests or report COMPETE words accepted over actual production/API gaps. Latestquota03:09weekly71.40%/fivehour3.46%remaining, not yet exhausted; no further AGY dispatch until active work/quota resolve. R0.1 session88503 actual first2strictgoldensPASS; samelivehandle continues. OPEN human decisions unchanged.\n')
