"""R6.5 offscreen villages (EDEN_OFFSCREEN, needs EDEN_WINDOW_DORMANCY; plan .orchestration/wsim/handovers/1119wsimimplementation-plan-R6.5.md).

Option A: a dormant group is advanced at wake by the missed game days with one pure function, ``offscreen.coarse_days``: the food balance
(the group's food rows with closed-form regrowth against what its residents burn), needs at the fed set point or rising when unfed,
starvation and dehydration damage, healing, age, and death by the normal rules (D1: old age, lasting hunger). Flag off, the wake is
today's capped catch-up, unchanged.
"""
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_dormancy import DormancyFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
from harness import dormancy, offscreen  # noqa: E402

RATES = offscreen.Rates(day_ticks=100, hunger=0.05, thirst=0.07, starve_damage=2.0, thirst_damage=2.5, heal=0.3,
                        age_step=1.0 / 600.0, cooldown_decay=1.0 / 600.0)
MEAL = RATES.hunger * RATES.day_ticks / cfg.EAT_HUNGER_RESTORE * cfg.EAT_RESOURCE_COST      # food units one resident eats per day
FIRST_MEAL = (50.0 + RATES.hunger * RATES.day_ticks - 30.0) / cfg.EAT_HUNGER_RESTORE * cfg.EAT_RESOURCE_COST   # day 1 from hunger 50 to the set point 30


def resident(uid="a", **kw):
    values = dict(uid=uid, sex=0.0, age=30.0, life_exp=70.0, hunger=50.0, thirst=40.0, hp=80.0)
    values.update(kw)
    return offscreen.Resident(**values)


