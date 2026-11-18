"""Coherent current authored village fixture, including every declared portal target."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / 'world_data/maps2d'
MAP_NAMES = ('starter_village', 'smith_interior', 'village_lodge_interior', 'west_cottage_interior')
MAP_FILES = tuple(MAP_DIR / (name + '.json') for name in MAP_NAMES)
ORIGINS = {'smith_interior': [620, 0], 'village_lodge_interior': [620, 400], 'west_cottage_interior': [960, 160]}


def village_environment(village=MAP_FILES[0], smith=MAP_FILES[1], origins=None):
    placement = dict(ORIGINS)
    if origins is not None:
        placement.update(json.loads(origins) if isinstance(origins, str) else origins)
    return {'EDEN_MAP_FILES': os.pathsep.join(map(str, (village, smith, *MAP_FILES[2:]))),
            'EDEN_MAP_ORIGINS': json.dumps(placement)}


def load_village_maps(**kwargs):
    from systems.movement.map_contract import load_from_environment
    return load_from_environment(village_environment(**kwargs))
