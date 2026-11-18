"""Golden set for the generator: fixed (seed, cx, cy, pinned) cases and their sha256.

    .venv/Scripts/python.exe at_the_beginning/systems/worldgen/golden.py --write     # regenerate tests/golden/worldgen_*.json
    .venv/Scripts/python.exe at_the_beginning/systems/worldgen/golden.py --check     # compare with the committed files

Regenerate ONLY together with a GENERATOR_VERSION bump (spec.py); the drift test fails otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.worldgen import GENERATOR_VERSION, PinnedSet, generate_chunk, starter_village_area   # noqa: E402

GOLDEN_DIR = ROOT / "tests" / "golden"
HASHES_FILE = GOLDEN_DIR / "worldgen_hashes.json"
SAMPLE_FILE = GOLDEN_DIR / "worldgen_chunk_1008_2_0.json"      # one full chunk, readable and diffable
SAMPLE_CASE = ("village", 1008, 2, 0)

VILLAGE = PinnedSet([starter_village_area()])
SEEDS = (1008, 7, (1 << 40) + 5, -3)
COORDS = ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (-1, -1), (5, 3), (7, 0), (8, 0), (7, 7), (8, 8), (-9, 4), (31, -17), (1000, 1000), (-123456, 654321),
          (10 ** 6, -10 ** 6))


def cases():
    """Yield (label, seed, cx, cy, pinned) for every golden entry."""
    for seed in SEEDS:
        for cx, cy in COORDS:
            yield f"free/{seed}/{cx}/{cy}", seed, cx, cy, None
    for cx, cy in ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1), (-1, 0), (0, -1), (3, 2), (-2, -2), (5, 5)):
        yield f"village/1008/{cx}/{cy}", 1008, cx, cy, VILLAGE


def compute() -> dict:
    entries = {}
    for label, seed, cx, cy, pinned in cases():
        chunk = generate_chunk(seed, cx, cy, pinned)
        entries[label] = {"sha256": chunk.sha256, "bytes": len(chunk.payload)}
    return {"generator_version": GENERATOR_VERSION, "count": len(entries), "entries": entries}


def sample_bytes() -> bytes:
    _, seed, cx, cy = SAMPLE_CASE
    return generate_chunk(seed, cx, cy, VILLAGE).payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = compute()
    if args.write:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        HASHES_FILE.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        SAMPLE_FILE.write_bytes(sample_bytes())
        print(f"wrote {HASHES_FILE.name} ({result['count']} cases) and {SAMPLE_FILE.name}")
        return 0
    if args.check:
        committed = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
        changed = [k for k, v in result["entries"].items() if committed["entries"].get(k, {}).get("sha256") != v["sha256"]]
        print("golden OK" if not changed else f"golden DRIFT in {len(changed)} cases: {changed[:5]}")
        return 1 if changed else 0
    print(json.dumps(result, indent=1)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