class CoarseDaysTests(unittest.TestCase):
    """The pure model: plain data in, plain data out, no engine."""

    def test_zero_days_is_the_identity(self):
        before = resident(hunger=12.0, thirst=7.0, hp=55.0, stamina=20.0, threat=30.0)
        out = offscreen.coarse_days([before], [offscreen.Food("n1", 4.0, 0.01, 9.0)], 0, RATES)
        self.assertEqual(out.residents["a"], before)
        self.assertEqual(out.foods, {"n1": 4.0})
        self.assertEqual(out.deaths, [])

    def test_a_fed_village_settles_at_the_set_points_and_nobody_dies(self):
        out = offscreen.coarse_days([resident()], [offscreen.Food("n1", 1000.0)], 3, RATES)
        a = out.residents["a"]
        self.assertEqual(a.hunger, offscreen.CATCH_UP_V2["hunger_fed"])
        self.assertEqual(a.thirst, offscreen.CATCH_UP_V2["thirst_watered"])
        self.assertTrue(a.alive)
        self.assertEqual(a.hp, 100.0, "fed and safe: healed, capped at 100")
        eaten = (50.0 + RATES.hunger * RATES.day_ticks - offscreen.CATCH_UP_V2["hunger_fed"]) / cfg.EAT_HUNGER_RESTORE + 2 * MEAL
        self.assertAlmostEqual(out.foods["n1"], 1000.0 - eaten, places=6, msg="eats down to the set point, then holds it")
        self.assertAlmostEqual(a.age, 30.0 + 3 * RATES.day_ticks * RATES.age_step, places=9)
        self.assertEqual((a.stamina, a.threat), (100.0, 0.0), "rested, as the interim wake")

    def test_fed_and_watered_never_raise_a_need_past_its_normal_rise(self):
        out = offscreen.coarse_days([resident(hunger=5.0, thirst=3.0)], [offscreen.Food("n1", 1000.0)], 1, RATES)
        a = out.residents["a"]
        self.assertAlmostEqual(a.hunger, 5.0 + RATES.hunger * RATES.day_ticks, places=9, msg="below the set point: rises as awake")
        self.assertAlmostEqual(a.thirst, 3.0 + RATES.thirst * RATES.day_ticks, places=9)
        self.assertEqual(out.foods["n1"], 1000.0, "nobody eats below the set point")
        out = offscreen.coarse_days([resident(hunger=28.0, thirst=22.0)], [offscreen.Food("n1", 1000.0)], 2, RATES)
        a = out.residents["a"]
        self.assertEqual((a.hunger, a.thirst), (offscreen.CATCH_UP_V2["hunger_fed"], offscreen.CATCH_UP_V2["thirst_watered"]),
                         "reaches the set point and stays there")
        eaten = (28.0 + RATES.hunger * RATES.day_ticks - offscreen.CATCH_UP_V2["hunger_fed"]) / cfg.EAT_HUNGER_RESTORE + MEAL
        self.assertAlmostEqual(out.foods["n1"], 1000.0 - eaten, places=9)

    def test_with_no_food_hunger_rises_and_lasting_hunger_kills_by_the_normal_rule(self):
        out = offscreen.coarse_days([resident(hunger=0.0, hp=100.0)], [], 30, RATES)
        a = out.residents["a"]
        # 5 hunger a day: 90 at the end of day 18 (index 17); day 19 (index 18) is spent starving: 100 ticks x 2.0 damage > 100 hp.
        self.assertFalse(a.alive)
        self.assertEqual(out.deaths, [("a", 18, "starvation")])
        self.assertEqual(a.hp, 0.0)

    def test_a_shortfall_is_shared_and_raises_hunger_by_the_unfed_share(self):
        rise, point = RATES.hunger * RATES.day_ticks, offscreen.CATCH_UP_V2["hunger_fed"]
        need = (40.0 + rise - point) / cfg.EAT_HUNGER_RESTORE * cfg.EAT_RESOURCE_COST      # what one resident eats to get back to the set point
        food = 1.5 * need                                        # three quarters of what two residents need
        out = offscreen.coarse_days([resident("a", hunger=40.0), resident("b", hunger=40.0)], [offscreen.Food("n1", food)], 1, RATES)
        fed = 0.75
        expected = fed * point + (1.0 - fed) * (40.0 + rise)
        self.assertAlmostEqual(out.residents["a"].hunger, expected, places=6)
        self.assertAlmostEqual(out.residents["b"].hunger, expected, places=6)
        self.assertAlmostEqual(out.foods["n1"], 0.0, places=9)

    def test_old_age_kills_on_the_day_age_passes_life_expectancy(self):
        out = offscreen.coarse_days([resident(age=59.9, life_exp=60.0)], [offscreen.Food("n1", 1000.0)], 5, RATES, start_day=7)
        self.assertEqual(out.deaths, [("a", 7, "old_age")], "a sixth of a life-year a day: past 60 on the first day")
        self.assertFalse(out.residents["a"].alive)
        self.assertGreater(out.residents["a"].age, 60.0, "the row keeps its age: the normal instinct_die removes it at wake")
        self.assertAlmostEqual(out.foods["n1"], 1000.0 - FIRST_MEAL, places=6, msg="the dead eat nothing after their day")

    def test_food_regrows_in_closed_form_under_its_cap(self):
        out = offscreen.coarse_days([], [offscreen.Food("n1", 10.0, 0.01, 15.0)], 3, RATES)
        self.assertAlmostEqual(out.foods["n1"], 13.0, places=6)
        out = offscreen.coarse_days([], [offscreen.Food("n1", 10.0, 0.01, 15.0)], 30, RATES)
        self.assertAlmostEqual(out.foods["n1"], 15.0, places=6)
        out = offscreen.coarse_days([resident()], [offscreen.Food("n1", 10.0, 0.01, 15.0)], 3, RATES)
        self.assertAlmostEqual(out.foods["n1"], 13.0 - FIRST_MEAL - 2 * MEAL, places=6)

    def test_a_partial_day_is_the_same_as_its_parts(self):
        start = [resident(hunger=0.0)]
        whole = offscreen.coarse_days(start, [], 1.5, RATES)
        first = offscreen.coarse_days(start, [], 1, RATES)
        second = offscreen.coarse_days(list(first.residents.values()), [], 0.5, RATES, start_day=1)
        self.assertAlmostEqual(whole.residents["a"].hunger, 7.5, places=6)
        self.assertEqual(whole.residents["a"], second.residents["a"])

    def test_roster_needs_and_age_scales_apply(self):
        out = offscreen.coarse_days([resident(hunger=0.0, needs_scale=2.0, age_scale=3.0)], [], 1, RATES)
        self.assertAlmostEqual(out.residents["a"].hunger, 10.0, places=6)
        self.assertAlmostEqual(out.residents["a"].age, 30.0 + 3.0 * RATES.day_ticks * RATES.age_step, places=9)

    def test_dehydration_without_water_and_cooldown_decay(self):
        out = offscreen.coarse_days([resident(thirst=0.0, hp=100.0, cooldown=1.0)], [offscreen.Food("n1", 1000.0)], 1, RATES, water=False)
        self.assertAlmostEqual(out.residents["a"].thirst, 7.0, places=6)
        self.assertAlmostEqual(out.residents["a"].cooldown, 1.0 - RATES.day_ticks * RATES.cooldown_decay, places=9)

    def test_deterministic_and_independent_of_member_order(self):
        people = [resident("a", hunger=10.0), resident("b", hunger=70.0, hp=30.0), resident("c", age=69.95)]
        foods = [offscreen.Food("n1", 2.0, 0.001, 5.0), offscreen.Food("n2", 1.0)]
        reference = offscreen.coarse_days(people, foods, 4.25, RATES, start_day=3)
        for _ in range(5):
            shuffled_people, shuffled_foods = people[:], foods[:]
            random.shuffle(shuffled_people)
            random.shuffle(shuffled_foods)
            again = offscreen.coarse_days(shuffled_people, shuffled_foods, 4.25, RATES, start_day=3)
            self.assertEqual(again.residents, reference.residents)
            self.assertEqual(again.foods, reference.foods)
            self.assertEqual(sorted(again.deaths), sorted(reference.deaths))

    def test_groups_join_adjacent_chunks_and_home_anchors(self):
        points = {"a": (3000.0, 500.0), "b": (3200.0, 500.0), "c": (5000.0, 500.0), "d": (9000.0, 9000.0)}
        homes = {"c": (3100.0, 520.0)}
        groups = offscreen.group_residents(points, homes)
        self.assertEqual(sorted(sorted(g) for g in groups), [["a", "b", "c"], ["d"]])


