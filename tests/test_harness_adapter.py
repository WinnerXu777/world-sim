"""EngineWorld: the harness World over the real legacy Engine, with no behaviour change."""
from authored_village import load_village_maps
import hashlib
import unittest

import torch

from test_startup_preservation import backend  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from harness import effects as fx
from harness import target_selectors as sel
from harness.adapter import EngineWorld


def digest(engine):
    return hashlib.sha256(engine.state.h_tensor.numpy().tobytes() + engine.state.m_tensor.numpy().tobytes()).hexdigest()


class EngineWorldTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.world = EngineWorld(self.engine, seed=1008)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]

    def test_tables_share_the_engine_tensors_and_live_ids(self):
        h = self.world.table("humans")
        self.assertEqual(h.tensor.data_ptr(), self.engine.state.h_tensor.data_ptr())
        self.assertEqual(self.world.table("entities").tensor.data_ptr(), self.engine.state.m_tensor.data_ptr())
        self.assertIs(h.ids, self.engine._human_uid_by_slot)
        self.assertEqual(sorted(h.ids[s] for s in h.live_slots()), sorted(self.humans))
        self.assertEqual(len(self.humans), 8)
        self.assertEqual(self.world.observe_counts(), {"humans": 8, "entities": int((self.engine.state.m_tensor[:, cfg.M_TYPE] > 0).sum())})

    def test_construction_and_reads_change_nothing(self):
        before = digest(self.engine)
        world = EngineWorld(self.engine)
        sel.resolve({"of": "humans", "where": [{"field": "hunger", "op": ">=", "value": 0}]}, world)
        world.within("humans", 600, 450, 400)
        world.table("humans").get(self.humans[0], "hp")
        world.rng("s", self.humans[0]).random()
        self.assertEqual(digest(self.engine), before)

    def test_clock_seed_and_legacy_frame(self):
        self.assertEqual(self.world.tick, self.engine.tick)
        t0 = self.world.tick
        self.engine.step()
        self.assertEqual(self.world.tick, t0 + 1)
        with self.assertRaises(RuntimeError):
            self.world.clock.advance()
        self.assertEqual((self.world.bounds(), self.world.centre()), ((0.0, 0.0, float(cfg.MAP_WIDTH), float(cfg.MAP_HEIGHT)), (cfg.MAP_WIDTH / 2, cfg.MAP_HEIGHT / 2)))
        self.assertEqual(self.world.clamp(-4, 99999), (0.0, float(cfg.MAP_HEIGHT)))
        self.assertEqual(self.world.rng("s", "h_000001").random(), EngineWorld(self.engine, seed=1008).rng("s", "h_000001").random())

    def test_selectors_resolve_real_residents_to_stable_ids(self):
        r = sel.resolve({"of": "humans"}, self.world)
        self.assertEqual(sorted(r.ids), sorted(self.humans))
        who = self.humans[0]
        x, y = self.world.table("humans").get(who, "x"), self.world.table("humans").get(who, "y")
        near = sel.resolve({"of": "humans", "near": {"anchor": {"point": [x, y]}, "radius": 0.01}}, self.world)
        self.assertEqual(near.ids, (who,))
        self.assertEqual(self.world.within("humans", x, y, 0.01), [who])

    def test_effects_write_through_to_the_engine_tensor(self):
        who = self.humans[0]
        slot = self.engine._human_slot_for_id(who)
        before = float(self.engine.state.h_tensor[slot, cfg.HUNGER])
        report = self.world.apply([fx.delta("humans", who, "hunger", 7.5)])
        self.assertEqual((report.ok, report.revision), (True, 1))
        self.assertAlmostEqual(float(self.engine.state.h_tensor[slot, cfg.HUNGER]), before + 7.5, places=4)
        self.assertEqual(self.world.apply([fx.set_("humans", who, "hp", 250)]).clamped, 1)       # hp is bounded by the legacy 100 cap
        self.assertEqual(float(self.engine.state.h_tensor[slot, cfg.HP]), 100.0)
        self.assertEqual(self.world.apply([fx.delta("humans", "h_999999", "hunger", 1)]).skipped[0].reason, "unknown_id")

    def test_the_engine_keeps_running_after_harness_writes(self):
        self.world.apply([fx.delta("humans", self.humans[0], "hunger", 3)])
        for _ in range(5):
            self.engine.step()
        self.assertEqual(self.engine.tick, self.world.tick)

    def test_events_use_the_god_witness_rule(self):
        from systems.god.state import witnesses
        who = self.humans[0]
        point = tuple(self.world.table("humans").position(self.engine._human_slot_for_id(who)))
        event = self.world.events.emit("shout", actors=(who,), place=point, radius=80.0)
        self.assertEqual(sorted(event.witnesses), sorted(set(witnesses(self.engine, point, radius=80.0, always=(who,)))))
        self.assertIn(who, event.witnesses)

    def test_items_go_through_the_real_inventory_and_are_conserved(self):
        a, b = self.humans[0], self.humans[1]
        store = self.world.items
        store.add(a, "coin", 50)
        base_total, base_a, base_b = store.total("coin"), store.quantity(a, "coin"), store.quantity(b, "coin")
        report = self.world.apply([fx.Transfer("coin", 20, a, b)])
        self.assertTrue(report.ok, report.skipped)
        self.assertEqual((store.quantity(a, "coin"), store.quantity(b, "coin"), store.total("coin")), (base_a - 20, base_b + 20, base_total))
        over = self.world.apply([fx.Transfer("coin", base_a, a, b)])      # more than a has left
        self.assertEqual([s.reason for s in over.skipped], ["insufficient"])
        self.assertEqual(store.total("coin"), base_total)
        self.assertIn("coin", list(store.items()))


if __name__ == "__main__":
    unittest.main()
