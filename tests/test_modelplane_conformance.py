"""tools/model_conformance.py: the bundled mock passes everything; broken servers fail the specific checks they should."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import model_conformance as mc
from model_server.app import create_app
from model_server.config import ServerConfig
from systems.modelplane.testing import ServerThread


mc.SCALE = 0.1   # 200 ms / 300 ms deadlines keep the faulty-server cases quick


def failures(report):
    return [name for name, ok, _ in report.rows if not ok]


class ConformanceTests(unittest.TestCase):
    def test_mock_server_passes_every_check_for_every_role(self):
        with ServerThread(create_app(ServerConfig())) as server:
            report = mc.run(server.url, list(mc.c.ROLES))
        self.assertEqual(failures(report), [])
        self.assertGreater(len(report.rows), 100)
        self.assertIn("checks passed", report.render())

    def test_rules_backend_passes_the_decide_role(self):
        config = ServerConfig(backends={role: ("rules", {}) for role in mc.c.ROLES})
        with ServerThread(create_app(config)) as server:
            self.assertEqual(failures(mc.run(server.url, ["decide"], quick=True)), [])

    def test_each_fault_is_caught_by_a_named_check(self):
        expectations = {"garbage": "schema, echo and result valid", "bad_result": "schema, echo and result valid",
                        "stale": "schema, echo and result valid", "error500": "answers"}
        for kind, needle in expectations.items():
            with self.subTest(kind=kind):
                with ServerThread(create_app(ServerConfig(faults=[{"kind": kind, "variant": 0}]))) as server:
                    report = mc.run(server.url, ["decide"], quick=True)
                self.assertFalse(report.passed)
                self.assertTrue(any(needle in name or "reply is JSON" in name for name in failures(report)), failures(report))

    def test_slow_server_fails_the_deadline_check_or_answers_504_cleanly(self):
        # slower than the request deadline: the server must answer 504 within it, which the "answers" check reports as a failure of
        # the valid request but the endpoint still ends cleanly (no hang).
        with ServerThread(create_app(ServerConfig(faults=[{"kind": "slow", "delay_ms": 2000}]))) as server:
            report = mc.run(server.url, ["decide"], quick=True)
        names = failures(report)
        self.assertTrue(any(n.startswith("decide: answers") for n in names))
        self.assertNotIn("decide deadline: ... and does not hang", names)

    def test_clef_stub_fails_and_says_why(self):
        config = ServerConfig(backends={"decide": ("clef", {}), **{r: ("mock", {}) for r in ("resident", "dialogue", "world")}})
        with ServerThread(create_app(config)) as server:
            report = mc.run(server.url, ["decide"], quick=True)
        self.assertFalse(report.passed)
        self.assertTrue(any("HTTP 501" in detail for _, ok, detail in report.rows if not ok), report.render())

    def test_unreachable_endpoint_reports_failures_instead_of_crashing(self):
        report = mc.run("http://127.0.0.1:9", ["decide"], quick=True)
        self.assertFalse(report.passed)

    def test_cli_exit_codes(self):
        self.assertEqual(mc.main(["--selftest", "--role", "decide", "--quick", "--deadline-scale", "0.1"]), 0)


if __name__ == "__main__":
    unittest.main()
