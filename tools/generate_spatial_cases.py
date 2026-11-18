"""Generate deterministic cross-language sweep cases for the Godot parity check."""
import json
from pathlib import Path
import random
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "at_the_beginning"))
from systems.movement.spatial import slide

contract = {"version": 1, "actor_radius": .35, "bounds": [0, 0, 100, 100],
            "boxes": [{"min": [40, 20], "max": [60, 21]}]}
rng = random.Random(905)
pairs = [((50, 10), (50, 90)), ((50, 30), (50, 0)),
         ((50, 19.65), (55, 19.65)), ((39.65, 20), (50, 25))]
pairs += [(tuple(rng.uniform(0, 100) for _ in range(2)),
           tuple(rng.uniform(-20, 120) for _ in range(2))) for _ in range(500)]
cases = [{"start": start, "desired": desired, "expected": slide(start, desired, contract)}
         for start, desired in pairs]
output = root / ".tmp" / "implementation_0905" / "spatial_cases.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"contract": contract, "cases": cases}), encoding="utf-8")
print(output)
