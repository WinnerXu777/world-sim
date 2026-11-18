"""The S-1 ``commons`` scenario (market + credit + labour + justice, all on) in a fresh process (``model_server/s1_commons.py``)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scenario(*args, timeout=1200):
    out = Path(tempfile.mkdtemp()) / "out.json"
    proc = subprocess.run([sys.executable, "-m", "model_server.s1_commons", "--single", *args, "--json", str(out)], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    return proc, json.loads(out.read_text(encoding="utf-8")) if out.exists() else None


class Commons(unittest.TestCase):
    def test_a_scarce_village_with_a_thief_a_defaulter_and_a_guard_gets_through_without_deadlock(self):
        proc, r = scenario("--seed", "1008", "--ticks", "4000")
        self.assertEqual(proc.returncode, 0, proc.stdout[-1500:] + proc.stderr[-1500:])
        self.assertTrue(r["verdict"]["pass"], r["verdict"])
        self.assertEqual(r["dead_at"], {})
        self.assertEqual(r["silent_starvation"], [])
        self.assertEqual(r["items_start"].get("coin"), r["items_end"].get("coin"))
        loans = {row["borrower"]: row["status"] for row in r["loans"]["rows"]}
        self.assertEqual((loans["family_mara"], loans["family_tomas"]), ("repaid", "defaulted"))        # the honest debtor pays, the other one goes bad
        self.assertEqual([(c["thief"], c["authority"], c["status"]) for c in r["cases"]], [("family_tomas", "neighbour_elsa", "closed")])
        self.assertGreater(r["wages"]["paid"], 0)
        self.assertGreater(r["stall"]["sales"], 0)

    def test_the_run_is_deterministic_and_the_seed_matters(self):
        digests = [scenario("--seed", str(seed), "--ticks", "1500")[1]["digest"] for seed in (1008, 1008, 1)]
        self.assertEqual(digests[0], digests[1])
        self.assertNotEqual(digests[0], digests[2])


if __name__ == "__main__":
    unittest.main()
