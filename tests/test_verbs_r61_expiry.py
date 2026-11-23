import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from test_actions_runner import Scene
from systems.actions.r61 import invitations_of
from systems.roster.install import install_smith_loop, invitation_expiry_hook
from simulation.dispatch import Dispatcher


class ExpiryTests(unittest.TestCase):
    def test_install_off_and_on(self):
        with patch.dict(os.environ, {"EDEN_VERBS_R61": "0"}):
            off = Dispatcher()
            install_smith_loop(off)
            before = [[name for name, _ in hooks] for hooks in (off.genesis_hooks, off.step_hooks, off.post_step_hooks)]
            self.assertEqual(before, [["roster_apply"], ["roster_driver", "agent_driver", "motion_checkpoint"], ["motion_limits", "commission_tick", "god_weather_expiry"]])
        with patch.dict(os.environ, {"EDEN_VERBS_R61": "1"}):
            on = Dispatcher()
            install_smith_loop(on)
            install_smith_loop(on)
            self.assertEqual([name for name, _ in on.step_hooks], ["roster_driver", "agent_driver", "invitation_expiry", "motion_checkpoint"])
            self.assertEqual([name for name, _ in on.post_step_hooks], before[2])
            self.assertEqual([name for name, _ in on.genesis_hooks], before[0])

    def test_hook_expires_without_agent_residents(self):
        with patch.dict(os.environ, {"EDEN_VERBS_R61": "1"}):
            scene = Scene()
            pending = invitations_of(scene.services).open("h_a", "h_b", "v:bed", 0)
            result = scene.runner.run("h_a", "invite", {"target": "h_b", "place": "v:bed"})
            accepted = scene.services._r61_invitations.records[-1]
            engine = SimpleNamespace(_r61_invitations=scene.services._r61_invitations, tick=60)
            with patch("systems.actions.agent_driver.driver_of", return_value=SimpleNamespace(runner=lambda engine: scene.runner)):
                invitation_expiry_hook(engine)
                invitation_expiry_hook(engine)
            self.assertEqual((pending["state"], accepted["state"]), ("expired", "expired"))
            self.assertEqual(scene.records["h_b"]["tasks"], [])
            self.assertEqual([e.type for e in scene.world.events.events()].count("invitation_expired"), 2)
            self.assertTrue(result.ok)

    def test_queue_failure_declines(self):
        with patch.dict(os.environ, {"EDEN_VERBS_R61": "1"}):
            scene = Scene()
            with patch.object(scene.runner.record_ops, "execute", return_value={"ok": False, "reason": "blocked"}):
                result = scene.runner.run("h_a", "invite", {"target": "h_b", "place": "v:bed"})
            self.assertEqual(result.ops[0]["answer"], "declined")
            self.assertEqual(result.ops[0]["invitation"]["reason"], "no_route")
            events = scene.world.events.events()
            self.assertNotIn("invitation_accepted", [e.type for e in events])
            event = next(e for e in events if e.type == "invitation_declined")
            self.assertEqual(event.payload["reason"], "no_route")
            self.assertFalse(scene.records["h_b"].get("tasks"))

if __name__ == "__main__":
    unittest.main()
