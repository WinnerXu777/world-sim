"""1008 scaling (1008_spatial_index_gap.md): the human-to-human resolvers and ``_current_masks`` were rewritten to pre-filter with vector operations.
Pure equivalence: every test here runs the NEW method on the real engine against the OLD implementation kept below (verbatim bodies from before the
rewrite) over randomized worlds full of ties, equal distances, dead and half-built rows, missing ids, other spaces and NaN positions."""
import math
import random
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (isolated data root, imports map_test)
import genesis_config as cfg  # noqa: E402
from genesis_config import (AGENT_TYPE_HUMAN, AGGRESSION_THRESHOLD, ANIMAL_TYPES, ATTACK_STAMINA_COST, H_AGE, H_AGGRESSION, H_COOLDOWN, H_SEX,  # noqa: E402
                            H_SPACE, H_STAMINA, HP, HUNGER, MATURE_AGE, SAFE_REPRO_HP_MIN, SAFE_REPRO_HUNGER_MAX, SAFE_REPRO_STAMINA_MIN,
                            SAFE_REPRO_THIRST_MAX, SAFE_REPRO_THREAT_MAX, THIRST, THREAT, TYPE, X, Y)
from harness import human_query  # noqa: E402


# -- the old implementations, verbatim (self = the engine) --------------------------------------------------------------------
def old_slot_ready_for_mating(self, slot: int) -> bool:
    if int(self.state.h_tensor[slot, TYPE]) != int(AGENT_TYPE_HUMAN):
        return False
    if float(self.state.h_tensor[slot, H_AGE]) < float(MATURE_AGE):
        return False
    if float(self.state.h_tensor[slot, H_COOLDOWN]) > 0.0:
        return False
    if float(self.state.h_tensor[slot, HUNGER]) > float(SAFE_REPRO_HUNGER_MAX):
        return False
    if float(self.state.h_tensor[slot, THIRST]) > float(SAFE_REPRO_THIRST_MAX):
        return False
    if float(self.state.h_tensor[slot, THREAT]) > float(SAFE_REPRO_THREAT_MAX):
        return False
    if float(self.state.h_tensor[slot, HP]) < float(SAFE_REPRO_HP_MIN):
        return False
    if float(self.state.h_tensor[slot, H_STAMINA]) < float(SAFE_REPRO_STAMINA_MIN):
        return False
    return True


def old_resolve_mate_candidate(self, slot: int, *, radius: float = 72.0) -> dict[str, Any] | None:
    if not old_slot_ready_for_mating(self, slot):
        return None
    seeker_id = self._human_uid_by_slot[slot]
    seeker_sex = float(self.state.h_tensor[slot, H_SEX])
    seeker_x = float(self.state.h_tensor[slot, X])
    seeker_y = float(self.state.h_tensor[slot, Y])
    best: dict[str, Any] | None = None
    for other_slot in torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist():
        if other_slot == slot:
            continue
        if not old_slot_ready_for_mating(self, other_slot):
            continue
        if float(self.state.h_tensor[other_slot, H_SEX]) == seeker_sex:
            continue
        other_id = self._human_uid_by_slot[other_slot]
        if not other_id or other_id == seeker_id:
            continue
        dx = float(self.state.h_tensor[other_slot, X]) - seeker_x
        dy = float(self.state.h_tensor[other_slot, Y]) - seeker_y
        distance = math.hypot(dx, dy)
        if distance > float(radius):
            continue
        other_resident = self.resident_store.get(other_id)
        candidate = {
            "slot": int(other_slot),
            "human_id": str(other_id),
            "name": str((other_resident or {}).get("profile", {}).get("name", other_id)),
            "x": float(self.state.h_tensor[other_slot, X]),
            "y": float(self.state.h_tensor[other_slot, Y]),
            "distance": round(distance, 2),
        }
        if best is None or float(candidate["distance"]) < float(best["distance"]):
            best = candidate
    return best


