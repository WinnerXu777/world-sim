import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from launch_config import LaunchConfig, PROJECT_ROOT


class LaunchConfigTests(unittest.TestCase):
    def test_defaults_preserve_legacy_data(self):
        config = LaunchConfig.from_env({})
        self.assertEqual(config.profile, "gameplay")
        self.assertEqual(config.host, "127.0.0.1")
        self.assertFalse(config.development)
        self.assertFalse(config.data_root.is_relative_to(PROJECT_ROOT / "Data_Storage"))

    def test_test_profiles_have_separate_roots_and_port(self):
        profiles = [LaunchConfig.from_env({"EDEN_PROFILE": p})
                    for p in ("gameplay", "render_fixture", "animation_qa")]
        self.assertEqual(len({p.data_root for p in profiles}), 3)
        self.assertNotEqual(profiles[0].port, profiles[1].port)

    def test_rejects_legacy_root_and_parent(self):
        for path in (PROJECT_ROOT, PROJECT_ROOT / "Data_Storage",
                     PROJECT_ROOT / "Data_Storage" / "ResidentAgents"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                LaunchConfig.from_env({"EDEN_DATA_ROOT": str(path)})

    def test_rejects_invalid_configuration(self):
        for env in ({"EDEN_PROFILE": "typo"}, {"EDEN_PORT": "0"}, {"EDEN_PORT": "65536"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                LaunchConfig.from_env(env)


if __name__ == "__main__":
    unittest.main()