class OffscreenFixture(DormancyFixture):
    """Slot 0 is the player (integrated chunk), slot 1 is far away (dormant). Food rows are cleared unless a test places one."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_OFFSCREEN": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        m = self.engine.state.m_tensor
        for food_type in iat.FOOD_SOURCE_TYPES:
            m[m[:, cfg.M_TYPE] == float(food_type), cfg.M_RESOURCE_FOOD] = 0.0
        self.addCleanup(lambda: self.engine.__dict__.pop("_offscreen_log", None))

    def away_and_back(self, ticks, x=530.0, y=530.0):
        h = self.engine.state.h_tensor
        dormancy.refresh(self.engine)                                  # slot 1 goes dormant
        self.engine.tick += ticks
        h[1, cfg.X], h[1, cfg.Y] = x, y                                # its chunk is integrated again
        dormancy.refresh(self.engine)

    def place_food(self, x, y, stock, gain=0.0, cap=None):
        m = self.engine.state.m_tensor
        slot = int((m[:, cfg.M_TYPE] == 0).nonzero(as_tuple=False)[-1])
        m[slot] = 0.0
        m[slot, cfg.CX], m[slot, cfg.CY], m[slot, cfg.M_TYPE] = x, y, float(cfg.M_RESOURCE_NODE)
        m[slot, cfg.M_NODE_KIND], m[slot, cfg.M_RESOURCE_FOOD], m[slot, cfg.M_GROWTH_RATE] = 1.0, stock, gain
        m[slot, cfg.M_NODE_CAP] = stock if cap is None else cap
        self.engine._entity_uid_by_slot[slot] = "food_t"
        return slot


class EngineWakeTests(OffscreenFixture):
    async def test_flag_off_the_wake_is_todays_capped_catch_up(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER], h[1, cfg.HP] = 10.0, 100.0
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_OFFSCREEN")
            self.away_and_back(2000)
        self.assertEqual(float(h[1, cfg.HUNGER]), dormancy.CATCH_UP["hunger_cap"])
        self.assertEqual(float(h[1, cfg.HP]), 100.0)
        self.assertNotIn("_offscreen_log", self.engine.__dict__)

    async def test_without_food_the_resident_starves_while_away_and_the_normal_rule_removes_it(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER], h[1, cfg.THIRST], h[1, cfg.HP], h[1, cfg.H_AGE], h[1, cfg.H_LIFE_EXP] = 10.0, 0.0, 100.0, 20.0, 80.0
        self.away_and_back(2000)                                       # hunger 90 after 1600 ticks, then 400 ticks starving
        self.assertEqual(float(h[1, cfg.HUNGER]), 100.0)
        self.assertEqual(float(h[1, cfg.HP]), 0.0)
        deaths = [e for e in self.engine._offscreen_log if e["event"] == "death"]
        self.assertEqual([(e["uid"], e["cause"]) for e in deaths], [("h_t1", "starvation")])
        self.assertEqual((float(h[1, cfg.X]), float(h[1, cfg.Y])), (530.0, 530.0), "the coarse model never moves anyone")
        ctx = {"h_mask": h[:, cfg.TYPE] > 0}
        iat.instinct_hp_death(ctx, h, self.engine._pop_count)
        self.assertEqual(float(h[1, cfg.TYPE]), 0.0, "the normal hp death removes the row")

    async def test_a_fed_resident_wakes_at_the_set_point_and_the_food_row_is_debited_once(self):
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        h[1, cfg.HUNGER], h[1, cfg.HP], h[1, cfg.H_AGE], h[1, cfg.H_LIFE_EXP] = 60.0, 50.0, 20.0, 80.0
        food = self.place_food(540.0, 540.0, 40.0)                   # next to where the row wakes
        self.away_and_back(1000)
        self.assertEqual(float(h[1, cfg.HUNGER]), offscreen.CATCH_UP_V2["hunger_fed"])
        eaten = (60.0 + cfg.HUNGER_TICK_RATE * 1000 - offscreen.CATCH_UP_V2["hunger_fed"]) / cfg.EAT_HUNGER_RESTORE * cfg.EAT_RESOURCE_COST
        self.assertAlmostEqual(float(m[food, cfg.M_RESOURCE_FOOD]), 40.0 - eaten, places=4)
        self.assertAlmostEqual(float(h[1, cfg.H_AGE]), 20.0 + 1000 * dormancy._calendar.age_step(), places=3)
        after = h[1].clone(), float(m[food, cfg.M_RESOURCE_FOOD])
        dormancy.refresh(self.engine)                                  # awake now: nothing is applied a second time
        self.assertTrue(bool((h[1] == after[0]).all()))
        self.assertEqual(float(m[food, cfg.M_RESOURCE_FOOD]), after[1])

    async def test_a_roster_resident_away_50_days_without_food_rows_lives_on_the_sites(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER], h[1, cfg.THIRST], h[1, cfg.HP], h[1, cfg.H_AGE], h[1, cfg.H_LIFE_EXP] = 10.0, 10.0, 100.0, 20.0, 80.0
        with mock.patch.object(offscreen, "_loops_of", lambda engine, uid: (SITE, SITE) if uid == "h_t1" else (None, None)):
            self.away_and_back(50 * 2400)
        self.assertEqual(float(h[1, cfg.TYPE]), float(cfg.AGENT_TYPE_HUMAN), "alive: the row is still a human")
        self.assertGreater(float(h[1, cfg.HP]), 0.0)
        self.assertLess(float(h[1, cfg.HUNGER]), 30.0)
        self.assertLess(float(h[1, cfg.THIRST]), 30.0)

    async def test_a_food_row_far_from_the_group_is_not_eaten(self):
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        h[1, cfg.HUNGER] = 60.0
        far = self.place_food(9000.0, 9000.0, 40.0)
        self.away_and_back(1000)
        self.assertEqual(float(m[far, cfg.M_RESOURCE_FOOD]), 40.0)
        self.assertGreater(float(h[1, cfg.HUNGER]), 60.0, "unfed")

    async def test_old_age_while_away_is_applied_and_the_normal_rule_removes_the_row(self):
        h = self.engine.state.h_tensor
        h[1, cfg.H_AGE], h[1, cfg.H_LIFE_EXP], h[1, cfg.HP] = 79.5, 80.0, 100.0
        self.place_food(540.0, 540.0, 100.0)
        self.away_and_back(1000)                                       # legacy: one life-year per 600 ticks
        self.assertGreater(float(h[1, cfg.H_AGE]), 80.0)
        self.assertEqual([(e["uid"], e["cause"]) for e in self.engine._offscreen_log if e["event"] == "death"], [("h_t1", "old_age")])
        iat.instinct_die({"h_mask": h[:, cfg.TYPE] > 0}, h, self.engine._pop_count)
        self.assertEqual(float(h[1, cfg.TYPE]), 0.0)

    async def test_a_save_while_dormant_changes_nothing(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER] = 60.0
        dormancy.refresh(self.engine)
        state = self.manager.snapshot()
        self.assertNotIn("offscreen", state, "option A saves nothing new")
        self.manager.load(state)
        self.engine.tick += 400
        h[1, cfg.X], h[1, cfg.Y] = 530.0, 530.0
        dormancy.refresh(self.engine)
        self.assertAlmostEqual(float(h[1, cfg.HUNGER]), 60.0 + cfg.HUNGER_TICK_RATE * 400, places=4)


ROSTER_RATES = offscreen.Rates(day_ticks=2400, hunger=0.05 * 0.015, thirst=0.07 * 0.015, starve_damage=2.0, thirst_damage=2.5, heal=0.3,
                               age_step=1.0 / 600.0, cooldown_decay=1.0 / 600.0)   # the starter village: legacy day, roster needs_scale 0.015
SITE = (30.0, 30.0)          # roster needs loop with a site: at the threshold 30 the resident walks there and the need goes back to 0
RATION = (30.0, 25.0)        # no site: a ration of 25 on the spot


def ticked(start, rate, ticks, threshold, drop, delay=0):
    """The roster loop stepped tick by tick (systems/roster/needs.py): the need rises; from the threshold a trip of ``delay`` ticks
    (walk + stand) during which it keeps rising, then it drops by ``drop`` (a site sets it to 0: drop = threshold). Returns (value, trips)."""
    value, trip, trips = float(start), None, 0
    for _ in range(int(ticks)):
        value += rate
        if trip is None and value >= threshold:
            trip = 0
        if trip is not None:
            if trip >= delay:
                value = 0.0 if drop >= threshold else value - drop
                trip, trips = None, trips + 1
            else:
                trip += 1
    return value, trips


class RosterLoopTests(unittest.TestCase):
    """R6.5-roster: a roster resident eats and drinks at the village sites (unlimited), so away it follows the loop in closed form."""

    def test_a_roster_resident_away_60_days_lives_on_the_sites(self):
        days = 60
        r = resident(hunger=10.0, thirst=20.0, hp=70.0, age_scale=0.05, hunger_loop=SITE, thirst_loop=SITE)   # the roster age scale
        out = offscreen.coarse_days([r], [offscreen.Food("n1", 50.0)], days, ROSTER_RATES)
        a = out.residents["a"]
        self.assertTrue(a.alive)
        self.assertEqual(out.deaths, [])
        self.assertEqual(out.foods["n1"], 50.0, "the sites are unlimited: no food row is drained")
        self.assertEqual(a.hp, 100.0, "never hungry enough to stop healing")
        ticks = days * ROSTER_RATES.day_ticks
        for value, start, rate in ((a.hunger, 10.0, ROSTER_RATES.hunger), (a.thirst, 20.0, ROSTER_RATES.thirst)):
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 30.0)
            exact, trips = ticked(start, rate, ticks, 30.0, 30.0)
            self.assertGreater(trips, 0, "the run crosses the threshold")
            self.assertAlmostEqual(value, exact, delta=rate * (trips + 1), msg="instant trips: the same loop, up to one tick per trip")
            for delay in (60, 300):                                    # stand ticks (food 60) and a walk: the approximation
                walked, trips = ticked(start, rate, ticks, 30.0, 30.0, delay)
                self.assertAlmostEqual(value, walked, delta=rate * (delay + 1) * (trips + 1),
                                       msg="within the walk and stand time of each trip")

    def test_without_a_site_the_ration_keeps_the_need_between_threshold_minus_ration_and_threshold(self):
        r = resident(hunger=29.0, thirst=0.0, age_scale=0.05, hunger_loop=RATION, thirst_loop=SITE)
        out = offscreen.coarse_days([r], [], 90, ROSTER_RATES)
        a = out.residents["a"]
        self.assertTrue(a.alive)
        self.assertGreaterEqual(a.hunger, 5.0)
        self.assertLess(a.hunger, 30.0)
        exact, trips = ticked(29.0, ROSTER_RATES.hunger, 90 * ROSTER_RATES.day_ticks, 30.0, 25.0)
        self.assertGreater(trips, 1)
        self.assertAlmostEqual(a.hunger, exact, delta=ROSTER_RATES.hunger * (trips + 1))

    def test_a_need_already_over_the_threshold_at_sleep_is_met_first(self):
        out = offscreen.coarse_days([resident(hunger=31.0, thirst=45.0, hunger_loop=SITE, thirst_loop=SITE)], [], 1, ROSTER_RATES)
        a = out.residents["a"]
        self.assertAlmostEqual(a.hunger, 31.0 + 1.8 - 30.0, places=6)
        self.assertAlmostEqual(a.thirst, (45.0 + 2.52 - 30.0) % 30.0, places=6)

    def test_a_non_roster_resident_in_the_same_group_keeps_the_fed_model(self):
        people = [resident("r", hunger=10.0, hunger_loop=SITE, thirst_loop=SITE), resident("x", hunger=60.0)]
        out = offscreen.coarse_days(people, [offscreen.Food("n1", 1.0)], 1, RATES)
        need = (60.0 + RATES.hunger * RATES.day_ticks - offscreen.CATCH_UP_V2["hunger_fed"]) / cfg.EAT_HUNGER_RESTORE
        fed = 1.0 / need
        self.assertAlmostEqual(out.residents["x"].hunger, 60.0 + 5.0 - fed * (60.0 + 5.0 - 30.0), places=6, msg="only x eats the row")
        self.assertAlmostEqual(out.residents["r"].hunger, 15.0, places=6)
        self.assertAlmostEqual(out.foods["n1"], 0.0, places=9)

    def test_loops_of_reads_the_roster_needs(self):
        roster = {"needs": {"threshold": 30, "ration": 25, "trip_timeout_ticks": 2400,
                            "water": {"anchor": "village:use_well", "ticks": 40}, "food": {"anchor": None, "ticks": 60}}}
        import systems.roster.driver as driver
        import systems.roster.needs as needs
        with mock.patch.object(driver, "roster_of", lambda engine, uid: (roster, {})), \
                mock.patch.object(needs, "site_position", lambda engine, n, kind, has: (1.0, 2.0) if n[kind]["anchor"] else None):
            self.assertEqual(offscreen._loops_of(object(), "h_1"), ((30.0, 25.0), (30.0, 30.0)))
        with mock.patch.object(driver, "roster_of", lambda engine, uid: (None, {})):
            self.assertEqual(offscreen._loops_of(object(), "h_1"), (None, None))

    def test_with_the_agent_ladder_and_market_balance_food_waits_for_the_ladder_limit(self):
        roster = {"driver": "agent", "needs": {"threshold": 30, "ration": 25, "trip_timeout_ticks": 2400,
                                               "water": {"anchor": "w", "ticks": 40}, "food": {"anchor": "f", "ticks": 60}}}
        import systems.roster.driver as driver
        import systems.roster.needs as needs
        from systems.actions import agent_driver, market_day
        with mock.patch.object(driver, "roster_of", lambda engine, uid: (roster, {})),                 mock.patch.object(needs, "site_position", lambda engine, n, kind, has: (1.0, 2.0)),                 mock.patch.object(agent_driver, "actions_enabled", lambda: True),                 mock.patch.object(agent_driver.ladder_module, "enabled", lambda: True),                 mock.patch.object(market_day, "balance_enabled", lambda: True):
            limit = float(agent_driver.LADDER_TIER0_HUNGER)
            self.assertEqual(offscreen._loops_of(object(), "h_1"), ((limit, limit), (30.0, 30.0)))
            with mock.patch.dict(os.environ, {agent_driver.LADDER_STARVE_ENV: "1"}):
                self.assertEqual(offscreen._loops_of(object(), "h_1"), (None, (30.0, 30.0)), "no ration at all: the fed model")


class BirthModelTests(unittest.TestCase):
    """D3 (b): births counted in closed form (pure part)."""

    def couple(self, **mother):
        values = dict(sex=1.0, age=25.0, hunger=20.0, thirst=10.0, hp=100.0)
        values.update(mother)
        return [resident("m", **values), resident("f", sex=0.0, age=27.0, hunger=20.0, thirst=10.0, hp=100.0)]

    def test_b1_a_ready_mother_gives_one_birth_per_life_year_of_cooldown(self):
        out = offscreen.coarse_days(self.couple(), [offscreen.Food("n1", 1e6)], 13, RATES, births_allowed=True, birth_p=1.0, seed=5)
        self.assertEqual([b["day"] for b in out.births], [0, 6, 12], "cooldown 1 life-year = 6 days of 100 ticks at 1/600 a tick")
        self.assertTrue(all(b["mother_uid"] == "m" and b["father_uid"] == "f" for b in out.births))
        for blocked in (dict(age=17.0), dict(infection=cfg.INFECTION_THRESHOLD, hp=40.0), dict(cooldown=50.0)):
            out = offscreen.coarse_days(self.couple(**blocked), [offscreen.Food("n1", 1e6)], 5, RATES, births_allowed=True, birth_p=1.0)
            self.assertEqual(out.births, [], blocked)
        hungry = offscreen.coarse_days(self.couple(hunger=60.0), [], 3, RATES, births_allowed=True, birth_p=1.0)
        self.assertEqual(hungry.births, [], "unfed: hunger over 55")
        alone = offscreen.coarse_days(self.couple()[:1], [offscreen.Food("n1", 1e6)], 5, RATES, births_allowed=True, birth_p=1.0)
        self.assertEqual(alone.births, [], "no ready male in the group")

    def test_b1_draws_are_deterministic_and_independent_of_order(self):
        people = self.couple() + [resident("m2", sex=1.0, age=30.0, hunger=20.0, thirst=10.0, hp=100.0)]
        a = offscreen.coarse_days(people, [offscreen.Food("n1", 1e6)], 40, RATES, births_allowed=True, birth_p=0.3, seed=11)
        b = offscreen.coarse_days(list(reversed(people)), [offscreen.Food("n1", 1e6)], 40, RATES, births_allowed=True, birth_p=0.3, seed=11)
        self.assertEqual(a.births, b.births)
        self.assertGreater(len(a.births), 0)
        other = offscreen.coarse_days(people, [offscreen.Food("n1", 1e6)], 40, RATES, births_allowed=True, birth_p=0.3, seed=12)
        self.assertNotEqual(a.births, other.births, "the world seed is part of the draw")

    def test_b2_a_roster_world_has_no_births_and_nothing_else_changes(self):
        people = self.couple(age=10.0)                             # no ready mother: births allowed or not gives the same world
        allowed = offscreen.coarse_days(people, [offscreen.Food("n1", 50.0)], 9, RATES, births_allowed=True, birth_p=1.0)
        roster = offscreen.coarse_days(people, [offscreen.Food("n1", 50.0)], 9, RATES, births_allowed=False, birth_p=1.0)
        self.assertEqual((allowed.residents, allowed.foods, allowed.deaths), (roster.residents, roster.foods, roster.deaths))
        ready = offscreen.coarse_days(self.couple(), [offscreen.Food("n1", 1e6)], 9, RATES, births_allowed=False, birth_p=1.0)
        self.assertEqual(ready.births, [])

    def test_b3_a_child_born_while_away_ages_and_lives_by_the_same_rules(self):
        out = offscreen.coarse_days(self.couple(), [offscreen.Food("n1", 1e6)], 3, RATES, births_allowed=True, birth_p=1.0)
        child = out.residents[out.births[0]["key"]]
        self.assertAlmostEqual(child.age, 2 * RATES.day_ticks * RATES.age_step, places=9, msg="born at the end of day 0, two days old")
        self.assertAlmostEqual(child.hunger, 2 * RATES.hunger * RATES.day_ticks, places=9, msg="born at 0: rises, under the set point")
        starving = offscreen.coarse_days(self.couple(), [offscreen.Food("n1", MEAL * 2)], 40, RATES, births_allowed=True, birth_p=1.0)
        child = starving.residents[starving.births[0]["key"]]
        self.assertFalse(child.alive)
        self.assertIn((child.uid, starving.deaths[[d[0] for d in starving.deaths].index(child.uid)][1], "starvation"), starving.deaths)


class BirthFixture(OffscreenFixture):
    """A dormant couple (mother h_t1, father h_t2) away from the player, food near where they come back, p patched to 1."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        h = self.engine.state.h_tensor
        self.place_human(2, 3010.0, 500.0)                             # the father, dormant next to the mother
        self.engine._human_uid_by_slot[2] = "h_t2"
        for slot, sex, age in ((1, 1.0, 25.0), (2, 0.0, 27.0)):
            h[slot, cfg.H_SEX], h[slot, cfg.H_AGE], h[slot, cfg.H_LIFE_EXP], h[slot, cfg.HP], h[slot, cfg.H_STAMINA] = sex, age, 80.0, 100.0, 100.0
            h[slot, cfg.HUNGER], h[slot, cfg.THIRST] = 20.0, 10.0
        self.engine._pop_count[0] = int((h[:, cfg.TYPE] == float(cfg.AGENT_TYPE_HUMAN)).sum())
        patch = mock.patch.object(offscreen, "BIRTH_P_PER_READY_DAY", 1.0)
        patch.start()
        self.addCleanup(patch.stop)
        self.place_food(540.0, 540.0, 1e5)
        for key in ("_offscreen_pending", "_offscreen_counters", "_offscreen_cache"):
            self.addCleanup(lambda key=key: self.engine.__dict__.pop(key, None))

    def both_back(self, ticks):
        h = self.engine.state.h_tensor
        dormancy.refresh(self.engine)
        self.engine.tick += ticks
        h[1, cfg.X], h[1, cfg.Y] = 530.0, 530.0
        h[2, cfg.X], h[2, cfg.Y] = 536.0, 530.0
        dormancy.refresh(self.engine)

    def children(self):
        h = self.engine.state.h_tensor
        return [s for s in range(3, h.shape[0]) if float(h[s, cfg.TYPE]) == float(cfg.AGENT_TYPE_HUMAN)]


