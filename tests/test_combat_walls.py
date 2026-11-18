import unittest

from test_startup_preservation import backend
from systems.movement.spatial import segment_blocked, wall_boxes
from systems.combat.intents import CombatIntent
from systems.combat.resolver import resolve_human_attack_intents


class CombatWallTests(unittest.TestCase):
    def test_segment_contact_embedding_and_clear_path(self):
        boxes = [{"min": [2, -1], "max": [4, 1]}]
        for start, end in (((0, 0), (6, 0)), ((3, 0), (6, 0)), ((0, 1), (2, 1)), ((3, 0), (3, 0))):
            self.assertTrue(segment_blocked(start, end, boxes))
            self.assertTrue(segment_blocked(end, start, boxes))
        for start, end in (((0, 2), (6, 2)), ((0, 0), (1, 0)), ((0, 2), (0, 2))):
            self.assertFalse(segment_blocked(start, end, boxes))

    def test_shared_resolver_blocks_human_and_animal_hits_until_wall_destroyed(self):
        h = backend.engine.state.h_tensor.clone().zero_()
        m = backend.engine.state.m_tensor.clone().zero_()
        h[:2, backend.TYPE] = backend.AGENT_TYPE_HUMAN
        h[:2, backend.HP] = 100
        h[:2, backend.H_STAMINA] = 100
        h[:2, backend.X] = 100
        h[0, backend.Y], h[1, backend.Y] = 99, 101
        m[0, backend.M_TYPE] = backend.M_WALL
        m[0, backend.M_HP] = 100
        m[0, backend.CX], m[0, backend.CY] = 100, 100
        self.assertEqual(wall_boxes(m)[0]["min"], [98, 99.4])
        animal_type = next(iter(backend.ANIMAL_TYPES))
        m[1, backend.M_TYPE] = animal_type
        m[1, backend.M_HP] = 100
        m[1, backend.CX], m[1, backend.CY] = 100, 101
        for kind in ("human", "entity"):
            intent = CombatIntent(source="manual", action="attack", attacker_kind="human", attacker_slot=0,
                                  target_kind=kind, target_slot=1, target_id="victim")
            result = resolve_human_attack_intents([intent], h, m, str(h.device))
            self.assertEqual(result["resolved"], 0)
            self.assertEqual(result["rejections"][0]["reason"], "blocked")
        self.assertEqual(float(h[1, backend.HP]), 100)
        self.assertEqual(float(m[1, backend.M_HP]), 100)
        self.assertEqual(float(h[0, backend.H_STAMINA]), 100)
        m[0, backend.M_HP] = 0
        result = resolve_human_attack_intents([intent], h, m, str(h.device))
        self.assertEqual(result["resolved"], 1)
        self.assertLess(float(m[1, backend.M_HP]), 100)
