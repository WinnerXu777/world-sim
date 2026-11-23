import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'at_the_beginning'))
from harness import calendar, calendar_wire, powers
from harness.world import World
from systems.nature import weather
from systems.schedule import resolver


class CalendarWiringTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '1', 'EDEN_CALENDAR': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.world = World.synthetic()
        self.other = World.synthetic()
        self.registry = powers.build_registry()

    def power(self, name, value):
        self.assertTrue(powers.call(self.world, name, {'value': value}, registry=self.registry).ok)

    def test_season_weather_wire_and_clear(self):
        self.power('set_season', 'winter')
        self.assertEqual(weather.ensure_nature_state(self.world, tick=0)['season'], 'winter')
        self.assertEqual(calendar_wire.time_block(self.world)['time']['season'], 'winter')
        self.assertEqual(resolver.tick_to_time_block(5500, world=self.world), 'night')
        self.assertEqual(resolver.tick_to_time_block(5500, world=self.other), 'dusk')
        self.assertEqual(weather.ensure_nature_state(self.other, tick=0)['season'], 'spring')
        self.power('set_season', 'clear')
        with patch.object(weather, '_maybe_execute_pending_event', return_value={}):
            result = weather.advance_nature_cycle({'h_mask': torch.zeros(0, dtype=torch.bool)}, torch.zeros((0, 1)), torch.zeros((0, 1)), engine=self.world)
        self.assertEqual(result['nature_state']['season'], 'spring')
        self.assertEqual(weather._world_season(self.world, 0), 'spring')
        self.assertEqual(calendar_wire.time_block(self.world)['time']['season'], 'spring')

    def test_time_schedule_light_isolation_and_clear(self):
        self.world.clock.tick = 1000
        self.other.clock.tick = 1000
        baseline = calendar_wire.time_block(self.world)['time']['light']
        self.power('set_time_of_day', 'night')
        candidates = resolver.routine_candidates_for_tick({}, 1000, world=self.world)
        self.assertEqual(candidates[0]['time_block'], 'night')
        self.assertEqual(resolver.tick_to_time_block(1000, world=self.other), 'day')
        self.assertLess(calendar_wire.time_block(self.world)['time']['light'], baseline)
        self.assertEqual(calendar_wire.time_block(self.other)['time']['light'], baseline)
        self.power('set_time_of_day', 'clear')
        self.assertEqual(resolver.tick_to_time_block(1000, world=self.world), 'day')

    def test_store_bridge_and_disabled_flag(self):
        engine = SimpleNamespace(resident_store=SimpleNamespace(), tick=1000)
        calendar.set_override(engine, 'time', 'night')
        self.assertIs(engine.resident_store._god_calendar_owner, engine)
        self.assertEqual(resolver.tick_to_time_block(1000, world=engine), 'night')
        with patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '0'}):
            self.assertEqual(resolver.tick_to_time_block(1000, world=engine), resolver.tick_to_time_block(1000))
            self.assertEqual(calendar_wire.time_block(engine)['time']['block'], calendar.now(1000).block)
            self.assertEqual(weather._world_season(engine, 0), weather.season_for_tick(0))

if __name__ == '__main__':
    unittest.main()

