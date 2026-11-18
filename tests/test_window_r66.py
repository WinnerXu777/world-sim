"""R6.6 integrated-set snapshots through the real engine export/version paths."""
import copy
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from test_harness_window_manager import WindowFixture
from test_harness_creature_store import CreatureFixture
import genesis_config as cfg
from harness import window_wire
from systems.worldgen.rings import ChunkCoord


class IntegratedWireTests(WindowFixture):
    def rebuild(self):
        self.engine._build_map_delta_payload()

    def versions(self):
        return self.engine._map_state_version, self.engine._map_geo_version_sent

    def set_chunks(self, coords):
        # Isolate set-only changes: no entity rows or geo-version changes.
        self.manager.chunks = {ChunkCoord(x, y): SimpleNamespace(boxes=[], sha256="same") for x, y in coords}
        self.manager._publish()

    async def test_two_consumers_receive_set_only_change_after_unchanged_ticks(self):
        self.rebuild()
        base = self.versions()
        self.set_chunks([(2, 0), (-1, 1), (-1, -2)])
        self.rebuild()
        self.assertEqual(self.versions(), (base[0] + 1, base[1]))
        first = copy.deepcopy(self.engine.get_map_delta_for(*base))
        self.assertFalse(first["replace_all"])
        self.assertEqual(first["upserts"], [])
        self.assertEqual(first["removed"], [])
        self.assertEqual(first["window"], {"integrated": ["-1:-2", "-1:1", "2:0"]})
        self.assertNotIn("window.integrated", first)
        # These reads/builds must not consume the outstanding update.
        stamp = window_wire.stamp(self.engine)
        self.assertEqual(set(stamp), {"window_origin", "window_epoch"})
        h, a, _ = self.engine._current_masks()
        self.engine._build_frame_payload(h, a)
        self.engine._build_bootstrap_payload()
        self.rebuild()
        self.assertEqual(self.engine.get_map_delta_for(*base), first)
        self.assertEqual(self.engine.get_map_delta_for(*base), first)
        self.assertNotIn("window", self.engine.get_map_delta_for(*self.versions()))
        self.assertEqual(self.engine._bootstrap_payload["world"]["window"], first["window"])
        self.assertNotIn("window", self.engine._frame_payload)

    async def test_initial_full_reconnect_and_removed_set(self):
        self.rebuild()
        self.assertEqual(self.engine.get_map_delta_for()["window"], {"integrated": []})
        self.set_chunks([(0, 0), (-2, 3)])
        self.rebuild()
        base = self.versions()
        expected = {"integrated": ["-2:3", "0:0"]}
        self.assertEqual(self.engine.get_map_delta_for()["window"], expected)
        self.assertEqual(self.engine.get_map_delta_for(-99, -99)["window"], expected)
        self.set_chunks([])
        self.rebuild()
        delta = self.engine.get_map_delta_for(*base)
        self.assertEqual(delta["window"], {"integrated": []})
        self.assertEqual(delta["state_version"], base[0] + 1)
        self.assertEqual(self.engine._bootstrap_payload["world"]["window"], {"integrated": []})

    async def test_origin_and_digest_changes_do_not_signal_unchanged_set(self):
        far = 2**40 - 2
        self.set_chunks([(far, -far), (-2, 10)])
        self.rebuild()
        version = self.versions()
        expected = ["-2:10", f"{far}:{-far}"]
        self.manager.frame.origin = (far, -far)
        self.manager.epoch += 1
        self.manager.chunks[ChunkCoord(-2, 10)].sha256 = "changed"
        self.manager._publish()
        self.rebuild()
        self.assertEqual(self.versions(), version)
        self.assertNotIn("window", self.engine.get_map_delta_for(*version))
        full = self.engine.get_map_delta_for()
        self.assertEqual(full["window"]["integrated"], expected)
        self.assertEqual(full["window_origin"], [far, -far])
        self.assertEqual(full["window_epoch"], 1)

    async def test_real_integration_and_unload_follow_entity_exports(self):
        self.rebuild()
        before = self.versions()
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(1)
        self.rebuild()
        coord = next(iter(self.manager.chunks))
        delta = self.engine.get_map_delta_for(*before)
        self.assertEqual(delta["window"]["integrated"], [coord.chunk_id])
        self.assertTrue(delta["upserts"])
        ids = {row["id"] for row in delta["upserts"]}
        self.assertTrue(all(uid.startswith("c2_2:") for uid in ids))
        before = self.versions()
        self.manager.unload(coord)
        self.rebuild()
        delta = self.engine.get_map_delta_for(*before)
        self.assertEqual(delta["window"], {"integrated": []})
        self.assertEqual(set(delta["removed"]), ids)
        self.assertEqual(self.engine.get_map_delta_for()["upserts"], [])

    async def test_flag_off_does_not_change_wire_or_version_for_set_changes(self):
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            self.rebuild()
            before = self.versions()
            self.set_chunks([(9, -8)])
            self.rebuild()
            self.assertEqual(self.versions(), before)
            self.assertEqual(window_wire.stamp(self.engine), {})
            self.assertEqual(window_wire.world_block(self.engine), {})
            self.assertEqual(window_wire.integrated_block(self.engine), {})
            for payload in (self.engine._map_delta_payload, self.engine.get_map_delta_for(), self.engine.get_map_delta_for(-99, -99), self.engine._bootstrap_payload["world"]):
                self.assertNotIn("window", payload)
                self.assertNotIn("window.integrated", payload)

    async def test_protocol_reset_retires_previous_world_snapshot(self):
        self.set_chunks([(4, 5)])
        self.rebuild()
        self.assertEqual(self.engine.get_map_delta_for()["window"]["integrated"], ["4:5"])
        self.engine.reset_protocol_state()
        self.assertEqual(self.engine._bootstrap_payload["world"]["window"], {"integrated": []})
        self.assertEqual(self.engine.get_map_delta_for()["window"], {"integrated": []})
        self.assertIsNone(self.engine._latest_window_delta_payload)


class CreatureExportLifecycleTests(CreatureFixture):
    def animal_ids(self):
        h, a, _ = self.engine._current_masks()
        self.engine._build_frame_payload(h, a)
        rows = self.engine._frame_payload["animals"]
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), "frame contains no duplicate animal IDs")
        return set(ids)

    async def test_spawn_unload_restore_is_visible_in_actual_frame_exports(self):
        slots = self.creature_slots()
        self.assertTrue(slots)
        row = self.engine.state.m_tensor[slots[0]]
        coord = ChunkCoord(int(float(row[cfg.CX]) // 256), int(float(row[cfg.CY]) // 256))
        self.assertIn(coord, self.manager.chunks)
        before = self.animal_ids()
        self.assertTrue(self.uids() <= before)
        self.manager.unload(coord)
        stored = {record["uid"] for record in self.manager.creatures.records[coord]}
        self.assertTrue(stored)
        self.assertTrue(stored <= before)
        self.assertTrue(stored.isdisjoint(self.animal_ids()))
        self.manager.integrate(coord, self.service.peek(coord))
        self.assertTrue(stored <= self.animal_ids(), "restored animals retain IDs in real wire rows")


if __name__ == "__main__":
    unittest.main()
