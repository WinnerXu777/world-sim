"""gc.freeze policy: freeze the loaded world out of full collections, thaw it before a reset so old worlds are still reclaimed.

gc.freeze() only affects cycle detection (frozen objects are still freed by refcount), so the leak risk it creates is CYCLIC garbage
of a dropped world. The mechanism tests below use an explicit reference cycle to show that; the engine test runs repeated New Game
cycles in one process and requires tracked-object count and RSS to stay flat.
"""
import ctypes
import gc
import os
import sys
import unittest
import weakref
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from harness import gcpolicy  # noqa: E402


def rss_mb():
    """Resident set size in MB, or None where it cannot be read cheaply."""
    if sys.platform != "win32":
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return None
    from ctypes import wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.WorkingSetSize / 1048576.0


class Node:
    pass


def make_cycle():
    a, b = Node(), Node()
    a.other, b.other = b, a
    return a, weakref.ref(a)


class MechanismTests(unittest.TestCase):
    def tearDown(self):
        gcpolicy.thaw_before_reset()

    def test_a_frozen_cycle_survives_collection_until_thawed(self):
        world = [make_cycle()]                       # a live "world" holding a reference cycle
        ref = world[0][1]
        gcpolicy.freeze_after_load("w1")
        del world
        gc.collect()
        self.assertIsNotNone(ref(), "frozen cyclic garbage is not scanned: this is the leak the thaw prevents")
        self.assertTrue(gcpolicy.thaw_before_reset())
        gc.collect()
        self.assertIsNone(ref(), "after thaw the dropped world's cycle is reclaimed")

    def test_freeze_collects_garbage_first_and_never_stacks_frozen_worlds(self):
        make_cycle()                                  # garbage already
        ref = make_cycle()[1]
        gcpolicy.freeze_after_load("w1")
        self.assertIsNone(ref(), "garbage present at freeze time is collected, not frozen")
        first = gc.get_freeze_count()
        gcpolicy.freeze_after_load("w2")              # the previous world was never thawed
        self.assertLess(abs(gc.get_freeze_count() - first), 2000)

    def test_thaw_is_safe_when_nothing_is_frozen(self):
        gcpolicy.thaw_before_reset()
        self.assertFalse(gcpolicy.thaw_before_reset())
        self.assertEqual(gc.get_freeze_count(), 0)

    def test_env_switch_disables_the_policy(self):
        with mock.patch.dict(os.environ, {"EDEN_GC_FREEZE": "0"}):
            self.assertFalse(gcpolicy.freeze_after_load("w"))
            self.assertEqual(gc.get_freeze_count(), 0)

    def test_ensure_frozen_freezes_once_per_world_token(self):
        gcpolicy.ensure_frozen("w1")
        count = gc.get_freeze_count()
        self.assertGreater(count, 0)
        make_cycle_holder = [make_cycle()]
        gcpolicy.ensure_frozen("w1")                  # same world: no work
        self.assertEqual(gc.get_freeze_count(), count)
        gcpolicy.ensure_frozen("w2")                  # new world token: freeze again
        self.assertGreater(gc.get_freeze_count(), count - 1)
        self.assertEqual(gcpolicy.frozen_token(), "w2")
        del make_cycle_holder


class EngineNewGameCycleTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()

    async def asyncTearDown(self):
        gcpolicy.thaw_before_reset()
        await super().asyncTearDown()

    @staticmethod
    def total_objects():
        return len(gc.get_objects()) + gc.get_freeze_count()

    async def test_repeated_new_game_cycles_keep_objects_and_memory_flat(self):
        engine = backend.engine
        rows = []
        for _ in range(6):
            for _ in range(5):
                if engine.world_loaded:
                    engine.step()
            engine.reset_world()                      # thaws the previous world
            await backend.create_genesis(engine, map_name="starter_village")   # freezes the new one
            gc.collect()
            rows.append((self.total_objects(), rss_mb()))
        totals = [t for t, _ in rows]
        self.assertGreater(gc.get_freeze_count(), 0, "the loaded world is frozen")
        self.assertLessEqual(max(totals[1:]) - min(totals[1:]), 0.01 * totals[1], f"tracked-object count drifted across cycles: {totals}")
        rss = [r for _, r in rows if r is not None]
        if len(rss) == 6:
            self.assertLess(rss[-1] - rss[1], 25.0, f"RSS grew across New Game cycles (MB): {rss}")

    async def test_a_loaded_world_leaves_the_collector_almost_nothing_to_scan(self):
        engine = backend.engine
        engine.reset_world()
        await backend.create_genesis(engine, map_name="starter_village")
        frozen, scanned = gc.get_freeze_count(), len(gc.get_objects())
        self.assertGreater(frozen, 10000)
        self.assertLess(scanned, frozen / 5, f"{scanned} objects still scanned of {frozen} frozen")

    async def test_the_fallback_freezes_a_world_loaded_by_another_path(self):
        engine = backend.engine
        engine.reset_world()
        await backend.create_genesis(engine, map_name="starter_village")
        gcpolicy.thaw_before_reset()                  # as if a save restore had set world_loaded without freezing
        self.assertEqual(gc.get_freeze_count(), 0)
        engine.step()                                  # step() calls ensure_frozen(world_epoch)
        self.assertGreater(gc.get_freeze_count(), 10000)
        self.assertEqual(gcpolicy.frozen_token(), engine.world_epoch)


if __name__ == "__main__":
    unittest.main()
