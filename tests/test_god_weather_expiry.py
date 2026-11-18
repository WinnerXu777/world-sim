"""A god-set weather ends at its end tick on roster worlds too (the nature cycle that used to end it is off there)."""
import unittest
import uuid

from authored_village import load_village_maps
from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation
from persistence.sessions import GameSessions
from systems.god.powers import set_weather
from systems.god.state import is_paused, set_paused, store


async def authored_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def run(engine, ticks):
    for _ in range(ticks):
        engine.step()


def weather(engine):
    return engine._nature_state.get("weather", "clear")


def weather_events(engine):
    return [e for e in store(engine)["events"].values() if e["kind"] == "weather_changed"]


class WeatherExpiryCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        set_paused(backend.engine, False)
        await super().asyncTearDown()

    async def test_a_short_weather_ends_back_to_clear_and_is_remembered_once(self):
        engine = await authored_world()
        self.assertTrue(set_weather(engine, {"weather": "rain", "duration_ticks": 10})["changed"])
        run(engine, 5)
        self.assertEqual(weather(engine), "rain")
        run(engine, 10)
        self.assertEqual(weather(engine), "clear")
        events = weather_events(engine)
        self.assertEqual([(e["tick"] >= 10, e["witnesses"] != []) for e in events][-1], (True, True))
        self.assertEqual(len(events), 2)  # the change to rain and the expiry, each once
        run(engine, 100)
        self.assertEqual(len(weather_events(engine)), 2)  # nothing repeats
        self.assertNotIn("weather", store(engine))

    async def test_a_long_weather_persists_until_its_end_tick(self):
        engine = await authored_world()
        set_weather(engine, {"weather": "storm", "duration_ticks": 300})
        run(engine, 250)
        self.assertEqual(weather(engine), "storm")
        run(engine, 60)
        self.assertEqual(weather(engine), "clear")

    async def test_a_god_clear_still_works_and_cancels_the_pending_end(self):
        engine = await authored_world()
        set_weather(engine, {"weather": "rain", "duration_ticks": 200})
        run(engine, 20)
        cleared = set_weather(engine, {"weather": "clear"})
        self.assertTrue(cleared["changed"])
        self.assertEqual(weather(engine), "clear")
        self.assertNotIn("weather", store(engine))
        before = len(weather_events(engine))
        run(engine, 250)
        self.assertEqual(len(weather_events(engine)), before)  # no second "cleared" event when the old end tick passes

    async def test_a_second_weather_replaces_the_first_end_tick(self):
        engine = await authored_world()
        set_weather(engine, {"weather": "rain", "duration_ticks": 30})
        run(engine, 10)
        set_weather(engine, {"weather": "storm", "duration_ticks": 100})
        run(engine, 40)  # past the rain's end tick
        self.assertEqual(weather(engine), "storm")
        run(engine, 80)
        self.assertEqual(weather(engine), "clear")

    async def test_time_paused_means_no_expiry(self):
        engine = await authored_world()
        set_weather(engine, {"weather": "rain", "duration_ticks": 10})
        set_paused(engine, True)
        run(engine, 50)
        self.assertEqual(weather(engine), "rain")
        set_paused(engine, False)
        run(engine, 15)
        self.assertEqual(weather(engine), "clear")

    async def test_continue_in_the_middle_of_a_weather_keeps_the_end_tick(self):
        engine = await authored_world()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, _test_storage / "gw" / uuid.uuid4().hex[:8],
                                backend.create_genesis, 905, map_name="starter_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Rain", engine.world_epoch
        set_weather(engine, {"weather": "rain", "duration_ticks": 60})
        run(engine, 20)
        await sessions.save()
        saved_tick = engine.tick
        engine.reset_world()
        await sessions.continue_world(sessions.active_id)
        engine = backend.engine
        self.assertEqual(engine.tick, saved_tick)
        self.assertEqual(weather(engine), "rain")
        self.assertEqual(store(engine)["weather"]["ends_tick"], saved_tick + 40)
        run(engine, 30)
        self.assertEqual(weather(engine), "rain")
        run(engine, 20)
        self.assertEqual(weather(engine), "clear")

    async def test_a_new_world_has_no_pending_end(self):
        engine = await authored_world()
        set_weather(engine, {"weather": "rain", "duration_ticks": 50})
        engine.reset_world()
        await backend.create_genesis(engine, map_name="starter_village")
        self.assertNotIn("weather", store(engine))
        run(engine, 80)
        self.assertEqual(weather(engine), "clear")
        self.assertEqual(weather_events(engine), [])

    async def test_legacy_maps_keep_their_own_weather_cycle(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        set_weather(engine, {"weather": "rain", "duration_ticks": 10})
        self.assertNotIn("weather", store(engine))  # no god-side expiry entry on a legacy map


if __name__ == "__main__":
    unittest.main()
