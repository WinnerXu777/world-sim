"""1008 window: with a controlled (player) human the re-base follows THAT human, not the mean of all residents, so the player can walk away from
a village; the residents left behind keep their absolute positions and slots and become integrated again when the window returns. No controlled
human: the mean rule is unchanged (test_harness_window_rebase)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402

SIZE = 256.0
VILLAGE = [(520.0, 520.0), (540.0, 520.0), (520.0, 540.0), (500.0, 500.0)]


class FollowTests(WindowFixture):
    def setup_world(self):
        for slot, (x, y) in enumerate(VILLAGE):
            self.place_human(slot, x, y)
        self.place_human(4, 530.0, 530.0)                                  # the player, in the village
        self.engine.player_control.sessions_by_controller["p"] = {"target_kind": "human", "slot": 4, "controller_id": "p"}
        self.addCleanup(self.engine.player_control.sessions_by_controller.pop, "p", None)
        self.run_ticks(30)

    def absolute(self, slot):
        h = self.engine.state.h_tensor
        ox, oy = self.manager.frame.origin
        return ox * SIZE + float(h[slot, cfg.X]), oy * SIZE + float(h[slot, cfg.Y])

    def walk_player(self, to_abs_x, ticks=90):
        h = self.engine.state.h_tensor
        ox, _ = self.manager.frame.origin
        h[4, cfg.X] = to_abs_x - ox * SIZE
        self.run_ticks(ticks)

    async def test_the_origin_follows_the_player_not_the_mean(self):
        self.setup_world()
        self.assertEqual(self.manager.frame.origin, (0, 0))
        self.walk_player(6 * SIZE + 100.0)                                 # chunk 6: the mean of five humans is chunk 2, no re-base by the mean rule
        self.assertEqual(self.manager.frame.origin[0], 6)
        self.assertEqual(self.manager.epoch, 1)
        self.assertAlmostEqual(self.absolute(4)[0], 6 * SIZE + 100.0, places=2)

    async def test_the_residents_left_behind_keep_their_absolute_positions_and_slots(self):
        self.setup_world()
        uids = {slot: self.engine._human_uid_by_slot[slot] for slot in range(4)}
        before = {slot: self.absolute(slot) for slot in range(4)}
        self.walk_player(9 * SIZE + 100.0)
        self.assertEqual(self.manager.frame.origin[0], 9)
        for slot in range(4):
            self.assertEqual(self.engine._human_uid_by_slot[slot], uids[slot])
            ax, ay = self.absolute(slot)
            self.assertAlmostEqual(ax, before[slot][0], places=2, msg=slot)
            self.assertAlmostEqual(ay, before[slot][1], places=2, msg=slot)
        self.assertLess(float(self.engine.state.h_tensor[0, cfg.X]), -1280.0, "left outside the frame, as a plain negative local coordinate")
        self.assertNotIn(ChunkCoord(2, 2), self.manager.chunks, "the village chunks are outside the frame and not integrated")
        self.assertIn(ChunkCoord(9, 2), self.manager.chunks)

    async def test_walking_back_integrates_the_village_again(self):
        self.setup_world()
        self.walk_player(9 * SIZE + 100.0)
        before = [self.absolute(slot) for slot in range(4)]
        self.walk_player(2 * SIZE + 100.0, ticks=80)
        self.assertLessEqual(abs(self.manager.frame.origin[0] - 2), 1)
        self.assertIn(ChunkCoord(2, 2), self.manager.chunks)
        for slot in range(4):
            self.assertEqual(tuple(round(v, 2) for v in self.absolute(slot)), tuple(round(v, 2) for v in before[slot]))

    async def test_no_player_keeps_the_mean_rule(self):
        self.setup_world()
        self.engine.player_control.sessions_by_controller.pop("p")
        self.walk_player(6 * SIZE + 100.0)
        self.assertEqual(self.manager.frame.origin, (0, 0), "the mean of the five humans is still near chunk 2")

    async def test_a_parked_avatar_keeps_the_window_after_the_session_lapses(self):
        self.setup_world()
        self.engine._human_uid_by_slot[4] = "h_avatar"
        self.engine._incarnated_human_by_controller["p"] = {"human_id": "h_avatar"}
        self.addCleanup(self.engine._incarnated_human_by_controller.pop, "p", None)
        self.engine.player_control.sessions_by_controller.pop("p")      # the session timed out; the body is still the player's
        self.assertEqual(self.manager.controlled_slots(), [4])
        self.walk_player(6 * SIZE + 100.0)
        self.assertEqual(self.manager.frame.origin[0], 6)

    async def test_a_player_in_an_interior_falls_back_to_the_mean(self):
        self.setup_world()
        self.engine.state.h_tensor[4, cfg.H_SPACE] = 1.0
        self.assertEqual(self.manager.controlled_actors(), [])


if __name__ == "__main__":
    unittest.main()
