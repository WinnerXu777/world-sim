"""Small deterministic playable slice, independent of rendering and Eden saves."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import random

TILE = 48
COLS, ROWS = 52, 38
WIDTH, HEIGHT = COLS * TILE, ROWS * TILE
SPAWN = (21.5 * TILE, 19.5 * TILE)


@dataclass
class Entity:
    id: str
    kind: str
    x: float
    y: float
    label: str = ''
    radius: float = 0
    stock: int = 0


class World:
    def __init__(self, seed=1006):
        self.seed = seed
        self.player_x, self.player_y = SPAWN
        self.facing = 'south'
        self.inventory = {'wood': 0, 'stone': 0, 'berries': 0}
        self.health = 100
        self.hunger = 100.0
        self.elapsed = 0.0
        self.entities: list[Entity] = []
        self.events = ['Welcome to Eden. Find Mira by the campfire.']
        self.quest_done = False
        self.quest_started = False
        self.talking = False
        self._populate()

    def tile(self, col, row):
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return 'water'
        shore = 42 + round(2 * math.sin(row * 0.22))
        if col >= shore:
            return 'water'
        if col == shore - 1:
            return 'sand'
        if 18 <= row <= 20 or 20 <= col <= 22 and 9 <= row <= 30:
            return 'path'
        return 'grass'

    def _populate(self):
        self.entities = [
            Entity('cottage_1', 'cottage', 15*TILE, 16*TILE, 'Mira\'s cottage', 95),
            Entity('cottage_2', 'cottage_blue', 28*TILE, 16*TILE, 'Storehouse', 95),
            Entity('well', 'well', 24*TILE, 23*TILE, 'Village well', 24),
            Entity('fire', 'campfire', 19*TILE, 23*TILE, 'Campfire'),
            Entity('mira', 'resident', 20.5*TILE, 23*TILE, 'Mira'),
            Entity('chest', 'crate', 27*TILE, 17*TILE, 'Supply crate', 15, 1),
            Entity('cart', 'cart', 16*TILE, 21.8*TILE, 'Handcart', 30),
            Entity('barrel', 'barrel', 29*TILE, 17*TILE, 'Barrel', 15),
            Entity('berry_near', 'berry_bush', 24*TILE, 21.7*TILE, 'Berry bush', 14, 4),
            Entity('rock_near', 'boulders', 25.8*TILE, 25*TILE, 'Stone outcrop', 25, 4),
            Entity('oak_near', 'oak', 17*TILE, 25.5*TILE, 'Oak tree', 18, 4),
        ]
        rng = random.Random(self.seed)
        for i in range(95):
            x, y = rng.uniform(2*TILE, 39*TILE), rng.uniform(3*TILE, 35*TILE)
            # Keep the village, spawn, and all roads clear.
            if 12*TILE < x < 32*TILE and 10*TILE < y < 28*TILE:
                continue
            if self.tile(int(x/TILE), int(y/TILE)) != 'grass':
                continue
            kind = rng.choices(['oak', 'pine', 'boulders', 'berry_bush'], [5, 4, 2, 2])[0]
            radius = {'oak': 18, 'pine': 17, 'boulders': 25, 'berry_bush': 14}[kind]
            self.entities.append(Entity(f'nature_{i}', kind, x, y, kind.replace('_', ' ').title(), radius, 4))

    def blocked(self, x, y):
        if not (18 <= x <= WIDTH - 18 and 18 <= y <= HEIGHT - 18):
            return True
        for dx, dy in ((-10, -10), (10, -10), (-10, 10), (10, 10)):
            if self.tile(int((x+dx)/TILE), int((y+dy)/TILE)) == 'water':
                return True
        for entity in self.entities:
            if entity.kind.startswith('cottage'):
                if abs(x - entity.x) < 112 and entity.y - 124 < y < entity.y + 10:
                    return True
            elif entity.radius and math.hypot(x-entity.x, y-entity.y) < entity.radius + 10:
                return True
        return False

    def move(self, dx, dy, dt, sprint=False):
        length = math.hypot(dx, dy)
        if not length:
            return False
        dx, dy = dx/length, dy/length
        if abs(dx) > abs(dy):
            self.facing = 'east' if dx > 0 else 'west'
        else:
            self.facing = 'south' if dy > 0 else 'north'
        distance = (220 if sprint else 145) * min(max(dt, 0), 0.1)
        start = self.player_x, self.player_y
        # Small movement steps prevent tunnelling even during a slow frame.
        steps = max(1, math.ceil(distance / 6))
        for _ in range(steps):
            nx = self.player_x + dx * distance/steps
            if not self.blocked(nx, self.player_y):
                self.player_x = nx
            ny = self.player_y + dy * distance/steps
            if not self.blocked(self.player_x, ny):
                self.player_y = ny
        return start != (self.player_x, self.player_y)

    def nearest(self):
        candidates = [e for e in self.entities if e.kind not in ('cottage', 'cottage_blue', 'cart', 'barrel')]
        if not candidates:
            return None
        entity = min(candidates, key=lambda e: math.hypot(self.player_x-e.x, self.player_y-e.y))
        return entity if math.hypot(self.player_x-entity.x, self.player_y-entity.y) <= 94 else None

    def say(self, text):
        self.events.append(text)
        self.events = self.events[-12:]
        return text

    def interact(self):
        entity = self.nearest()
        if entity is None:
            return self.say('Move closer to a person, resource, or the campfire.')
        if entity.kind == 'resident':
            self.talking = True
            self.quest_started = True
            if self.quest_done:
                return self.say('Mira: The fire is ready. This place is starting to feel like home.')
            return self.say('Mira: Bring 3 wood and 2 stone to the campfire. Trees and rocks are nearby.')
        resource = {'oak': 'wood', 'pine': 'wood', 'boulders': 'stone', 'berry_bush': 'berries'}.get(entity.kind)
        if resource:
            if entity.stock <= 0:
                return self.say('This resource is depleted for now.')
            entity.stock -= 1
            self.inventory[resource] += 1
            return self.say(f'Gathered 1 {resource}.')
        if entity.kind == 'well':
            self.health = 100
            return self.say('Fresh well water. Health restored.')
        if entity.kind == 'crate':
            if not entity.stock:
                return self.say('The supply crate is empty.')
            entity.stock = 0
            self.inventory['berries'] += 2
            return self.say('Found 2 berries in the supply crate.')
        if entity.kind == 'campfire':
            if self.quest_done:
                return self.say('The campfire is warm. First settlement task complete.')
            if self.inventory['wood'] < 3 or self.inventory['stone'] < 2:
                return self.say('To prepare the campfire: gather 3 wood and 2 stone.')
            self.inventory['wood'] -= 3
            self.inventory['stone'] -= 2
            self.quest_done = True
            return self.say('Campfire prepared. Mira: Thank you! Our first evening is safe.')
        return None

    def eat(self):
        if self.inventory['berries'] < 1:
            return self.say('Gather berries from a bush, or check the supply crate.')
        self.inventory['berries'] -= 1
        self.hunger = min(100.0, self.hunger + 25)
        return self.say('Ate berries. Hunger restored.')

    def update(self, dt):
        self.elapsed += max(0, dt)
        self.hunger = max(0, self.hunger - max(0, dt)*0.035)

    def save(self, path: Path):
        payload = {'version': 1, 'seed': self.seed, 'player': [self.player_x, self.player_y],
                   'facing': self.facing, 'inventory': self.inventory, 'health': self.health,
                   'hunger': self.hunger, 'elapsed': self.elapsed, 'quest_done': self.quest_done,
                   'quest_started': self.quest_started,
                   'stock': {e.id: e.stock for e in self.entities}}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise ValueError('Unsupported save version')
        world = cls(int(data['seed']))
        x, y = map(float, data['player'])
        if not math.isfinite(x) or not math.isfinite(y) or world.blocked(x, y):
            raise ValueError('Saved player position is invalid')
        world.player_x, world.player_y = x, y
        world.facing = data.get('facing', 'south')
        if world.facing not in ('south', 'west', 'east', 'north'):
            raise ValueError('Saved facing is invalid')
        for key in world.inventory:
            world.inventory[key] = max(0, int(data['inventory'].get(key, 0)))
        world.health = max(0, min(100, int(data['health'])))
        for attr in ('hunger', 'elapsed'):
            number = float(data[attr])
            if not math.isfinite(number):
                raise ValueError('Non-finite save value')
            setattr(world, attr, max(0, min(100, number)) if attr == 'hunger' else max(0, number))
        world.quest_done = bool(data.get('quest_done'))
        world.quest_started = bool(data.get('quest_started'))
        for entity in world.entities:
            entity.stock = max(0, min(4, int(data.get('stock', {}).get(entity.id, entity.stock))))
        world.say('Local world loaded.')
        return world