def old_resolve_nearby_help_target(self, slot: int, *, radius: float = 72.0) -> dict[str, Any] | None:
    seeker_id = str(self._human_uid_by_slot[slot] or "").strip()
    if not seeker_id:
        return None
    px = float(self.state.h_tensor[slot, X])
    py = float(self.state.h_tensor[slot, Y])
    best: dict[str, Any] | None = None
    for other_slot in torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist():
        if int(other_slot) == int(slot):
            continue
        other_id = str(self._human_uid_by_slot[other_slot] or "").strip()
        if not other_id or other_id == seeker_id:
            continue
        dx = float(self.state.h_tensor[other_slot, X]) - px
        dy = float(self.state.h_tensor[other_slot, Y]) - py
        distance = math.hypot(dx, dy)
        if distance > float(radius):
            continue
        hp = float(self.state.h_tensor[other_slot, HP])
        threat = float(self.state.h_tensor[other_slot, THREAT])
        if hp >= 78.0 and threat < 42.0:
            continue
        resident = self.resident_store.get(other_id)
        candidate = {
            "slot": int(other_slot),
            "human_id": other_id,
            "name": str((resident or {}).get("profile", {}).get("name", other_id)),
            "x": float(self.state.h_tensor[other_slot, X]),
            "y": float(self.state.h_tensor[other_slot, Y]),
            "distance": round(distance, 2),
            "hp": hp,
            "threat": threat,
        }
        if best is None or (float(candidate["hp"]) < float(best["hp"])) or (
            float(candidate["hp"]) == float(best["hp"]) and float(candidate["distance"]) < float(best["distance"])
        ):
            best = candidate
    return best


def old_resolve_support_target(self, slot: int, *, radius: float = 96.0) -> dict[str, Any] | None:
    seeker_id = str(self._human_uid_by_slot[slot] or "").strip()
    if not seeker_id:
        return None
    px = float(self.state.h_tensor[slot, X])
    py = float(self.state.h_tensor[slot, Y])
    best: dict[str, Any] | None = None
    best_score = -10**9
    for other_slot in torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist():
        if int(other_slot) == int(slot):
            continue
        other_id = str(self._human_uid_by_slot[other_slot] or "").strip()
        if not other_id or other_id == seeker_id:
            continue
        if float(self.state.h_tensor[other_slot, HP]) <= 0.0:
            continue
        dx = float(self.state.h_tensor[other_slot, X]) - px
        dy = float(self.state.h_tensor[other_slot, Y]) - py
        distance = math.hypot(dx, dy)
        if distance > float(radius):
            continue
        resident = self.resident_store.get(other_id)
        occupation_kind = str((resident or {}).get("occupation", {}).get("kind", "")).strip()
        hp = float(self.state.h_tensor[other_slot, HP])
        threat = float(self.state.h_tensor[other_slot, THREAT])
        if hp < 45.0 or threat > 68.0:
            continue
        score = 100.0 - distance
        if occupation_kind == "guard":
            score += 18.0
        elif occupation_kind == "healer":
            score += 8.0
        score += max(0.0, hp - 60.0) * 0.1
        if best is None or score > best_score:
            best = {
                "slot": int(other_slot),
                "human_id": other_id,
                "name": str((resident or {}).get("profile", {}).get("name", other_id)),
                "x": float(self.state.h_tensor[other_slot, X]),
                "y": float(self.state.h_tensor[other_slot, Y]),
                "distance": round(distance, 2),
                "occupation_kind": occupation_kind,
            }
            best_score = score
    return best


def old_resolve_autonomous_human_attack_target(self, slot: int, *, radius: float = 28.0) -> dict[str, Any] | None:
    aggression = float(self.state.h_tensor[slot, H_AGGRESSION])
    threat = float(self.state.h_tensor[slot, THREAT])
    stamina = float(self.state.h_tensor[slot, H_STAMINA])
    if stamina < float(ATTACK_STAMINA_COST):
        return None
    if aggression < max(float(AGGRESSION_THRESHOLD) + 0.15, 0.65) and threat < 55.0:
        return None
    px = float(self.state.h_tensor[slot, X])
    py = float(self.state.h_tensor[slot, Y])
    best: dict[str, Any] | None = None
    for other_slot in torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist():
        if other_slot == slot:
            continue
        if float(self.state.h_tensor[other_slot, HP]) <= 0.0:
            continue
        human_id = self._human_uid_by_slot[other_slot]
        if not human_id:
            continue
        dx = float(self.state.h_tensor[other_slot, X]) - px
        dy = float(self.state.h_tensor[other_slot, Y]) - py
        distance = math.hypot(dx, dy)
        if distance > float(radius):
            continue
        resident = self.resident_store.get(human_id)
        candidate = {
            "target_kind": "human",
            "target_id": str(human_id),
            "name": str((resident or {}).get("profile", {}).get("name", human_id)),
            "distance": round(distance, 2),
            "reason": "aggression",
        }
        if best is None or float(candidate["distance"]) < float(best["distance"]):
            best = candidate
    return best


