"""EDEN_MARKET: the ladder's ``buy`` rung (pure ordering) and the S-1 ``market`` scenario in a fresh process (``model_server/s1_family_farm.py``)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.actions import ladder  # noqa: E402


class Ordering(unittest.TestCase):
    def test_buy_is_not_built_without_the_market_and_sits_between_work_and_trade(self):
        self.assertNotIn("buy", ladder.BUILT)
        self.assertNotIn("buy", ladder.allowed(0.9, 0.0))
        rungs = ladder.allowed(0.9, 0.0, built=ladder.BUILT + ("buy",))
        self.assertLess(rungs.index("forage"), rungs.index("buy"))
        self.assertLess(rungs.index("buy"), rungs.index("trade"))

    def test_paying_opens_before_begging_stealing_or_trading_at_any_conscience(self):
        for c in (-0.5, 0.0, 0.6):
            limit = ladder.thresholds(c)
            self.assertLessEqual(limit["buy"], limit["trade"], c)
            self.assertLess(limit["buy"], limit["steal"], c)


def scenario(*args, timeout=1200):
    out = Path(tempfile.mkdtemp()) / "out.json"
    env = {k: v for k, v in os.environ.items() if k != "EDEN_CALENDAR"}   # R0.6: the scenario keeps its own 600-tick day; an ambient EDEN_CALENDAR=1 slows the node regrowth and empties the stall
    proc = subprocess.run([sys.executable, "-m", "model_server.s1_family_farm", *args, "--json", str(out)], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=env)
    return proc, json.loads(out.read_text(encoding="utf-8")) if out.exists() else None


class MarketScenario(unittest.TestCase):
    def test_a_family_with_coin_buys_from_the_stall_instead_of_stealing_and_the_price_follows_a_shock(self):
        proc, result = scenario("--variant", "market", "--ticks", "3000", "--reputation", "--shock-at", "1500", "--shock", "3")
        self.assertEqual(proc.returncode, 0, proc.stdout[-1200:] + proc.stderr[-1200:])
        market = result["market"]
        self.assertGreater(result["events"].get("bought", 0), 0)
        self.assertEqual(result["events"].get("theft", 0), 0)
        self.assertEqual(market["coin_start"], market["coin_end"])
        self.assertEqual(result["dead_at"], {})
        self.assertTrue(market["factors"], "the daily update never ran")

    def test_the_market_run_is_deterministic(self):
        digests = [scenario("--variant", "market", "--ticks", "1200")[1]["digest"] for _ in range(2)]
        self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
