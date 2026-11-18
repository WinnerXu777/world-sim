"""Save/Continue map guard: a save records its maps; Continue refuses a changed map (gameplay), legacy saves are unaffected."""
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation
from persistence import map_guard
from persistence.map_guard import MapMismatchError
from persistence.sessions import GameSessions
from systems.movement.map_contract import load_from_environment
from authored_village import MAP_FILES, MAP_NAMES, ORIGINS as ALL_ORIGINS, load_village_maps

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"
ORIGINS = json.dumps({"smith_interior": [620, 0]})


def register(village=VILLAGE, smith=SMITH, origins=ORIGINS):
    load_village_maps(village=village, smith=smith, origins=origins)


def variant(directory, *, revision=None, extra_bytes=b"", source=VILLAGE):
    """A copy of the village map with another revision number and/or trailing bytes (so another sha256)."""
    data = json.loads(source.read_text(encoding="utf-8"))
    if revision is not None:
        data["revision"] = revision
    path = directory / f"{source.stem}_{uuid.uuid4().hex[:6]}.json"
    path.write_bytes(json.dumps(data, indent=2).encode("utf-8") + extra_bytes)
    return path


def manifest_of(engine):
    return engine.inventory_state.get(map_guard.MANIFEST_KEY)


class GuardCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.directory = _test_storage / "mg" / uuid.uuid4().hex[:8]
        self.directory.mkdir(parents=True, exist_ok=True)
        register()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, self.directory / "saves",
                                     backend.create_genesis, 905, map_name="starter_village")
        self.sessions.active_id, self.sessions.active_name = uuid.uuid4().hex, "Guard"
        self.sessions.active_epoch = backend.engine.world_epoch
        await self.sessions.save()
        self.save_id = self.sessions.active_id

    async def continue_save(self):
        backend.engine.reset_world()
        return await self.sessions.continue_world(self.save_id)

    async def test_the_save_records_every_placed_map_with_revision_sha_and_origin(self):
        saved = manifest_of(backend.engine)
        self.assertEqual([m["map_id"] for m in saved], list(MAP_NAMES))
        for entry, path in zip(saved, MAP_FILES):
            import hashlib
            self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(entry["revision"], json.loads(path.read_text(encoding="utf-8"))["revision"])
        self.assertEqual(saved[1]["origin"], [620.0, 0.0])
        self.assertEqual(saved[2]["origin"], [620.0, 400.0])
        self.assertEqual(saved[3]["origin"], [960.0, 160.0])

    async def test_matching_maps_continue(self):
        result = await self.continue_save()
        self.assertTrue(result["ok"])
        self.assertEqual(backend.engine._map_name, "starter_village")

    async def test_a_changed_revision_is_refused_naming_old_and_new_revision_and_sha(self):
        old = {m["map_id"]: m for m in manifest_of(backend.engine)}
        revised = variant(self.directory, revision=old["starter_village"]["revision"] + 1)
        register(village=revised)
        new = {m["map_id"]: m for m in map_guard.current_manifest("starter_village")}
        with self.assertRaises(MapMismatchError) as caught:
            await self.continue_save()
        message = str(caught.exception)
        for needle in ("starter_village", f"saved revision {old['starter_village']['revision']}",
                       f"registered revision {new['starter_village']['revision']}", old["starter_village"]["sha256"],
                       new["starter_village"]["sha256"], "EDEN_ALLOW_MAP_MISMATCH"):
            self.assertIn(needle, message)
        self.assertNotIn("smith_interior", message)  # the unchanged map is not blamed

    async def test_a_changed_sha_with_the_same_revision_is_refused(self):
        same_revision = variant(self.directory, extra_bytes=b"\n\n")
        register(village=same_revision)
        with self.assertRaises(MapMismatchError) as caught:
            await self.continue_save()
        self.assertIn("without a revision bump", str(caught.exception))

    async def test_a_moved_map_is_refused(self):
        register(origins=json.dumps({"smith_interior": [640, 0]}))
        with self.assertRaises(MapMismatchError) as caught:
            await self.continue_save()
        self.assertIn("placed elsewhere", str(caught.exception))

    async def test_the_http_error_is_a_400_with_the_same_text(self):
        register(village=variant(self.directory, revision=99))
        try:
            await self.continue_save()
        except ValueError as exc:  # the route maps ValueError to HTTP 400 with str(exc)
            self.assertIn("revised after this save", str(exc))
        else:
            self.fail("Continue should have been refused")

    async def test_the_override_and_non_gameplay_profiles_continue_with_a_notice(self):
        register(village=variant(self.directory, revision=99))
        with mock.patch.dict(os.environ, {"EDEN_ALLOW_MAP_MISMATCH": "1"}):
            self.assertTrue((await self.continue_save())["ok"])
        self.assertEqual(manifest_of(backend.engine)[0]["revision"], json.loads(VILLAGE.read_text(encoding="utf-8"))["revision"])  # still the saved one
        with mock.patch.dict(os.environ, {"EDEN_PROFILE": "render_fixture"}):
            self.assertTrue((await self.continue_save())["ok"])
        await self.sessions.save()  # the next save records the maps actually in use
        self.assertEqual(manifest_of(backend.engine)[0]["revision"], 99)

    async def test_a_save_without_a_manifest_still_loads(self):
        payload = {"engine": {"inventory_state": {}, "_map_name": "starter_village"}}
        self.assertEqual(map_guard.check(payload), [])
        register(village=variant(self.directory, revision=50))
        self.assertEqual(map_guard.check(payload), [])  # nothing to compare against

    async def test_a_missing_secondary_map_is_refused(self):
        from systems.movement.map_contract import clear_map_contracts
        clear_map_contracts()
        load_from_environment({"EDEN_MAP_FILES": str(VILLAGE)})
        with self.assertRaises(MapMismatchError) as caught:
            await self.continue_save()
        self.assertIn("smith_interior", str(caught.exception))
        self.assertIn("not registered", str(caught.exception))


class LegacyCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_legacy_worlds_record_no_manifest_and_continue_unchanged(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        directory = _test_storage / "mg" / uuid.uuid4().hex[:8]
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, directory,
                                backend.create_genesis, 905, map_name="playable_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Legacy", backend.engine.world_epoch
        await sessions.save()
        self.assertNotIn(map_guard.MANIFEST_KEY, backend.engine.inventory_state)
        backend.engine.reset_world()
        self.assertTrue((await sessions.continue_world(sessions.active_id))["ok"])
        self.assertNotIn(map_guard.MANIFEST_KEY, backend.engine.inventory_state)


if __name__ == "__main__":
    unittest.main()
