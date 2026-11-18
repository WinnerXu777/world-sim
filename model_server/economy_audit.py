"""Scenario-only observation of actual Tier 0 food calls, restored on exit."""
from collections import Counter


class FoodRationAudit:
    def __init__(self, engine, names, driver, tail_from):
        self.engine, self.names, self.driver, self.tail_from = engine, names, driver, tail_from
        self.total, self.tail, self.reasons, self.errands = Counter(), Counter(), Counter(), Counter()
        self.water_ticks, self.samples = set(), []

    def __enter__(self):
        import genesis_config as cfg
        from systems.roster import needs
        self.module, self.original = needs, needs.ration

        def observe(engine, slot, kind, settings, state, human_id):
            pair = (int(engine.tick), human_id)
            if kind == "water":
                self.water_ticks.add(pair)
            if kind == "food":
                key = self.names.get(human_id, human_id)
                self.total[key] += 1
                if int(engine.tick) > self.tail_from:
                    self.tail[key] += 1
                hunger = float(engine.state.h_tensor[slot, cfg.HUNGER])
                reason = "hunger_floor" if hunger >= 90 else ("thirst_then_food" if pair in self.water_ticks else "below_floor_other")
                self.reasons[reason] += 1
                errand = self.driver.ladder.errands.get(human_id)
                self.errands[errand.purpose if errand else "none"] += 1
                if len(self.samples) < 100:
                    self.samples.append({"tick": int(engine.tick), "who": key, "hunger": round(hunger, 3), "reason": reason,
                                         "errand": errand.purpose if errand else ""})
            return self.original(engine, slot, kind, settings, state, human_id)

        needs.ration = observe
        return self

    def __exit__(self, *exc):
        self.module.ration = self.original

    def summary(self):
        return {"total": dict(self.total), "tail": dict(self.tail), "reasons": dict(self.reasons),
                "errand_purposes": dict(self.errands), "samples": self.samples}
