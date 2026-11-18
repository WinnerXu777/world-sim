import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from runtime.resident_store import ResidentAgentStore, _atomic_write_json, write_resident_batch


class ResidentPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ".tmp" / "tests" / uuid.uuid4().hex
        self.store = ResidentAgentStore(self.root)
        self.path = self.root / "h_000001.json"
        _atomic_write_json(self.path, {"version": 1})
        self.store._cache["h_000001"] = {"version": 2}
        self.store._dirty.add("h_000001")

    def test_locked_replace_preserves_last_good_save_and_dirty_state(self):
        with patch.object(Path, "replace", side_effect=PermissionError("locked")):
            self.store.flush_dirty(tick=20)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 1})
        self.assertIn("h_000001", self.store._dirty)
        self.assertIn("h_000001", self.store.save_errors)
        self.assertNotIn("h_000001", self.store._last_flushed_tick)
        with patch("runtime.resident_store._atomic_write_json") as write:
            self.store.flush_dirty(tick=21)
            write.assert_not_called()
        self.store.flush_dirty(tick=40)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 2})
        self.assertFalse(self.store._dirty)
        self.assertFalse(self.store.save_errors)

    def test_failed_temporary_write_does_not_touch_last_good_file(self):
        with patch.object(Path, "open", side_effect=OSError("disk full")):
            self.store.flush_dirty(force=True)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 1})
        self.assertIn("h_000001", self.store._dirty)

    def test_old_revision_and_old_generation_cannot_clear_new_changes(self):
        self.store.touch_resident("h_000001")
        jobs = self.store.capture_dirty(tick=20)
        self.store._cache["h_000001"]["version"] = 3
        self.store.touch_resident("h_000001")
        results = write_resident_batch(jobs)
        self.store.acknowledge_writes(results)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 2})
        self.assertIn("h_000001", self.store._dirty)
        self.store.reset_world()
        self.store._cache["h_000001"] = {"version": 4}
        self.store.touch_resident("h_000001")
        self.store.acknowledge_writes(results)
        self.assertIn("h_000001", self.store._dirty)
        self.store.flush_dirty(force=True)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 4})

    def test_background_mode_defers_even_forced_flush(self):
        self.store.background_writes = True
        with patch("runtime.resident_store._atomic_write_json") as write:
            self.store.flush_dirty(force=True)
            write.assert_not_called()
        self.assertIn("h_000001", self.store._dirty)

    def test_bounded_batch_does_not_starve_unattempted_residents(self):
        for index in range(20):
            human_id = f"h_{index:06d}"
            self.store._cache[human_id] = {"version": 1}
            self.store.touch_resident(human_id)
        jobs = self.store.capture_dirty(tick=20, force=True, limit=16)
        self.assertEqual(len(jobs), 16)
        self.store.acknowledge_writes(tuple((uid, gen, rev, tick, "locked")
                                          for uid, gen, rev, path, data, tick in jobs))
        later = self.store.capture_dirty(tick=20, force=True, limit=4)
        self.assertTrue({job[0] for job in jobs}.isdisjoint({job[0] for job in later}))


if __name__ == "__main__":
    unittest.main()
