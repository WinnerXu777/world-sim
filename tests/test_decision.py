"""DecisionProvider contract, rules provider, service fallback/staleness, JSONL log, recorded replay."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.decision import (ClefDecisionProvider, DecisionError, DecisionLog, DecisionOption, DecisionProvider, DecisionRequest,
                              DecisionService, RecordedDecisionProvider, RulesDecisionProvider, read_log, softmax, summarize,
                              validate_probabilities, validate_request)


def options(*ids):
    return tuple(DecisionOption(i, f"option {i}", ("t",)) for i in ids)


def request(opts=("a", "b", "c"), topic="generic", state=None, job_id="j1", epoch="E1", revision=1, trigger="t:1", resident="h_1"):
    return DecisionRequest(job_id=job_id, resident_id=resident, world_epoch=epoch, state_revision=revision, tick=10,
                           trigger=trigger, question_kind="choice", options=options(*opts), state=state or {}, topic=topic)


class Broken(DecisionProvider):
    mode = "mock"

    def __init__(self, output=None, error=None):
        self.output, self.error = output, error

    def decide(self, request):
        if self.error:
            raise self.error
        return self.output


class ContractTests(unittest.TestCase):
    def test_validate_request(self):
        validate_request(request())
        with self.assertRaises(DecisionError):
            validate_request(request(opts=()))
        with self.assertRaises(DecisionError):
            validate_request(request(opts=("a", "a")))
        with self.assertRaises(DecisionError):
            validate_request(DecisionRequest("j", "h", "E", 1, 0, "t", "essay", options("a")))

    def test_probability_validation(self):
        opts = options("a", "b")
        self.assertEqual(validate_probabilities(opts, {"a": 0.25, "b": 0.75}), {"a": 0.25, "b": 0.75})
        for bad in ({"a": 1.0}, {"a": 0.5, "b": 0.5, "c": 0.0}, {"a": 0.5, "b": 0.6}, {"a": -0.1, "b": 1.1},
                    {"a": float("nan"), "b": 1.0}, {"a": "x", "b": 1.0}, {"a": True, "b": 0.0}, [0.5, 0.5], None):
            with self.subTest(bad=bad):
                with self.assertRaises(DecisionError):
                    validate_probabilities(opts, bad)

    def test_summary_top_and_margin_with_deterministic_ties(self):
        opts = options("a", "b", "c")
        self.assertEqual(summarize(opts, {"a": 0.2, "b": 0.5, "c": 0.3}), ("b", 0.5, 0.2))
        top, p, margin = summarize(opts, {"a": 0.4, "b": 0.4, "c": 0.2})
        self.assertEqual((top, margin), ("a", 0.0))  # a tie goes to the earlier option


class RulesProviderTests(unittest.TestCase):
    def test_single_legal_option_gets_probability_one(self):
        self.assertEqual(RulesDecisionProvider().decide(request(opts=("only",))), {"only": 1.0})

    def test_without_a_scorer_options_are_uniform_and_argmax_is_the_first(self):
        service = DecisionService()
        result = service.decide(request())
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0)
        self.assertEqual(result.top_option, "a")
        self.assertEqual(result.provider_mode, "rules")

    def test_scorer_changes_the_distribution_and_is_deterministic(self):
        provider = RulesDecisionProvider({"t": lambda r: {"a": 0.0, "b": 1.0 + r.state.get("greed", 0.0), "c": -1.0}})
        service = DecisionService(provider)
        low = service.decide(request(topic="t", state={"greed": 0.0}))
        high = service.decide(request(topic="t", state={"greed": 1.0}))
        again = service.decide(request(topic="t", state={"greed": 0.0}))
        self.assertEqual(low.probabilities, again.probabilities)
        self.assertEqual((low.top_option, high.top_option), ("b", "b"))
        self.assertGreater(high.probabilities["b"], low.probabilities["b"])  # state (personality) changes probabilities

    def test_softmax_is_stable_for_large_scores_and_rejects_bad_temperature(self):
        probabilities = softmax({"a": 1000.0, "b": 999.0})
        self.assertTrue(all(math.isfinite(v) for v in probabilities.values()))
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        with self.assertRaises(ValueError):
            softmax({"a": 1.0}, temperature=0)

    def test_a_non_finite_score_is_an_error_not_a_distribution(self):
        provider = RulesDecisionProvider({"t": lambda r: {"a": float("inf"), "b": 0.0}})
        with self.assertRaises(DecisionError):
            provider.decide(request(opts=("a", "b"), topic="t"))
        with self.assertRaises(ValueError):
            provider.register_scorer("", lambda r: {})


class ServiceTests(unittest.TestCase):
    def test_malformed_output_falls_back_to_rules_and_says_so(self):
        for output in ({"a": 1.0}, {"a": 0.5, "b": 0.5, "c": 0.5}, "nope", None):
            with self.subTest(output=output):
                service = DecisionService(Broken(output=output))
                result = service.decide(request())
                self.assertEqual(result.provider_mode, "fallback")
                self.assertEqual(result.top_option, "a")
                self.assertTrue(result.note)
                self.assertEqual(service.counts["fallbacks"], 1)

    def test_provider_exceptions_fall_back(self):
        for error in (RuntimeError("down"), TimeoutError("slow"), NotImplementedError()):
            result = DecisionService(Broken(error=error)).decide(request())
            self.assertEqual(result.provider_mode, "fallback")

    def test_clef_stub_is_a_fallback_not_a_crash(self):
        result = DecisionService(ClefDecisionProvider()).decide(request())
        self.assertEqual((result.provider_mode, result.top_option), ("fallback", "a"))
        self.assertIn("NotImplementedError", result.note)

    def test_valid_provider_output_is_used_with_its_mode(self):
        result = DecisionService(Broken(output={"a": 0.1, "b": 0.7, "c": 0.2})).decide(request())
        self.assertEqual((result.provider_mode, result.top_option), ("mock", "b"))
        self.assertAlmostEqual(result.margin, 0.5)

    def test_stale_results_are_dropped_and_logged(self):
        service = DecisionService()
        req = request()
        result = service.decide(req)
        self.assertFalse(service.apply_if_fresh(req, result, world_epoch="E2", state_revision=1))
        self.assertFalse(service.apply_if_fresh(req, result, world_epoch="E1", state_revision=2))
        self.assertEqual(service.counts["stale_dropped"], 2)
        self.assertEqual([r["reason"] for r in service.log.records if r["type"] == "drop"], ["stale_world_epoch", "stale_state_revision"])
        self.assertEqual([r for r in service.log.records if r["type"] == "decision"], [])
        self.assertTrue(service.apply_if_fresh(req, result, world_epoch="E1", state_revision=1))
        self.assertEqual(len([r for r in service.log.records if r["type"] == "decision"]), 1)

    def test_status_shows_the_provider_mode(self):
        service = DecisionService()
        service.decide(request())
        status = service.status()
        self.assertEqual((status["provider_mode"], status["counts"]["requests"]), ("rules", 1))
        self.assertEqual(DecisionService(Broken(output={"a": 1.0, "b": 0.0, "c": 0.0})).status()["provider_mode"], "mock")


class LogAndReplayTests(unittest.TestCase):
    def test_jsonl_log_round_trip_outside_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = DecisionLog(Path(tmp) / "decisions")
            service = DecisionService(log=log)
            req = request(state={"closeness": 0.4})
            result = service.decide(req)
            service.apply_if_fresh(req, result, world_epoch="E1", state_revision=1)
            log.record_outcome("j1", "delivered", order_id="o1")
            records = read_log(log.path)
            self.assertEqual([r["type"] for r in records], ["decision", "outcome"])
            decision = records[0]
            for key in ("job_id", "resident_id", "tick", "trigger", "state", "options", "probabilities", "chosen", "how",
                        "provider_mode", "validation", "world_epoch", "state_revision"):
                self.assertIn(key, decision)
            self.assertEqual((decision["chosen"], decision["how"], decision["state"]), ("a", "argmax", {"closeness": 0.4}))
            self.assertEqual(records[1]["outcome"], "delivered")

    def test_a_truncated_last_line_does_not_lose_earlier_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = DecisionLog(tmp)
            log.record_outcome("j1", "ok")
            with log.path.open("a", encoding="utf-8") as handle:
                handle.write('{"type": "decision", "job_id": "j2", "resi')
            self.assertEqual(len(read_log(log.path)), 1)

    def test_an_unwritable_log_never_breaks_a_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            log = DecisionLog(blocker / "sub")  # a directory cannot be created under a file
            service = DecisionService(log=log)
            req = request()
            result = service.decide(req)
            self.assertTrue(service.apply_if_fresh(req, result, world_epoch="E1", state_revision=1))
            self.assertEqual(log.write_errors, 1)
            self.assertEqual(len(log.records), 1)  # still held in memory

    def test_recorded_provider_replays_by_resident_and_trigger(self):
        log = DecisionLog(None)
        live = DecisionService(Broken(output={"a": 0.1, "b": 0.8, "c": 0.1}), log=log)
        req = request(trigger="commission:o1")
        result = live.decide(req)
        live.apply_if_fresh(req, result, world_epoch="E1", state_revision=1)
        replay = DecisionService(RecordedDecisionProvider(log.records))
        replayed = replay.decide(req)
        self.assertEqual((replayed.provider_mode, replayed.top_option, replayed.probabilities), ("recorded", "b", result.probabilities))
        unknown = replay.decide(request(trigger="commission:other"))
        self.assertEqual(unknown.provider_mode, "fallback")  # nothing recorded: rules answer, and say so
        self.assertIn("no recorded decision", unknown.note)

    def test_log_records_are_plain_json(self):
        log = DecisionLog(None)
        service = DecisionService(log=log)
        req = request()
        service.apply_if_fresh(req, service.decide(req), world_epoch="E1", state_revision=1)
        json.dumps(log.records)


if __name__ == "__main__":
    unittest.main()
