"""Write the creature contract (ids, names, sprite, frame, pivot, footprint, variants) as JSON for the asset side and the client.

Usage: ``python tools/export_creatures.py [path]`` (default: stdout). ``tests/fixtures/creatures_contract.json`` is the frozen copy the tests compare against."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from systems.creatures import table  # noqa: E402

text = json.dumps(table.export(), indent=1, sort_keys=False) + "\n"
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(text, encoding="utf-8", newline="\n")
else:
    sys.stdout.write(text)