def old_current_masks(self):
    h_mask = self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN
    m = self.state.m_tensor
    entity_mask = m[:, cfg.M_TYPE] > 0
    a_mask = torch.zeros(cfg.MAX_ENTITIES, dtype=torch.bool, device=self.state.device)
    for t in ANIMAL_TYPES:
        a_mask |= (m[:, cfg.M_TYPE] == t)
    return h_mask, a_mask, entity_mask


# -- a randomized world --------------------------------------------------------------------------------------------------------
class RandomWorld:
    """Fills the real engine's tensors with a random crowd; ``resident_store.get`` is a deterministic function of the uid."""

    def __init__(self, engine, seed, size=None, grid=None, nan_rows=False):
        rng = random.Random(seed)
        self.engine = engine
        h = engine.state.h_tensor
        h[:] = 0.0
        engine._human_uid_by_slot[:] = [None] * len(engine._human_uid_by_slot)
        size = size if size is not None else rng.choice([0, 1, 2, 5, 12, 40, 90])
        grid = grid if grid is not None else rng.choice([4, 12, 40, 150])             # a small grid makes equal distances and equal positions common
        slots = rng.sample(range(h.shape[0]), min(size, h.shape[0]))
        self.slots = sorted(slots)
        friendly = rng.random() < 0.6                                              # most rows pass the mating readiness checks (else mate answers are rare)
        for slot in slots:
            h[slot, TYPE] = float(AGENT_TYPE_HUMAN) if rng.random() < 0.93 else 0.0     # a few freed rows between live ones
            h[slot, X] = float(rng.randrange(grid)) + (0.0 if rng.random() < 0.7 else rng.random())
            h[slot, Y] = float(rng.randrange(grid)) + (0.0 if rng.random() < 0.7 else rng.random())
            h[slot, HP] = rng.choice([0.0, 10.0, 44.0, 45.0, 60.0, 77.9, 78.0, 100.0] + [60.0, 100.0] * (6 if friendly else 0))
            h[slot, THREAT] = rng.choice([0.0, 10.0, 41.9, 42.0, 45.0, 55.0, 68.0, 70.0] + [10.0] * (8 if friendly else 0))
            h[slot, H_AGE] = rng.choice([5.0, 17.9, 18.0, 30.0] + [30.0] * (12 if friendly else 0))
            h[slot, H_COOLDOWN] = rng.choice([0.0, 0.0, 0.0, 5.0] + [0.0] * (12 if friendly else 0))
            h[slot, HUNGER] = rng.choice([0.0, 20.0, 55.0, 56.0] + [20.0] * (12 if friendly else 0))
            h[slot, THIRST] = rng.choice([0.0, 20.0, 55.0, 56.0] + [20.0] * (12 if friendly else 0))
            h[slot, H_STAMINA] = rng.choice([5.0, 24.0, 25.0, 100.0] + [100.0] * (12 if friendly else 0))
            h[slot, H_SEX] = float(rng.randrange(2))
            h[slot, H_AGGRESSION] = rng.choice([0.0, 0.6, 0.65, 0.9])
            h[slot, H_SPACE] = float(rng.choice([0, 0, 0, 1]))                          # the old loops never looked at the space
            engine._human_uid_by_slot[slot] = rng.choice([f"h_{slot}", f"h_{slot}", f"h_{slot}", None, "", "  ", "h_dup"])
        if nan_rows and slots:
            for slot in rng.sample(slots, min(2, len(slots))):
                h[slot, rng.choice([X, Y])] = float("nan")
            if rng.random() < 0.3:
                h[rng.choice(slots), X] = float("inf")
        kinds = ["guard", "healer", "farmer", ""]
        self.records = {}

        def get(uid):
            if uid not in self.records:
                local = random.Random(f"{seed}:{uid}")
                self.records[uid] = local.choice([None, {}, {"profile": {"name": f"N{uid}"}, "occupation": {"kind": local.choice(kinds)}}])
            return self.records[uid]
        self.get = get

    def patched(self):
        return mock.patch.object(self.engine.resident_store, "get", self.get)

    def queries(self, rng):
        extra = [s for s in range(0, self.engine.state.h_tensor.shape[0], 13)]                   # rows that are not live humans at all
        return self.slots + extra[:3]


