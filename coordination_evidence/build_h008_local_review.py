"""Bind root's viewed static-local review to exact immutable source bytes."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
asset_root = root / 'myassets'
manifest = asset_root / 'h008_creatures/manifest.json'
raw = manifest.read_bytes()
data = json.loads(raw)
records = []
seen = set()
species_ids = {40, 41, 43, 45, 46, 47, 48, 49, 60, 65}
for item in data['assets']:
    ident = f"{item['id']}_{item['state']}_{item['direction']}"
    if item['id'] not in species_ids or item['state'] not in {'idle', 'dead'} or ident in seen:
        raise ValueError('Unexpected or duplicate unreviewed pose: ' + ident)
    seen.add(ident)
    relative = Path('h008_creatures') / item['display']
    source = (asset_root / relative).resolve()
    if not source.is_relative_to(asset_root.resolve()):
        raise ValueError('Image escapes asset root')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != item['display_sha256']:
        raise ValueError('Changed reviewed source: ' + ident)
    records.append({'id': ident, 'source_path': relative.as_posix(), 'sha256': digest})
if len(records) != 33:
    raise ValueError('The viewed selection contains exactly 33 poses')
selection = {'schema': 'local-static-review-v1', 'scope': 'local_static_evaluation',
             'reviewer': 'Codex root', 'review_date': '2026-10-10',
             'review_record': 'coordination_evidence/h008_local_static_review_1010.md',
             'sets': {'h008_creatures': {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                                       'assets': records}}}
output = root / 'coordination_evidence/h008_local_static_selection_1010.json'
output.write_text(json.dumps(selection, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'selected': len(records), 'output': str(output), 'canonical_modified': False}))
