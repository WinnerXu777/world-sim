"""Read AGY's native /usage report without sending a model prompt or source."""
from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess

AGY = r'C:\Users\Rita\AppData\Local\agy\bin\agy.exe'
EVIDENCE = Path(__file__).resolve().parent

def check_usage():
    isolated = EVIDENCE / 'agy_usage_probe'
    isolated.mkdir(exist_ok=True)
    result = subprocess.run(
        [AGY, '-p', '/usage', '--output-format', 'json', '--print-timeout', '30s'],
        cwd=isolated, capture_output=True, text=True, encoding='utf-8', timeout=45)
    if result.returncode != 0:
        raise RuntimeError('AGY usage check failed: ' + result.stderr[-1500:])
    report = json.loads(result.stdout)
    if report.get('status') != 'SUCCESS':
        raise RuntimeError('AGY usage did not succeed')
    groups = report.get('command', {}).get('data', {}).get('groups', [])
    gemini = next((group for group in groups if group['name'] == 'Gemini Models'), None)
    if not gemini or not gemini.get('buckets'):
        raise RuntimeError('No Gemini quota data: cannot safely infer remaining usage')
    fractions = [bucket['remaining_fraction'] for bucket in gemini['buckets']]
    if any(not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in fractions):
        raise RuntimeError('Invalid Gemini quota data')
    snapshot = {'checked_at': datetime.now(timezone.utc).isoformat(),
                'exhausted': any(value == 0 for value in fractions),
                'gemini': gemini, 'native_report': report}
    (EVIDENCE / 'agy_usage_latest.json').write_text(
        json.dumps(snapshot, indent=2), encoding='utf-8')
    with (EVIDENCE / 'agy_usage_history.jsonl').open('a', encoding='utf-8') as log:
        log.write(json.dumps(snapshot) + '\n')
    return snapshot

if __name__ == '__main__':
    status = check_usage()
    print(json.dumps({'checked_at': status['checked_at'], 'exhausted': status['exhausted'],
                      'buckets': status['gemini']['buckets']}, indent=2))
