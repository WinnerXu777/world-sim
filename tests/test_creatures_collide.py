"""1008 Phase 2 step 4b (decision CREATURE-KERNEL): creature moves go through the walls humans slide against, and a wall stops a blow.

Pure tests of ``collide.slide_many`` (tangent slide, no tunnelling, margin/embedded starts), then engine tests on the window fixture of the kernel tests: a closed room that a skeleton
cannot enter (with a door-gap control that it can), the blow gate, built ``M_WALL`` rows, water for land / swim / fly classes, and the pocket (space != 0) staying out of reach."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_kernel import HOME, NIGHT, KernelFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.creatures import collide, table  # noqa: E402
from harness.window import WINDOW_FRAME  # noqa: E402


def box(x0, y0, x1, y1):
    return [x0, y0, x1, y1]


def boxes_of(*rows):
    return torch.tensor(rows, dtype=torch.float64)


def move(start, desired, boxes):
    out = collide.slide_many(torch.tensor([start], dtype=torch.float64), torch.tensor([desired], dtype=torch.float64), boxes)
    return tuple(float(v) for v in out[0])


R = collide.RADIUS
WALL = boxes_of(box(100.0, 90.0, 104.0, 110.0))


class SlideManyTests(unittest.TestCase):
    def test_the_constants_follow_the_generator(self):
        from systems.worldgen import spec
        self.assertEqual(collide.TERRAIN_WATER, spec.TERRAIN_WATER)
        self.assertEqual(collide.FOOT_WATER, spec.FOOT_WATER)

    def test_a_creature_stops_at_the_inflated_face(self):
        x, y = move((90.0, 100.0), (110.0, 100.0), WALL)
        self.assertAlmostEqual(x, 100.0 - R)
        self.assertAlmostEqual(y, 100.0)

    def test_the_tangent_component_survives(self):
        x, y = move((90.0, 100.0), (110.0, 130.0), WALL)
        self.assertAlmostEqual(x, 100.0 - R)
        self.assertAlmostEqual(y, 130.0, msg="x is cut at the face, y moves on")

    def test_the_far_side_is_blocked_too(self):
        x, y = move((110.0, 100.0), (90.0, 100.0), WALL)
        self.assertAlmostEqual(x, 104.0 + R)

    def test_a_long_step_does_not_tunnel(self):
        x, _ = move((60.0, 100.0), (160.0, 100.0), WALL)
        self.assertAlmostEqual(x, 100.0 - R)

    def test_open_ground_is_untouched(self):
        self.assertEqual(move((10.0, 10.0), (14.0, 11.0), WALL), (14.0, 11.0))
        self.assertEqual(move((10.0, 10.0), (14.0, 11.0), boxes_of()), (14.0, 11.0))

    def test_a_start_in_the_margin_may_leave_but_never_enters_the_wall(self):
        x, _ = move((99.8, 100.0), (103.0, 100.0), WALL)
        self.assertLessEqual(x, 100.0, "stays out of the raw box")
        x, _ = move((99.8, 100.0), (95.0, 100.0), WALL)
        self.assertAlmostEqual(x, 95.0, msg="free to step away")

    def test_a_start_inside_a_wall_walks_out(self):
        self.assertEqual(move((102.0, 100.0), (95.0, 100.0), WALL), (95.0, 100.0))

    def test_rows_are_independent(self):
        start = torch.tensor([[90.0, 100.0], [10.0, 10.0]], dtype=torch.float64)
        desired = torch.tensor([[110.0, 100.0], [14.0, 11.0]], dtype=torch.float64)
        out = collide.slide_many(start, desired, WALL)
        self.assertAlmostEqual(float(out[0, 0]), 100.0 - R)
        self.assertEqual(out[1].tolist(), [14.0, 11.0])

    def test_a_pocket_box_pair_holds_a_closed_room(self):
        room = boxes_of(box(0, 0, 20, 2), box(0, 18, 20, 20), box(0, 0, 2, 20), box(18, 0, 20, 20))
        for start, goal in (((-5.0, 10.0), (10.0, 10.0)), ((25.0, 10.0), (10.0, 10.0)), ((10.0, -5.0), (10.0, 10.0)), ((10.0, 25.0), (10.0, 10.0))):
            x, y = start
            for _ in range(30):
                x, y = move((x, y), (x + (goal[0] - x) * 0.3, y + (goal[1] - y) * 0.3), room)
            self.assertFalse(2.0 < x < 18.0 and 2.0 < y < 18.0, (start, x, y))


class WorldFixture(KernelFixture):
    def set_boxes(self, *rows):
        self._revision = getattr(self, "_revision", 0) + 1
        self.engine._window_contract = {"boxes": [{"id": f"t:w{i}", "min": [r[0], r[1]], "max": [r[2], r[3]], "height": 2.4} for i, r in enumerate(rows)],
                                       "bounds": None, "revision": f"test{self._revision}"}


class RoomTests(WorldFixture):
    ROOM = [(700.0, 700.0, 760.0, 704.0), (700.0, 756.0, 760.0, 760.0), (700.0, 700.0, 704.0, 760.0), (756.0, 700.0, 760.0, 760.0)]

    def inside(self, pos):
        return 704.0 < pos[0] < 756.0 and 704.0 < pos[1] < 756.0

    async def test_a_skeleton_cannot_enter_a_closed_room_and_cannot_hit_through_the_wall(self):
        self.set_boxes(*self.ROOM)
        self.human(0, 730.0, 730.0)
        slot = self.spawn("skeleton", 690.0, 730.0)
        self.go(400)
        self.assertFalse(self.inside(self.pos(slot)), self.pos(slot))
        self.assertEqual(float(self.engine.state.h_tensor[0, cfg.HP]), 100.0)

    async def test_the_same_room_with_a_door_is_entered(self):
        walls = list(self.ROOM)
        walls[2] = (700.0, 700.0, 704.0, 725.0)
        walls.append((700.0, 735.0, 704.0, 760.0))                                  # a 10-unit gap in the west wall
        self.set_boxes(*walls)
        self.human(0, 730.0, 730.0)
        slot = self.spawn("skeleton", 690.0, 730.0)
        self.assertTrue(self.go(400, until=lambda: self.inside(self.pos(slot))), "the control: a door lets it in")

    async def test_a_wall_between_attacker_and_victim_stops_the_blow(self):
        self.set_boxes((644.0, 600.0, 648.0, 680.0))
        self.human(0, 652.0, 640.0)
        slot = self.spawn("skeleton", 640.0, 640.0)
        self.go(30)
        self.assertEqual(float(self.engine.state.h_tensor[0, cfg.HP]), 100.0)
        self.set_boxes()
        self.assertTrue(self.go(60, until=lambda: float(self.engine.state.h_tensor[0, cfg.HP]) < 100.0), "the blow lands once the wall is gone")

    async def test_a_built_wall_row_is_a_wall_for_a_creature(self):
        uid = "built:wall1"
        (wall,) = self.manager.allocator.allocate([uid], [cfg.M_WALL], [700.0], [700.0], {cfg.M_HP: [100.0], cfg.SCALE: [10.0]})
        self.manager.allocator.owned.discard(wall)
        out, held = collide.resolve(self.engine, torch.tensor([[700.0, 690.0]]), torch.tensor([[700.0, 710.0]]), torch.tensor([collide.LAND]))
        self.assertAlmostEqual(float(out[0, 1]), 699.4 - R, places=3)
        self.assertEqual(held, 1)


class ClassTests(WorldFixture):
    def one(self, kind, start, desired):
        out, held = collide.resolve(self.engine, torch.tensor([start]), torch.tensor([desired]), torch.tensor([kind]))
        return tuple(float(v) for v in out[0]), held

    async def test_flyers_pass_the_generated_chunk_boxes_but_not_a_built_or_interior_box(self):
        self.engine._window_contract = {"boxes": [{"id": "c2_2:w0", "min": [700.0, 690.0], "max": [704.0, 710.0], "height": 2.4},
                                                  {"id": "interior:slab", "min": [800.0, 690.0], "max": [804.0, 710.0], "height": 2.4}], "bounds": None, "revision": "fly"}
        self.assertAlmostEqual(self.one(collide.LAND, (690.0, 700.0), (710.0, 700.0))[0][0], 700.0 - R, places=3)
        self.assertEqual(self.one(collide.FLY, (690.0, 700.0), (710.0, 700.0))[0], (710.0, 700.0))
        self.assertAlmostEqual(self.one(collide.FLY, (790.0, 700.0), (810.0, 700.0))[0][0], 800.0 - R, places=3)

    def water(self, x0, x1):
        width, height, (col0, row0) = WINDOW_FRAME
        grid = torch.zeros(height, width, dtype=torch.bool)
        grid[:, int(x0 // 8) - col0:int(x1 // 8) - col0] = True
        return mock.patch.object(collide, "_water_grid", return_value=(grid, col0, row0))

    async def test_land_creatures_do_not_step_into_water_swimmers_stay_in_it(self):
        with self.water(680.0, 720.0):
            self.assertEqual(self.one(collide.LAND, (670.0, 700.0), (684.0, 700.0))[0], (670.0, 700.0), "a land creature stays on the shore")
            self.assertEqual(self.one(collide.LAND, (690.0, 700.0), (696.0, 700.0))[0], (696.0, 700.0), "one already wading may move")
            self.assertEqual(self.one(collide.SWIM, (690.0, 700.0), (700.0, 700.0))[0], (700.0, 700.0))
            self.assertEqual(self.one(collide.SWIM, (710.0, 700.0), (730.0, 700.0))[0], (710.0, 700.0), "a swimmer does not leave the water")
            self.assertEqual(self.one(collide.FLY, (670.0, 700.0), (730.0, 700.0))[0], (730.0, 700.0))

    async def test_a_skeleton_chasing_across_a_lake_stops_on_the_shore(self):
        self.human(0, 760.0, 700.0)
        slot = self.spawn("skeleton", 650.0, 700.0)
        with self.water(680.0, 730.0):
            self.go(300)
        self.assertLess(self.pos(slot)[0], 680.0)


class PocketTests(WorldFixture):
    async def test_a_resident_in_a_pocket_is_out_of_reach(self):
        x0, y0 = 1920.0, 640.0                                                     # pool squares lie outside the window range
        self.human(0, x0, y0)
        self.engine.state.h_tensor[0, cfg.H_SPACE] = 1.0
        slot = self.spawn("skeleton", 1500.0, 640.0)
        self.go(200)
        self.assertLess(self.pos(slot)[0], 1536.0, "the frame limit holds")
        self.assertEqual(float(self.engine.state.h_tensor[0, cfg.HP]), 100.0)

    async def test_a_creature_row_inside_a_space_is_not_moved(self):
        slot = self.spawn("skeleton", 1900.0, 640.0)
        self.engine.state.m_tensor[slot, cfg.M_SPACE] = 1.0
        self.human(0, 1890.0, 640.0)
        self.engine.state.h_tensor[0, cfg.H_SPACE] = 1.0
        before = self.pos(slot)
        self.go(50)
        self.assertEqual(self.pos(slot), before)


if __name__ == "__main__":
    unittest.main()
