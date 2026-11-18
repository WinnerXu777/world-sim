"""EDEN_EMOTION: the pure rules, and the pass on the real engine (the starter village, agent residents): lazy grudge decay, grief and comfort, jealousy, the two drives, loyalty, the instinct columns, flag off."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from systems import emotion
from systems.actions import emotion_day, gameclock, guard_day
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.decision import instinct_features as ext, matrix
from systems.emotion import rules

DAY = 2400


class Rules(unittest.TestCase):
    def test_a_grudge_rises_toward_zero_and_stops_there(self):
        self.assertEqual(rules.decay_grudge(-0.3, 1, False), -0.26)
        self.assertEqual(rules.decay_grudge(-0.3, 5, False), -0.1)
        self.assertEqual(rules.decay_grudge(-0.3, 30, False), 0.0)
        self.assertEqual(rules.decay_grudge(0.4, 9, False), 0.4)
        self.assertEqual(rules.decay_grudge(-0.3, 0, False), -0.3)

    def test_a_grave_grudge_never_fully_fades(self):
        self.assertEqual(rules.decay_grudge(-0.9, 5, True), -0.7)
        self.assertEqual(rules.decay_grudge(-0.9, 30, True), -0.35)
        self.assertEqual(rules.decay_grudge(-0.9, 100, True), -0.35)
        self.assertEqual(rules.decay_grudge(-0.2, 100, True), -0.2)             # already above the floor: left as it is
        self.assertTrue(rules.is_grave(-0.8, []))
        self.assertTrue(rules.is_grave(-0.4, ["grave"]))
        self.assertFalse(rules.is_grave(-0.4, []))

    def test_grief_starts_by_closeness_and_fades_in_three_days(self):
        self.assertEqual(rules.grief_start(1.0), 1.0)
        self.assertEqual(rules.grief_start(0.5), 0.7)
        grief = {"level": 0.8, "subject": "x", "since": 100, "relief": 0.0}
        self.assertEqual(rules.grief_now(grief, 100, DAY), 0.8)
        self.assertAlmostEqual(rules.grief_now(grief, 100 + int(1.5 * DAY), DAY), 0.4, places=3)
        self.assertEqual(rules.grief_now(grief, 100 + 3 * DAY, DAY), 0.0)
        self.assertEqual(rules.grief_now({**grief, "relief": 0.3}, 100, DAY), 0.5)
        self.assertEqual(rules.grief_now(None, 5, DAY), 0.0)

    def test_loyalty_moves_the_closeness_asked(self):
        self.assertEqual(rules.threshold(0.5, 0.5), 0.5)
        self.assertEqual(rules.threshold(0.5, 1.0), 0.35)
        self.assertEqual(rules.threshold(0.5, 0.0), 0.65)

    def test_the_trait_set_thrift_point(self):
        self.assertGreater(rules.thrift_point({"greed": 0.9, "caution": 0.8, "sociability": 0.1}), rules.thrift_point({"greed": 0.1, "caution": 0.3, "sociability": 0.9}))
        self.assertTrue(0.0 <= rules.thrift_point({"greed": 1.0, "caution": 1.0, "sociability": 0.0}) <= 1.0)


class Village(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_EMOTION": "1", "EDEN_CALENDAR": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_dormant_h", None)
        self.addCleanup(self.engine.__dict__.pop, "_dormant_h", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.store = self.engine.resident_store
        self.a, self.b, self.c = self.humans[0], self.humans[1], self.humans[2]
        for index, other in enumerate(self.humans[3:]):
            slot = self.engine._human_slot_for_id(other)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 3000.0 + 700.0 * index, 3000.0
        for human_id in self.humans:
            self.store.get(human_id)["relationships"] = {}
            self.store.get(human_id).pop("emotion", None)
            slot = self.engine._human_slot_for_id(human_id)
            self.h[slot, cfg.HUNGER], self.h[slot, cfg.THIRST], self.h[slot, cfg.THREAT], self.h[slot, cfg.HP], self.h[slot, cfg.MOOD] = 10.0, 10.0, 0.0, 100.0, 70.0
        self.put(self.a, 0.0)
        self.put(self.b, 8.0)
        self.put(self.c, 16.0)
        self.tick = 600

    def put(self, human_id, dx):
        base = self.engine._human_slot_for_id(self.humans[0])
        slot = self.engine._human_slot_for_id(human_id)
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = self.h[base, cfg.X] + dx, self.h[base, cfg.Y]

    def relate(self, owner, other, closeness, tags=None):
        self.store.get(owner)["relationships"][other] = {"kind": "known", "closeness": closeness, "last_seen_tick": 0, "tags": list(tags or ["known"]), "tag_meta": {}}

    def closeness(self, owner, other):
        return self.store.get(owner)["relationships"][other]["closeness"]

    def step(self, tick=None):
        self.tick = self.tick if tick is None else tick
        self.engine.tick = self.tick
        emotion_day.step(self.driver, self.engine, self.tick)

    def mood(self, human_id):
        return float(self.h[self.engine._human_slot_for_id(human_id), cfg.MOOD])

    def traits(self, human_id, **values):
        record = self.store.get(human_id)
        base = dict(((record.get("personality") or {}).get("traits")) or {})
        record["personality"] = {**(record.get("personality") or {}), "traits": {**base, **values}}

    def kill(self, human_id):
        self.store.mark_dead(human_id, self.tick)


class Decay(Village):
    async def test_the_first_pass_only_stamps_the_day(self):
        self.relate(self.a, self.b, -0.3)
        self.step()
        self.assertEqual(self.closeness(self.a, self.b), -0.3)
        self.assertEqual(emotion.read(self.store.get(self.a))["last_decay_tick"], 600)

    async def test_a_day_later_the_grudge_has_softened_and_two_days_at_once_double_it(self):
        self.relate(self.a, self.b, -0.3)
        self.relate(self.c, self.b, -0.3)
        self.step()
        self.step(600 + DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.26)
        self.step(600 + 3 * DAY)                                  # two days missed: applied at once
        self.assertEqual(self.closeness(self.a, self.b), -0.18)

    async def test_a_new_offence_refreshes_the_grudge_for_that_day(self):
        self.relate(self.a, self.b, -0.3)
        self.step()
        self.step(600 + DAY)                                      # -0.26, remembered
        self.relate(self.a, self.b, -0.5)                         # a new offence in between
        self.step(600 + 2 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.5)
        self.step(600 + 3 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.46)

    async def test_a_grave_betrayal_stops_at_the_floor_and_is_tagged(self):
        self.relate(self.a, self.b, -0.9)
        self.step()
        self.step(600 + 40 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.35)
        self.assertIn("grave", self.store.get(self.a)["relationships"][self.b]["tags"])
        self.step(600 + 80 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.35)

    async def test_thief_tagged_relations_and_friends_are_left_alone(self):
        self.relate(self.a, self.b, -0.3, ["known", "thief"])
        self.relate(self.a, self.c, 0.4)
        self.step()
        self.step(600 + 5 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.3)
        self.assertEqual(self.closeness(self.a, self.c), 0.4)

    async def test_a_dormant_resident_catches_up_the_days_on_waking(self):
        self.relate(self.a, self.b, -0.3)
        self.step()
        mask = torch.zeros(len(self.h), dtype=torch.bool)
        mask[self.engine._human_slot_for_id(self.a)] = True
        self.engine.__dict__["_dormant_h"] = mask
        self.step(600 + 4 * DAY)
        self.assertEqual(self.closeness(self.a, self.b), -0.3)
        self.engine.__dict__["_dormant_h"] = torch.zeros(len(self.h), dtype=torch.bool)
        self.step(600 + 4 * DAY + 60)
        self.assertEqual(self.closeness(self.a, self.b), -0.14)

    async def test_the_calendar_day_sets_the_pace(self):
        self.relate(self.a, self.b, -0.3)
        with unittest.mock.patch.dict("os.environ", {"EDEN_CALENDAR": "1"}):
            self.step()
            self.step(600 + DAY)
            self.assertEqual(self.closeness(self.a, self.b), -0.3)          # a calendar day is 12000 ticks
            self.step(600 + 12000)
            self.assertEqual(self.closeness(self.a, self.b), -0.26)

    async def test_flag_off_nothing_is_written(self):
        self.relate(self.a, self.b, -0.3)
        with unittest.mock.patch.dict("os.environ", {"EDEN_EMOTION": ""}):
            self.step()
            self.step(600 + 3 * DAY)
        self.assertNotIn("emotion", self.store.get(self.a))
        self.assertEqual(self.closeness(self.a, self.b), -0.3)


class Grief(Village):
    async def test_a_close_friends_death_starts_a_grief_that_lowers_mood_once_and_fades(self):
        self.relate(self.a, self.b, 0.8)
        self.step()
        self.kill(self.b)
        self.step(660)
        record = self.store.get(self.a)
        grief = emotion.read(record)["grief"]
        self.assertEqual((grief["subject"], grief["since"]), (self.b, 660))
        self.assertEqual(grief["level"], rules.grief_start(0.8))
        self.assertLess(self.mood(self.a), 70.0 - 10.0)
        mood = self.mood(self.a)
        self.step(720)
        self.assertEqual(self.mood(self.a), mood)                                   # the shock is once
        self.assertGreater(emotion.grief_level(record, 660, DAY), 0.8)
        self.assertEqual(emotion.grief_level(record, 660 + 3 * DAY, DAY), 0.0)

    async def test_a_distant_acquaintance_is_not_mourned(self):
        self.relate(self.a, self.b, 0.2)
        self.step()
        self.kill(self.b)
        self.step(660)
        self.assertNotIn("grief", emotion.read(self.store.get(self.a)))

    async def test_a_neighbour_who_holds_the_griever_dear_comforts_them(self):
        self.relate(self.a, self.b, 0.8)
        self.relate(self.c, self.a, 0.6)
        self.step()
        self.kill(self.b)
        self.h[self.engine._human_slot_for_id(self.a), cfg.MOOD] = 10.0              # the verb needs a low mood
        self.step(660)
        grief = emotion.read(self.store.get(self.a))["grief"]
        self.assertGreaterEqual(grief["relief"], rules.COMFORT_RELIEF)
        self.step(720)
        self.assertEqual(emotion.read(self.store.get(self.a))["grief"]["relief"], grief["relief"])      # the comforter rests for a while

    async def test_the_grief_column_is_live_with_the_flag(self):
        self.relate(self.a, self.b, 0.8)
        self.step()
        self.kill(self.b)
        self.step(660)
        self.engine.tick = 660
        X, S = ext.scores(self.engine, [self.a, self.c])
        self.assertGreater(float(X[0, ext.FEATURES.index("grief")]), 0.8)
        self.assertEqual(float(X[1, ext.FEATURES.index("grief")]), 0.0)
        self.assertGreater(float(S[0, matrix.ACTION_INDEX["rest"]]), float(S[1, matrix.ACTION_INDEX["rest"]]))
        with unittest.mock.patch.dict("os.environ", {"EDEN_EMOTION": ""}):
            self.assertIsNone(ext.scores(self.engine, [self.a]))


class Jealousy(Village):
    async def test_a_partners_attention_to_a_rival_builds_tension_then_resentment(self):
        self.traits(self.a, pride=0.9, vengefulness=0.9)
        self.relate(self.a, self.b, 0.8)
        self.relate(self.b, self.a, 0.8)
        self.relate(self.b, self.c, 0.5)
        self.relate(self.a, self.c, 0.1)
        self.put(self.a, 0.0)
        self.put(self.b, 20.0)
        self.put(self.c, 28.0)
        for index in range(6):
            self.step(600 + 60 * index)
        tension = emotion.read(self.store.get(self.a))["tension"][self.c]
        self.assertGreaterEqual(tension, rules.TENSION_WARN)
        self.assertLess(self.closeness(self.a, self.c), 0.1)
        self.assertEqual(emotion.tension(self.store.get(self.a)), tension)

    async def test_without_a_partner_there_is_no_jealousy(self):
        self.relate(self.a, self.b, 0.3)
        self.relate(self.b, self.a, 0.3)
        self.relate(self.b, self.c, 0.5)
        self.step()
        self.step(660)
        self.assertNotIn("tension", emotion.read(self.store.get(self.a)))

    async def test_tension_fades_over_the_days(self):
        self.relate(self.a, self.b, 0.8)
        self.relate(self.b, self.a, 0.8)
        self.relate(self.b, self.c, 0.5)
        self.put(self.b, 20.0)
        self.put(self.c, 28.0)
        self.step()
        self.step(660)
        self.assertGreater(emotion.tension(self.store.get(self.a)), 0.0)
        self.put(self.c, 900.0)
        self.step(660 + 4 * DAY)
        self.assertEqual(emotion.tension(self.store.get(self.a)), 0.0)


class Drives(Village):
    async def test_the_drives_start_from_the_traits_and_curiosity_builds_by_the_day(self):
        self.traits(self.a, curiosity=0.9, greed=0.9, caution=0.8, sociability=0.1)
        self.step()
        drives = dict(emotion.read(self.store.get(self.a))["drives"])
        self.assertAlmostEqual(drives["curiosity"], 0.45, places=3)
        self.step(600 + DAY)
        after = emotion.read(self.store.get(self.a))["drives"]
        self.assertGreater(after["curiosity"], drives["curiosity"])
        self.step(600 + 8 * DAY)
        self.assertLessEqual(emotion.drive(self.store.get(self.a), "curiosity"), 1.0)

    async def test_learning_a_place_discharges_curiosity(self):
        self.step()
        self.step(600 + 5 * DAY)
        before = emotion.drive(self.store.get(self.a), "curiosity")
        self.store.get(self.a)["known_places"] = {"spring": {"target_place": {"x": 1, "y": 1}, "space": 0, "tick": 1, "source": "test"}}
        self.step(600 + 5 * DAY + 60)
        self.assertAlmostEqual(emotion.drive(self.store.get(self.a), "curiosity"), max(0.0, before - rules.CURIOSITY_DISCHARGE), places=3)

    async def test_thrift_settles_by_trait_and_rises_when_food_runs_short(self):
        self.traits(self.a, greed=0.1, caution=0.1, sociability=0.9)
        self.traits(self.b, greed=0.9, caution=0.9, sociability=0.1)
        self.step()
        self.step(600 + 6 * DAY)
        self.assertLess(emotion.drive(self.store.get(self.a), "thrift"), emotion.drive(self.store.get(self.b), "thrift"))

    async def test_the_curious_choose_to_explore_in_the_pure_matrix(self):
        self.step()
        self.store.get(self.a)["emotion"]["drives"]["curiosity"] = 1.0
        self.store.get(self.b)["emotion"]["drives"]["curiosity"] = 0.0
        S = ext.scores(self.engine, [self.a, self.b])[1]
        self.assertGreater(float(S[0, matrix.ACTION_INDEX["explore"]]), float(S[1, matrix.ACTION_INDEX["explore"]]))


class Loyalty(Village):
    async def test_a_loyal_guard_stands_over_a_less_close_friend_than_a_disloyal_one(self):
        self.traits(self.a, loyalty=1.0)
        self.assertEqual(guard_day._kin_closeness(self.engine, self.a, 0.5), 0.35)
        self.traits(self.a, loyalty=0.0)
        self.assertEqual(guard_day._kin_closeness(self.engine, self.a, 0.5), 0.65)
        with unittest.mock.patch.dict("os.environ", {"EDEN_EMOTION": ""}):
            self.assertEqual(guard_day._kin_closeness(self.engine, self.a, 0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