RADII = (None, 0.0, 1.0, 28.0, 72.0, 96.0, 400.0)


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.engine = backend.engine
        self.engine.reset_world()
        self.addCleanup(self.engine.reset_world)

    def compare(self, new, old, seeds=100, **world_kw):
        checked = nonempty = 0
        for seed in range(seeds):
            world = RandomWorld(self.engine, seed, **world_kw)
            rng = random.Random(seed)
            with world.patched():
                for slot in world.queries(rng):
                    for radius in RADII:
                        kw = {} if radius is None else {"radius": radius}
                        expected = old(self.engine, slot, **kw)
                        got = new(slot, **kw)
                        self.assertEqual(repr(got), repr(expected), f"seed {seed} slot {slot} radius {radius}")
                        checked += 1
                        nonempty += expected is not None
        self.assertGreater(nonempty, checked // 40, "the generator must produce real answers, not only None")

    def test_mate_candidate(self):
        self.compare(self.engine._resolve_mate_candidate, old_resolve_mate_candidate)

    def test_nearby_help_target(self):
        self.compare(self.engine._resolve_nearby_help_target, old_resolve_nearby_help_target)

    def test_support_target(self):
        self.compare(self.engine._resolve_support_target, old_resolve_support_target)

    def test_attack_target(self):
        self.compare(self.engine._resolve_autonomous_human_attack_target, old_resolve_autonomous_human_attack_target)

    def test_nan_and_inf_positions_behave_as_before(self):
        for new, old in ((self.engine._resolve_mate_candidate, old_resolve_mate_candidate), (self.engine._resolve_nearby_help_target, old_resolve_nearby_help_target),
                         (self.engine._resolve_support_target, old_resolve_support_target)):
            self.compare(new, old, seeds=60, nan_rows=True)

    def test_an_empty_world_gives_none(self):
        world = RandomWorld(self.engine, 1, size=0)
        with world.patched():
            for new in (self.engine._resolve_mate_candidate, self.engine._resolve_nearby_help_target, self.engine._resolve_support_target,
                        self.engine._resolve_autonomous_human_attack_target):
                self.assertIsNone(new(3))

    def test_current_masks(self):
        m = self.engine.state.m_tensor
        rng = random.Random(5)
        for trial in range(40):
            m[:] = 0.0
            for row in rng.sample(range(m.shape[0]), rng.randrange(0, 200)):
                m[row, cfg.M_TYPE] = float(rng.choice([0, 1, 5, 19, 20, 39, 40, 41, 60, 79, 80, 81]))
            for got, want in zip(self.engine._current_masks(), old_current_masks(self.engine)):
                self.assertTrue(torch.equal(got, want), trial)
                self.assertEqual(got.dtype, want.dtype)
                self.assertEqual(got.shape, want.shape)


class PrefilterTests(unittest.TestCase):
    def test_the_prefilter_is_a_superset_of_the_exact_test(self):
        rng = random.Random(3)
        h = torch.zeros(300, 32)
        for _ in range(60):
            h[:, TYPE] = torch.tensor([float(rng.random() < 0.8) for _ in range(300)])
            h[:, X] = torch.tensor([rng.uniform(-50, 50) for _ in range(300)])
            h[:, Y] = torch.tensor([rng.uniform(-50, 50) for _ in range(300)])
            qx, qy, radius = rng.uniform(-50, 50), rng.uniform(-50, 50), rng.choice([0.0, 3.0, 28.0, 72.0])
            ordered = human_query.humans_within(h, qx, qy, radius, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN)
            got = set(ordered)
            self.assertEqual(ordered, sorted(ordered))
            exact = {i for i in range(300) if float(h[i, TYPE]) == 1.0 and not math.hypot(float(h[i, X]) - qx, float(h[i, Y]) - qy) > radius}
            self.assertTrue(exact <= got)

    def test_the_boundary_is_kept(self):
        h = torch.zeros(4, 32)
        h[:, TYPE] = 1.0
        h[1, X], h[1, Y] = 3.0, 4.0                                # exactly 5.0 away
        h[2, X], h[2, Y] = 3.0000001, 4.0                          # just past (float32 rounds this to 3.0, so it is also exactly on the line)
        self.assertIn(1, human_query.humans_within(h, 0.0, 0.0, 5.0, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN))


if __name__ == "__main__":
    unittest.main()