class BirthEngineTests(BirthFixture):
    """D3 (b): births materialised at wake next to the mother (engine part)."""

    async def test_b4_the_child_appears_next_to_the_mother_with_a_reserved_uid_and_parent_links(self):
        before = self.engine._next_human_uid
        self.both_back(2400)                                           # one legacy day: the mother is ready, p = 1
        kids = self.children()
        self.assertEqual(len(kids), 1)
        child, h = kids[0], self.engine.state.h_tensor
        self.assertLessEqual(abs(float(h[child, cfg.X]) - 530.0), 4.0)
        self.assertLessEqual(abs(float(h[child, cfg.Y]) - 530.0), 4.0)
        self.assertTrue(offscreen._integrated(self.engine, float(h[child, cfg.X]), float(h[child, cfg.Y])))
        self.assertEqual(self.engine._human_uid_by_slot[child], f"h_{before:06d}")
        self.assertEqual(self.engine._pending_birth_links_by_slot[child]["parent_ids"], ["h_t1", "h_t2"])
        self.assertAlmostEqual(float(h[1, cfg.H_COOLDOWN]), 1.0, places=5)
        self.assertEqual(self.engine._offscreen_counters, {"births": 1, "births_placed": 1, "births_deferred": 0})
        self.assertEqual(self.engine._offscreen_pending, [])

    async def test_b5_no_slot_defers_the_birth_and_a_freed_slot_takes_it_later(self):
        h = self.engine.state.h_tensor
        for slot in range(3, h.shape[0]):                              # fill every free row (in the player's chunk: never dormant)
            self.place_human(slot, 525.0, 525.0)
        self.engine._pop_count[0] = h.shape[0]
        self.both_back(2400)
        self.assertEqual(len(self.engine._offscreen_pending), 1)
        self.assertEqual(self.engine._offscreen_pending[0]["reason"], "no_slot")
        self.assertEqual(self.engine._offscreen_counters["births_deferred"], 1)
        born_day, uid = self.engine._offscreen_pending[0]["day"], self.engine._offscreen_pending[0]["uid"]
        h[50] = 0.0
        self.engine._pop_count[0] -= 1
        self.engine.tick += offscreen.RETRY_EVERY - self.engine.tick % offscreen.RETRY_EVERY
        dormancy.refresh(self.engine)
        self.assertEqual(self.engine._offscreen_pending, [])
        self.assertEqual(self.engine._human_uid_by_slot[50], uid)
        self.assertEqual(self.engine._pending_birth_links_by_slot[50]["born_day"], born_day)
        self.assertGreater(float(h[50, cfg.H_AGE]), 0.0, "the delay counts towards its age")

    async def test_b6_no_standable_point_defers_and_nothing_is_dropped(self):
        import systems.movement.spatial as spatial
        with mock.patch.object(spatial, "standable_spawn_point", lambda engine, x, y: None):
            self.both_back(2400)
        self.assertEqual([b["reason"] for b in self.engine._offscreen_pending], ["no_place"])
        self.assertEqual(self.children(), [])
        self.engine.tick += offscreen.RETRY_EVERY - self.engine.tick % offscreen.RETRY_EVERY
        dormancy.refresh(self.engine)
        self.assertEqual(len(self.children()), 1)

    async def test_b8_flag_off_no_births(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_OFFSCREEN")
            self.both_back(2400)
        self.assertEqual(self.children(), [])
        self.assertNotIn("_offscreen_pending", self.engine.__dict__)


class BirthSaveTests(BirthFixture):
    """B7 and the orchestrator's three save tests: the optional window key ``offscreen``."""

    def capture(self):
        from persistence import codec, world_snapshot
        import map_geo
        return world_snapshot.capture(self.engine, map_geo)

    async def defer_one(self):
        import systems.movement.spatial as spatial
        with mock.patch.object(spatial, "standable_spawn_point", lambda engine, x, y: None):
            self.both_back(2400)
        self.assertEqual(len(self.engine._offscreen_pending), 1)

    async def test_a_save_with_nothing_pending_is_byte_identical_flag_on_and_off(self):
        on = self.capture()
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_OFFSCREEN")
            off = self.capture()
        self.assertEqual(on, off)
        from persistence import codec
        self.assertNotIn("offscreen", codec.loads(on)["window"])

    async def test_a_round_trip_keeps_the_pending_births(self):
        from persistence import codec, world_snapshot
        await self.defer_one()
        pending = [dict(b) for b in self.engine._offscreen_pending]
        payload = codec.loads(self.capture())
        section = payload["window"]["offscreen"]
        self.assertEqual(len(section["pending_births"]), 1)
        self.assertEqual([(b["uid"], b["day"]) for b in section["pending_births"]], [(b["uid"], b["day"]) for b in pending])
        world_snapshot._validate_window(payload, self.engine)
        self.engine._offscreen_pending = []
        offscreen.load(self.engine, section)
        self.assertEqual(self.engine._offscreen_pending, pending)
        self.engine.tick += offscreen.RETRY_EVERY - self.engine.tick % offscreen.RETRY_EVERY
        dormancy.refresh(self.engine)
        self.assertEqual(self.engine._offscreen_pending, [])
        self.assertIn(pending[0]["uid"], self.engine._human_uid_by_slot)

    async def test_a_save_with_pending_births_is_refused_without_the_flag(self):
        from persistence import codec, world_snapshot
        await self.defer_one()
        payload = codec.loads(self.capture())
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_OFFSCREEN")
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(payload, self.engine)
        self.assertIn("EDEN_OFFSCREEN=1", str(caught.exception))
        self.assertEqual(str(caught.exception), world_snapshot.REFUSAL_OFFSCREEN_WITHOUT)


class FlagTests(unittest.TestCase):
    def test_offscreen_needs_dormancy(self):
        with mock.patch.dict(os.environ, {"EDEN_OFFSCREEN": "1", "EDEN_WINDOW": "1"}):
            os.environ.pop("EDEN_WINDOW_DORMANCY", None)
            self.assertFalse(offscreen.enabled())
        with mock.patch.dict(os.environ, {"EDEN_OFFSCREEN": "1", "EDEN_WINDOW": "1", "EDEN_WINDOW_DORMANCY": "1"}):
            self.assertTrue(offscreen.enabled())
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1", "EDEN_WINDOW_DORMANCY": "1"}):
            os.environ.pop("EDEN_OFFSCREEN", None)
            self.assertFalse(offscreen.enabled())

    def test_offscreen_without_dormancy_refuses_to_boot(self):
        from harness import engine_hooks as eh, spaces
        from simulation.dispatch import Dispatcher
        with mock.patch.dict(os.environ, {"EDEN_OFFSCREEN": "1", "EDEN_WINDOW": "1"}):
            os.environ.pop("EDEN_WINDOW_DORMANCY", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(Dispatcher())
            self.assertIn("EDEN_WINDOW_DORMANCY=1", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
