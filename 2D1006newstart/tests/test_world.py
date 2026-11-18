from pathlib import Path
import math
from contextlib import contextmanager
import uuid
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from world import World, TILE, WIDTH

TEST_TEMP = Path(__file__).resolve().parent / '.tmp'
assert TEST_TEMP.resolve().is_relative_to(Path(__file__).resolve().parents[1])
TEST_TEMP.mkdir(exist_ok=True)


@contextmanager
def test_directory():
    # Python 3.13 TemporaryDirectory applies owner-only Windows ACLs that exclude
    # the Codex sandbox identity. A normal workspace directory inherits its ACL.
    path = TEST_TEMP / str(uuid.uuid4())
    assert path.resolve().is_relative_to(TEST_TEMP.resolve())
    path.mkdir()
    try:
        yield path
    finally:
        for name in ('world.json', 'world.tmp'):
            (path / name).unlink(missing_ok=True)
        path.rmdir()


class WorldTests(unittest.TestCase):
    def approach(self, world, entity_id):
        entity = next(e for e in world.entities if e.id == entity_id)
        # Find an unobstructed point at which this is the selected interaction.
        for radius in (55, 70, 85):
            for angle in range(0, 360, 15):
                x = entity.x + radius*math.cos(math.radians(angle))
                y = entity.y + radius*math.sin(math.radians(angle))
                if not world.blocked(x, y):
                    world.player_x, world.player_y = x, y
                    if world.nearest() is entity:
                        return entity
        self.fail(f'No accessible interaction point for {entity_id}')

    def test_deterministic_and_spawn_clear(self):
        a, b = World(), World()
        self.assertEqual(a.entities, b.entities)
        self.assertFalse(a.blocked(a.player_x, a.player_y))

    def test_diagonal_motion_has_same_speed(self):
        a, b = World(), World()
        start = a.player_x, a.player_y
        a.move(1, 0, 0.05)
        b.move(1, 1, 0.05)
        self.assertAlmostEqual(math.dist(start, (a.player_x, a.player_y)),
                               math.dist(start, (b.player_x, b.player_y)))

    def test_water_and_cottage_collision(self):
        w = World()
        self.assertTrue(w.blocked(WIDTH-30, 19*TILE))
        house = next(e for e in w.entities if e.id == 'cottage_1')
        self.assertTrue(w.blocked(house.x, house.y-30))
        w.player_x, w.player_y = house.x, house.y+24
        for _ in range(20):
            w.move(0, -1, 0.1)
        self.assertGreaterEqual(w.player_y, house.y+10)

    def test_complete_task_and_no_duplicate_reward(self):
        w = World()
        self.approach(w, 'mira')
        w.interact()
        self.assertTrue(w.quest_started)
        self.approach(w, 'fire')
        w.interact()
        self.assertFalse(w.quest_done)
        self.approach(w, 'oak_near')
        for _ in range(3):
            w.interact()
        self.approach(w, 'rock_near')
        for _ in range(2):
            w.interact()
        self.approach(w, 'fire')
        w.interact()
        self.assertTrue(w.quest_done)
        self.assertEqual(w.inventory['wood'], 0)
        self.assertEqual(w.inventory['stone'], 0)
        w.interact()
        self.assertEqual(w.inventory['wood'], 0)

    def test_depletion_loot_and_eating(self):
        w = World()
        self.approach(w, 'berry_near')
        for _ in range(8):
            w.interact()
        self.assertEqual(w.inventory['berries'], 4)
        w.hunger = 50
        w.eat()
        self.assertEqual(w.hunger, 75)
        self.assertEqual(w.inventory['berries'], 3)
        self.approach(w, 'chest')
        w.interact()
        w.interact()
        self.assertEqual(w.inventory['berries'], 5)

    def test_save_roundtrip_including_depletion(self):
        w = World()
        self.approach(w, 'berry_near')
        w.interact()
        w.update(15)
        with test_directory() as folder:
            path = Path(folder)/'world.json'
            w.save(path)
            loaded = World.load(path)
        self.assertEqual(loaded.inventory, w.inventory)
        self.assertEqual(loaded.hunger, w.hunger)
        self.assertEqual(loaded.elapsed, w.elapsed)
        self.assertEqual((loaded.player_x, loaded.player_y), (w.player_x, w.player_y))
        self.assertEqual([e.stock for e in loaded.entities], [e.stock for e in w.entities])

    def test_reject_invalid_saved_position(self):
        import json
        with test_directory() as folder:
            path = Path(folder)/'world.json'
            World().save(path)
            data = json.loads(path.read_text())
            data['player'] = [float('nan'), 0]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                World.load(path)


if __name__ == '__main__':
    unittest.main()
