"""Tier 3 over the model plane: typed prompt context, reply parsers, the confidence gate, the router (off / shadow / on), fallback reasons,
and the deterministic mock server for the three roles. Server-in-the-loop tests use an ephemeral loopback port."""
import json
import os
import sys
import time
import unittest
from driver_pin import pin_anchor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from model_server.app import create_app  # noqa: E402
from model_server.config import ServerConfig  # noqa: E402
from test_actions_runner import Scene, setrow  # noqa: E402
from test_modelplane_client import config_for, wait_for  # noqa: E402
from harness import powers  # noqa: E402
from systems.actions import run_plan  # noqa: E402
from systems.decision import DecisionLog  # noqa: E402
from systems.modelplane import ModelPlane, ModelSwitch  # noqa: E402
from systems.modelplane.testing import NoNetworkTransport, ScriptedTransport, ServerThread  # noqa: E402
from systems.modelplane.tier3 import (DecidedOutcome, GateConfig, PacketError, PlanProposal, Tier3Router, assert_case, dialogue_case, fallback_line,  # noqa: E402
                                      gate_plan, parse_intents, parse_line, parse_plan, power_catalog, resident_case, vet_intents, world_case)
from systems.modelplane.tier3.context import ContextError, RESIDENT_CASE_KEYS  # noqa: E402


def hungry_scene(**kw):
    scene = Scene(**kw)
    setrow(scene.world, "h_a", hunger=80, stamina=40)
    return scene


def make_plane(url, modes, mode="on", transport=None):
    plane = ModelPlane(config_for(url), ModelSwitch(modes={m: mode for m in modes}), transport=transport)
    plane.log = DecisionLog(None)
    return plane


def crafted(result_for, status=200):
    """A transport handler that answers every request with a valid echo envelope around ``result_for(request body)``."""
    def handler(url, body):
        result = result_for(body)
        if result is None:
            return 500, "boom"
        return status, json.dumps({"job_id": body["job_id"], "role": body["role"], "world_epoch": body["world_epoch"],
                                   "state_revision": body["state_revision"], "schema_version": 1, "ok": True, "provider_mode": "mock",
                                   "latency_ms": 1.0, "model_id": "crafted", "result": result})
    return handler


def plan_reply(**packet):
    def result(body):
        case = body["payload"]["cases"][0]
        base = {"resident_id": case["resident_id"], "summary": "x", "confidence": 0.9, "steps": [{"op": "eat", "args": {"item": "rations"}}]}
        return {"mode": "plan_ops", "responses": [{"packet": {**base, **packet}, "source": "crafted"}]}
    return result


def await_result(poll, timeout=5.0):
    return wait_for(poll, timeout)


class ContextTests(unittest.TestCase):
    def test_resident_case_is_typed_whitelisted_small_and_legal_only(self):
        scene = hungry_scene()
        case = resident_case(scene.world, scene.services, scene.runner.aff, "h_a", "replan")
        self.assertEqual(set(case), set(RESIDENT_CASE_KEYS))
        self.assertEqual(case["needs"]["hunger"], 80.0)
        self.assertEqual(case["limits"], {"max_steps": 6, "min_confidence": 0.6})
        verbs = {o["verb"] for o in case["options"]}
        self.assertIn("eat", verbs)
        self.assertNotIn("drink", verbs)                                       # not thirsty / not legal
        self.assertNotIn("attack", verbs)                                      # destructive verbs are not offered to a model unless the gate allows them
        self.assertNotIn("attack", case["plan_ops"])
        with_attack = resident_case(scene.world, scene.services, scene.runner.aff, "h_a", "replan", destructive_ops=True)
        self.assertIn("attack", {o["verb"] for o in with_attack["options"]})
        self.assertTrue(all(o["verb"] in case["plan_ops"] for o in case["options"]))
        self.assertLessEqual(len(case["options"]), 12)
        text = json.dumps(case)
        self.assertLess(len(text), 6000)
        self.assertNotIn("h_far", text)                                         # not perceived
        self.assertNotIn("h_dead", text)
        for forbidden in ("inventory", "relationships", "tensor"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(case, resident_case(scene.world, scene.services, scene.runner.aff, "h_a", "replan"))      # a pure function of the state

    def test_other_residents_state_does_not_enter_the_case(self):
        scene = hungry_scene()
        before = resident_case(scene.world, scene.services, scene.runner.aff, "h_a", "replan")
        scene.world.items.add("h_b", "gold", 50)
        scene.records["h_b"]["secret"] = "x" * 100
        setrow(scene.world, "h_far", hunger=99)
        self.assertEqual(before, resident_case(scene.world, scene.services, scene.runner.aff, "h_a", "replan"))

    def test_the_tripwire_rejects_extra_keys_forbidden_keys_and_big_cases(self):
        with self.assertRaises(ContextError):
            assert_case({"resident_id": "x", "inventory": {}}, RESIDENT_CASE_KEYS)
        with self.assertRaises(ContextError):
            assert_case({"resident_id": "x", "needs": {"record": {}}}, RESIDENT_CASE_KEYS)
        with self.assertRaises(ContextError):
            assert_case({"resident_id": "x", "goals": "g" * 7000}, RESIDENT_CASE_KEYS)
        self.assertEqual(assert_case({"resident_id": "x"}, RESIDENT_CASE_KEYS), {"resident_id": "x"})

    def test_dialogue_case_carries_only_the_decided_outcome(self):
        decided = DecidedOutcome("h_a", "h_b", act="refuse", tone="cold", topic="commission", outcome="refuses: no materials", utterance="make me a sword",
                                 relationship_summary="acquaintance", allowed_intents=("back_away",))
        case = dialogue_case(decided)
        self.assertEqual(case["prompt_case"]["outcome"], "refuses: no materials")
        self.assertEqual(case["prompt_case"]["allowed_physical_intents"], ["back_away"])
        self.assertEqual(case["talk_mode"], "direct_talk")

    def test_power_examples_are_valid_calls(self):
        scene = hungry_scene()
        catalog = power_catalog(sample_ids=["h_a"])
        names = {p["name"] for p in catalog}
        self.assertTrue({"bless", "plague", "cull", "set_mood"} <= names)
        for entry in catalog:
            if entry["name"] in ("bless", "set_mood"):                      # the other powers need columns / a resource model the synthetic world lacks
                plan = powers.plan(scene.world, entry["name"], entry["example"])
                self.assertTrue(plan.ok, (entry, plan.reason, plan.errors))


class ParserTests(unittest.TestCase):
    def test_parse_plan_accepts_good_and_rejects_bad_shapes(self):
        good = {"resident_id": "h_a", "confidence": 0.8, "summary": "s", "steps": [{"op": "eat", "args": {"item": "rations"}}, {"op": "rest"}]}
        proposal = parse_plan(good, "h_a", "m")
        self.assertEqual([s["op"] for s in proposal.steps], ["eat", "rest"])
        self.assertEqual(proposal.steps[1]["args"], {})
        bad = {"not a dict": [], "wrong resident": {**good, "resident_id": "h_b"}, "bool confidence": {**good, "confidence": True},
               "confidence > 1": {**good, "confidence": 1.5}, "steps not list": {**good, "steps": "eat"},
               "empty op": {**good, "steps": [{"op": " "}]}, "args not dict": {**good, "steps": [{"op": "eat", "args": []}]},
               "nan": {**good, "confidence": float("nan")}}
        for name, packet in bad.items():
            with self.subTest(name), self.assertRaises(PacketError):
                parse_plan(packet if name != "not a dict" else [], "h_a")

    def test_gate_plan_decisions(self):
        scene = hungry_scene()
        run = scene.runner

        def gate(steps, confidence=0.9, **cfg):
            return gate_plan(PlanProposal("h_a", tuple(steps), confidence), run, "h_a", GateConfig(**cfg))
        eat = {"op": "eat", "args": {"item": "rations"}}
        self.assertTrue(gate([eat]).ok)
        self.assertEqual(gate([]).reason, "empty_plan")
        self.assertEqual(gate([eat], 0.3).reason, "low_confidence")
        self.assertEqual(gate([eat] * 3, max_steps=2).reason, "too_many_steps")
        self.assertEqual(gate([{"op": "teleport", "args": {}}]).reason, "unknown_op:teleport")
        self.assertEqual(gate([{"op": "defend", "args": {}}]).reason, "unknown_op:defend")                         # a catalog verb that is not an S1 plan op
        self.assertEqual(gate([{"op": "attack", "args": {"target": "h_b"}}]).reason, "destructive_op:attack")      # an S1 op, but destructive: refused unless allowed
        self.assertTrue(gate([{"op": "attack", "args": {"target": "h_b"}}], allow_destructive_ops=True).ok)
        self.assertTrue(gate([{"op": "eat", "args": {"item": 5}}]).reason.startswith("invalid_step:0"))
        self.assertTrue(gate([eat, {"op": "eat", "args": {"item": 5}}]).reason.startswith("invalid_step:1"))            # schema checked for every step
        setrow(scene.world, "h_a", hunger=0)
        self.assertEqual(gate([eat]).reason, "illegal_step:0:illegal:not_needed")
        setrow(scene.world, "h_a", hunger=80)
        legal_later = gate([eat, {"op": "store_item", "args": {"container": "e_store", "item": "gold", "qty": 1}}])
        self.assertTrue(legal_later.ok)                                                                              # only step 0 must be legal now

    def test_gate_never_changes_the_world(self):
        scene = hungry_scene()
        before = scene.digest()
        gate_plan(PlanProposal("h_a", ({"op": "eat", "args": {"item": "rations"}},), 0.9), scene.runner, "h_a")
        self.assertTrue(Scene.same(before, scene.digest()))

    def test_parse_line_keeps_only_wording(self):
        packet = {"speech_text": "  Careful there. \x07", "speech_act": "warn", "tone": "angry", "physical_intent": "back_away",
                  "accept_commission": True, "give_item": {"item": "gold", "qty": 9}, "relationship_delta": "warmer"}
        line = parse_line(packet, "h_a", "h_b", ("back_away", "flee"), "m")
        self.assertEqual((line.text, line.tone, line.intent, line.act), ("Careful there.", "angry", "back_away", "warn"))
        self.assertFalse(hasattr(line, "give_item"))
        for bad in ({}, {"speech_text": ""}, {"speech_text": "x" * 501}, {"speech_text": "ok", "physical_intent": "attack"}, []):
            with self.subTest(bad), self.assertRaises(PacketError):
                parse_line(bad, "h_a", "h_b", ("back_away",))
        with self.assertRaises(PacketError):
            parse_line({"speech_text": "ok", "physical_intent": "flee"}, "h_a", "h_b", ())              # no intent is allowed
        self.assertEqual(parse_line({"speech_text": "ok", "tone": "weird"}, "h_a", "h_b", ()).tone, "neutral")

    def test_fallback_line_is_the_rules_line(self):
        line = fallback_line("h_a", "h_b", "warn")
        self.assertEqual((line.text, line.source), ("Careful, danger is near!", "fallback"))
        self.assertEqual(fallback_line("a", "b", "unheard_of").text, "...")

    def test_intents_are_vetted_by_the_powers_without_applying(self):
        scene = hungry_scene()
        before = scene.digest()
        intents = parse_intents({"intents": [
            {"power": "bless", "args": {"targets": {"of": "humans", "ids": ["h_a"]}}, "reason": "ok"},
            {"power": "plague", "args": {"targets": {"of": "humans", "ids": ["h_a"]}}},
            {"power": "nonsense", "args": {}}, {"power": "set_mood", "args": {"targets": {"of": "humans", "ids": ["h_a"]}}},
            {"power": "calm_area", "args": {"center": [10, 10]}}]}, max_intents=5)
        accepted, rejected = vet_intents(scene.world, intents)
        self.assertEqual([i.power for i, _ in accepted], ["bless"])
        self.assertEqual(dict((i.power, why.split(":")[0]) for i, why in rejected),          # the synthetic world has no threat column: calm_area cannot plan
                         {"plague": "risk_gated", "nonsense": "unknown_power", "set_mood": "invalid_arguments", "calm_area": "plan_error"})
        self.assertTrue(Scene.same(before, scene.digest()))
        accepted2, rejected2 = vet_intents(scene.world, intents, GateConfig(allow_destructive_powers=True))
        self.assertNotEqual(dict((i.power, why) for i, why in rejected2).get("plague"), "risk_gated")      # allowed through the risk gate (the world may still refuse)
        for bad in ({}, {"intents": "x"}, {"intents": [{"power": ""}]}, {"intents": [{"power": "bless", "args": 3}]}):
            with self.assertRaises(PacketError):
                parse_intents(bad)


class RouterOffTests(unittest.TestCase):
    def test_off_makes_no_job_no_thread_no_socket_for_all_three_kinds(self):
        scene = hungry_scene()
        plane = ModelPlane(config_for("http://127.0.0.1:9"), ModelSwitch(), transport=NoNetworkTransport())
        router = Tier3Router(plane, runner=scene.runner)
        threads = __import__("threading").active_count()
        self.assertEqual(router.request_plan("h_a", "replan").status, "off")
        self.assertEqual(router.request_line(DecidedOutcome("h_a", "h_b")).status, "off")
        self.assertEqual(router.request_intents("bless the harvest").status, "off")
        self.assertEqual(router.line_or_fallback(DecidedOutcome("h_a", "h_b", act="greet")).source, "fallback")
        self.assertEqual(plane.client.network_calls, 0)
        self.assertEqual(__import__("threading").active_count(), threads)
        self.assertEqual(router.status()["results"], {"plan": {}, "line": {}, "intents": {}})
        self.assertEqual(plane.status()["tier3"]["pending"], 0)


class RouterAgainstMockServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ServerThread(create_app(ServerConfig()))
        cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.scene = hungry_scene()
        self.plane = make_plane(self.server.url, ("tier3_resident", "tier3_dialogue", "tier3_world"))
        self.router = Tier3Router(self.plane, runner=self.scene.runner)

    def tearDown(self):
        self.plane.close()

    def test_plan_round_trip_on_then_runs_through_the_runner(self):
        self.assertEqual(self.router.request_plan("h_a", "replan").status, "pending")
        self.assertEqual(self.router.request_plan("h_a", "replan").reason, "already_pending")
        result = await_result(lambda: self.router.poll_plan("h_a"))
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "plan")
        self.assertIn(result.status, ("accepted", "rejected"))          # the mock's confidence is seeded: either is a valid, logged outcome
        if result.status == "accepted":
            outcome = run_plan(self.scene.runner, "h_a", result.proposal.steps_list(), proposer="tier3", confidence=result.proposal.confidence)
            self.assertTrue(outcome["ok"] or outcome["failed_at"] is not None)
        self.assertIsNone(self.router.poll_plan("h_a"))                  # taken once
        self.assertEqual(self.plane.metrics.snapshot()["resident"]["background"]["requests"], 1)

    def test_the_mock_plan_is_deterministic_and_only_uses_offered_options(self):
        case = resident_case(self.scene.world, self.scene.services, self.scene.runner.aff, "h_a", "replan")
        answers = []
        for _ in range(2):
            plane = make_plane(self.server.url, ("tier3_resident",))
            outcome = plane.client.call_sync(__import__("systems.modelplane", fromlist=["Job"]).Job(
                role="resident", payload={"mode": "plan_ops", "cases": [case]}, world_epoch="E", state_revision=1))
            answers.append(outcome.response.result["responses"][0]["packet"])
            plane.close()
        self.assertEqual(answers[0], answers[1])
        offered = {(o["verb"], json.dumps(o["params"], sort_keys=True)) for o in case["options"]}
        for step in answers[0]["steps"]:
            self.assertIn((step["op"], json.dumps(step["args"], sort_keys=True)), offered)
        self.assertEqual(answers[0]["resident_id"], "h_a")

    def test_the_mock_seed_changes_the_answers_but_stays_valid(self):
        case = resident_case(self.scene.world, self.scene.services, self.scene.runner.aff, "h_a", "replan")
        from model_server.backends import heuristics
        seen = set()
        for seed in ("", "a", "b", "c", "d", "e"):
            with mock.patch.dict(os.environ, {"EDEN_MODEL_MOCK_SEED": seed}):
                packet = heuristics.plan_ops_packet(case)
                parse_plan(packet, "h_a")
                seen.add(json.dumps(packet, sort_keys=True))
        self.assertGreater(len(seen), 1)

    def test_shadow_records_what_the_model_would_do_and_applies_nothing(self):
        self.plane.set_modes(tier3_resident="shadow")
        before = self.scene.digest()
        self.assertEqual(self.router.request_plan("h_a", "replan").status, "pending")
        wait_for(lambda: self.plane.pump() or self.router.status()["results"]["plan"], 5.0)
        self.assertIsNone(self.router.poll_plan("h_a"))                  # never offered to a caller
        self.assertTrue(Scene.same(before, self.scene.digest()))
        recent = self.router.status()["recent"][-1]
        self.assertEqual((recent["kind"], recent["status"], recent["mode"]), ("plan", "shadow", "shadow"))
        self.assertIsInstance(recent["would_apply"], bool)
        records = [r for r in self.plane.log.records if r["type"] == "tier3"]
        self.assertEqual(len(records), 1)
        self.assertIn("steps", records[0])

    def test_dialogue_round_trip_and_line_or_fallback(self):
        decided = DecidedOutcome("h_a", "h_b", act="warn", tone="tense", topic="danger", outcome="warns about wolves", allowed_intents=("flee", "back_away"),
                                 mode="ambient_npc_talk")
        first = self.router.line_or_fallback(decided)
        self.assertEqual(first.source, "fallback")                       # the tick never waits
        result = await_result(lambda: self.router.poll_line(decided))
        self.assertEqual((result.status, result.proposal.source), ("accepted", "mock-v1"))
        self.assertEqual(result.proposal.speaker, "h_a")
        self.assertTrue(result.proposal.text)

    def test_world_intents_round_trip_and_apply(self):
        self.assertEqual(self.router.request_intents("bless the harvest", tick=10, residents=5, sample_ids=["h_a"], only=("set_mood",)).status,
                         "pending")
        result = await_result(lambda: self.router.poll_intents("bless the harvest"))
        self.assertEqual(result.status, "accepted", result)
        self.assertEqual([i.power for i, _ in result.proposal][0] in powers.REGISTRY.powers, True)
        outcomes = self.router.apply_intents(result)
        self.assertTrue(all(o.ok for o in outcomes), [o.reason for o in outcomes])


class RouterFallbackTests(unittest.TestCase):
    def build(self, handler, modes=("tier3_resident", "tier3_dialogue", "tier3_world"), mode="on"):
        scene = hungry_scene()
        plane = make_plane("http://stub", modes, mode, ScriptedTransport(handler))
        return scene, plane, Tier3Router(plane, runner=scene.runner)

    def poll(self, router, actor="h_a"):
        return await_result(lambda: router.poll_plan(actor))

    def test_a_good_confident_legal_plan_is_accepted(self):
        scene, plane, router = self.build(crafted(plan_reply()))
        router.request_plan("h_a", "replan")
        result = self.poll(router)
        self.assertEqual((result.status, result.reason), ("accepted", ""))
        self.assertEqual(result.proposal.steps[0]["op"], "eat")
        self.assertEqual(plane.metrics.snapshot()["resident"]["background"]["gate_accepted"], 1)
        plane.close()

    def test_low_confidence_falls_back_with_a_logged_reason(self):
        scene, plane, router = self.build(crafted(plan_reply(confidence=0.2)))
        router.request_plan("h_a", "replan")
        result = self.poll(router)
        self.assertEqual((result.status, result.reason), ("rejected", "low_confidence"))
        self.assertIsNone(result.proposal)
        self.assertEqual(plane.metrics.snapshot()["resident"]["reasons"]["gate:low_confidence"], 1)
        logged = [r for r in plane.log.records if r["type"] == "tier3"]
        self.assertEqual((logged[0]["status"], logged[0]["reason"]), ("rejected", "low_confidence"))
        plane.close()

    def test_an_illegal_first_step_is_rejected_by_the_dry_run(self):
        scene, plane, router = self.build(crafted(plan_reply(steps=[{"op": "drink", "args": {"place": "v:well"}}])))
        router.request_plan("h_a", "replan")
        result = self.poll(router)
        self.assertEqual(result.status, "rejected")
        self.assertTrue(result.reason.startswith("illegal_step:0:"), result.reason)
        plane.close()

    def test_unknown_ops_and_empty_plans_are_rejected(self):
        for steps, reason in (([{"op": "summon_dragon", "args": {}}], "unknown_op:summon_dragon"), ([], "empty_plan")):
            scene, plane, router = self.build(crafted(plan_reply(steps=steps)))
            router.request_plan("h_a", "replan")
            self.assertEqual(self.poll(router).reason, reason)
            plane.close()

    def test_a_reply_for_the_wrong_resident_is_an_invalid_packet(self):
        scene, plane, router = self.build(crafted(plan_reply(resident_id="h_b")))
        router.request_plan("h_a", "replan")
        result = self.poll(router)
        self.assertEqual((result.status, result.reason), ("rejected", "invalid_packet:wrong_resident"))
        plane.close()

    def test_contract_breaking_replies_and_http_errors_are_fallbacks(self):
        cases = {"no confidence": (crafted(lambda b: {"mode": "plan_ops", "responses": [{"packet": {"resident_id": "h_a", "steps": []}}]}), "invalid_reply"),
                 "http 500": (crafted(lambda b: None), "http_500"),
                 "garbage": (lambda url, body: (200, "not json"), "bad_json")}
        for name, (handler, reason) in cases.items():
            with self.subTest(name):
                scene, plane, router = self.build(handler)
                router.request_plan("h_a", "replan")
                result = self.poll(router)
                self.assertEqual(result.status, "fallback")
                self.assertTrue(result.reason.startswith(reason), result.reason)
                self.assertTrue(any(r["type"] == "tier3" and r["status"] == "fallback" for r in plane.log.records))
                plane.close()

    def test_toggling_the_switch_drops_the_in_flight_answer(self):
        gate = {}

        def slow(url, body):
            gate["called"] = True
            time.sleep(0.2)
            return crafted(plan_reply())(url, body)
        scene, plane, router = self.build(slow)
        router.request_plan("h_a", "replan")
        wait_for(lambda: gate.get("called"))
        plane.set_modes(tier3_resident="on", tier1="matrix")            # any change bumps the model epoch
        result = await_result(lambda: router.poll_plan("h_a"))
        self.assertEqual((result.status, result.reason), ("fallback", "stale_model_epoch"))
        plane.close()

    def test_a_dialogue_that_breaks_the_rules_gets_the_rules_line(self):
        decided = DecidedOutcome("h_a", "h_b", act="warn", allowed_intents=("flee",))

        def reply(speech, **extra):
            return crafted(lambda b: {"mode": "talk_reply", "responses": [{"packet": {"speech_text": speech, **extra}}]})
        # intent outside the allowed list: the client contract already rejects it -> fallback with the rules line
        scene, plane, router = self.build(reply("Run!", physical_intent="attack"))
        router.request_line(decided)
        result = await_result(lambda: router.poll_line(decided))
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.proposal.source, "fallback")
        plane.close()
        # obligations the model tacked on are dropped; the wording is kept
        scene, plane, router = self.build(reply("Run!", physical_intent="flee", accept_commission=True, give_item={"item": "gold"}))
        router.request_line(decided)
        result = await_result(lambda: router.poll_line(decided))
        self.assertEqual((result.status, result.proposal.text, result.proposal.intent), ("accepted", "Run!", "flee"))
        plane.close()

    def test_destructive_and_invalid_world_intents_are_gated(self):
        intents = [{"power": "plague", "args": {"targets": {"of": "humans", "ids": ["h_a"]}}}, {"power": "bless", "args": {"nonsense": 1}}]
        scene, plane, router = self.build(crafted(lambda b: {"mode": "director", "responses": [{"packet": {"thought": "t", "intents": intents}}]}))
        router.request_intents("end the village", tick=1, residents=5)
        result = await_result(lambda: router.poll_intents("end the village"))
        self.assertEqual((result.status, result.reason), ("rejected", "no_valid_intent"))
        reasons = dict(result.detail["rejected"])
        self.assertEqual(reasons["plague"], "risk_gated")
        self.assertTrue(reasons["bless"].startswith("invalid_arguments"))
        self.assertEqual(router.apply_intents(result), [])
        plane.close()


class FakeEngine:
    """Just enough engine for the escalation hook: a roster, a tick and an epoch (the world/runner come from the synthetic Scene)."""
    def __init__(self, roster, tick=0):
        self._human_uid_by_slot = list(roster)
        self.tick, self.world_epoch = tick, "E1"


class EscalationTests(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        from systems.modelplane.tier3 import EscalationConfig, Escalator
        self.EscalationConfig, self.Escalator = EscalationConfig, Escalator
        self.server = ServerThread(create_app(ServerConfig()))
        self.server.__enter__()
        self.scene = hungry_scene()
        self.engine = FakeEngine(["h_a"])
        self.plane = make_plane(self.server.url, ("tier3_resident",), mode="off")
        self.router = Tier3Router(self.plane, runner=self.scene.runner, gate=GateConfig(min_confidence=0.0))

    def tearDown(self):
        self.plane.close()
        self.server.__exit__(None, None, None)

    def escalator(self, **config):
        # urgent_need=0.0: the synthetic world has no thirst column (reads 0), so "thirst >= 0 and no legal drink" is an unmet need for h_a
        config.setdefault("batch", 6)
        config.setdefault("prefilter", False)                   # the synthetic engine has no tensor; the prefilter has its own tests
        esc = self.Escalator(self.plane, self.router, config=self.EscalationConfig(period=1, urgent_need=0.0, **config))
        self.plane.escalator = esc
        esc._ctx = ((id(self.engine), self.engine.world_epoch), (self.scene.world, self.scene.services, self.scene.runner.aff, self.scene.runner))
        return esc

    def test_the_default_sweep_is_amortised_one_resident_per_tick(self):
        c = self.EscalationConfig()
        self.assertEqual((c.period, c.batch, c.prefilter), (1, 1, True))

    def test_the_prefilter_does_no_work_for_calm_or_unchanged_residents(self):
        import types
        import torch
        import genesis_config as cfg
        h = torch.zeros(3, 40)
        engine = types.SimpleNamespace(state=types.SimpleNamespace(h_tensor=h), _human_slot_for_id=lambda u: {"calm": 0, "hungry": 1, "gone": -1}.get(u, -1))
        h[0, cfg.HP], h[1, cfg.HP], h[1, cfg.HUNGER] = 100.0, 100.0, 80.0
        esc = self.Escalator(self.plane, self.router, config=self.EscalationConfig())
        self.assertFalse(esc._worth_evaluating(engine, "calm", 0))
        self.assertFalse(esc._worth_evaluating(engine, "gone", 0))
        self.assertTrue(esc._worth_evaluating(engine, "hungry", 0))
        self.assertFalse(esc._worth_evaluating(engine, "hungry", 5))               # same rounded inputs inside the cooldown window
        h[1, cfg.HUNGER] = 95.0
        self.assertTrue(esc._worth_evaluating(engine, "hungry", 6))                # inputs changed
        self.assertTrue(esc._worth_evaluating(engine, "hungry", 400))              # a new cooldown window: asked again if still unmet
        h[1, cfg.THREAT] = 40.0
        self.assertFalse(esc._worth_evaluating(engine, "calm", 0))
        h[0, cfg.THREAT] = 40.0
        self.assertTrue(esc._worth_evaluating(engine, "calm", 1))                  # a threat makes it worth evaluating
        self.assertEqual(esc.counts["skipped:calm"], 2)

    def test_classify_is_pure_and_names_each_trigger(self):
        from systems.modelplane.tier3 import classify
        cfg = self.EscalationConfig()
        self.assertEqual(classify({}, "eat", False, {"eat"}, cfg), [])
        self.assertEqual(classify({}, "USE_BRAIN", False, set(), cfg), ["macro:USE_BRAIN"])
        self.assertEqual(classify({}, "idle", True, set(), cfg), ["tier1_uncertain"])
        self.assertEqual(classify({"hunger": 0.9}, "idle", False, {"rest"}, cfg), ["unmet_need"])
        self.assertEqual(classify({"hunger": 0.9}, "eat", False, {"eat"}, cfg), [])
        self.assertEqual(classify({"threat": 0.8}, "idle", False, {"rest"}, cfg), ["unresolved_threat"])
        self.assertEqual(classify({"threat": 0.8}, "flee", False, {"flee"}, cfg), [])
        self.assertEqual(classify({"thirst": 0.9}, None, False, set(), cfg), ["unmet_need"])

    def test_off_is_a_no_op_that_touches_nothing(self):
        class Tripwire:
            tick = 0
            world_epoch = "E"
            @property
            def _human_uid_by_slot(self):
                raise AssertionError("the off path must not look at the roster")
        esc = self.Escalator(self.plane, self.router)
        esc.hook(Tripwire())
        self.assertEqual(dict(esc.counts), {})
        self.assertEqual(self.plane.client.network_calls, 0)

    def test_the_installed_hook_finds_the_engines_plane_and_is_idempotent(self):
        from simulation.dispatch import Dispatcher
        from systems.modelplane.tier3 import escalation
        dispatch = Dispatcher()
        self.engine.__dict__["_model_plane"] = self.plane
        first = escalation.install(dispatch, self.plane)
        self.assertIs(escalation.install(dispatch, self.plane), first)
        self.assertEqual([name for name, _ in dispatch.post_step_hooks], [escalation.HOOK_NAME])
        self.assertEqual(dispatch.run_post_step_hooks(self.engine), 0)                         # off: nothing happens, nothing raises
        self.assertEqual(dict(first.counts), {})
        dispatch.clear()
        self.assertEqual(len(dispatch.post_step_hooks), 1)                                       # builtin: survives a test clear()
        escalation.uninstall(dispatch)
        self.assertEqual(dispatch.post_step_hooks, [])

    def test_shadow_sweep_records_and_applies_nothing(self):
        self.plane.set_modes(tier3_resident="shadow")
        esc = self.escalator()
        before = self.scene.digest()
        esc.hook(self.engine)
        self.assertEqual(esc.counts["request:pending"], 1)                                      # max_per_sweep 2 but only h_a triggers
        wait_for(lambda: self.plane.pump() or self.router.status()["results"]["plan"], 5.0)
        self.assertTrue(Scene.same(before, self.scene.digest()))
        recent = self.router.status()["recent"][-1]
        self.assertEqual((recent["kind"], recent["status"], recent["resident_id"]), ("plan", "shadow", "h_a"))
        self.assertEqual(esc.status()["waiting_for_plan"], 0)                                   # shadow never waits for a plan to run
        self.assertEqual(self.plane.status()["tier3"]["escalation"]["counts"]["trigger:unmet_need"], 1)

    def test_sweep_budget_cooldown_and_round_robin(self):
        self.plane.set_modes(tier3_resident="shadow")
        two = FakeEngine(["h_a", "h_b"])
        probe = self.escalator(batch=1)
        self.assertEqual([probe.candidates(two) for _ in range(3)], [["h_a"], ["h_b"], ["h_a"]])
        self.assertEqual(self.escalator(batch=5).candidates(two), ["h_a", "h_b"])
        esc = self.escalator(batch=1, cooldown_ticks=100)
        esc.hook(self.engine)                                                                    # h_a: requested
        self.assertEqual(esc.counts["request:pending"], 1)
        self.engine.tick = 5
        esc.hook(self.engine)                                                                    # h_a again inside the cooldown: skipped
        self.assertEqual((esc.counts["skipped:cooldown"], esc.counts["request:pending"]), (1, 1))
        self.engine.tick = 150
        esc.hook(self.engine)                                                                    # cooldown over
        self.assertEqual(esc.counts["request:pending"] + esc.counts["request:refused"], 2)
        budget = self.escalator(batch=2, max_per_sweep=1)
        two_engine = FakeEngine(["h_a", "h_b"])
        budget._ctx = ((id(two_engine), two_engine.world_epoch), budget._ctx[1])
        budget.hook(two_engine)
        self.assertEqual((budget.counts["request:pending"], budget.counts["skipped:sweep_budget"]), (1, 1))

    def test_switching_shadow_to_on_resets_cooldowns_and_pending_so_triggers_resume(self):
        self.plane.set_modes(tier3_resident="shadow")
        esc = self.escalator(batch=1, cooldown_ticks=1000)
        esc.hook(self.engine)                                                                    # tick 0: asked in shadow (job stays pending: no pump)
        self.engine.tick = 5
        esc.hook(self.engine)
        self.assertEqual((esc.counts["request:pending"], esc.counts["skipped:cooldown"]), (1, 1))
        self.plane.set_modes(tier3_resident="on")                                                # same plane, same engine, the resident still has the need
        self.engine.tick = 10
        esc.hook(self.engine)
        self.assertEqual(esc.counts["epoch_reset"], 1)
        self.assertEqual(esc.counts["skipped:cooldown"], 1)                                      # not skipped again: the cooldown belonged to the old epoch
        self.assertEqual(esc.recent[-1]["requested"], [("h_a", "unmet_need", "pending", "")])    # a fresh ask, not "already_pending"
        self.assertEqual(esc.status()["waiting_for_plan"], 1)                                    # and on mode now waits for the plan to run
        self.plane.set_modes(tier3_resident="off")
        self.engine.tick = 15
        esc.hook(self.engine)                                                                    # off: nothing, and nothing raises
        self.assertEqual(esc.counts["epoch_reset"], 1)

    def test_a_hungry_roster_resident_is_not_an_unmet_need_while_the_world_allows_eating(self):
        self.scene = hungry_scene(roster=True)
        self.scene.world.items.remove("h_a", "rations", 2)                                       # no pack food: the only food is the roster resident's fire site
        setrow(self.scene.world, "h_a", hunger=90)
        self.router.runner, self.router.world, self.router.aff = self.scene.runner, self.scene.world, self.scene.runner.aff
        self.plane.set_modes(tier3_resident="shadow")
        esc = self.Escalator(self.plane, self.router, config=self.EscalationConfig(period=1, batch=6, prefilter=False))
        esc._ctx = ((id(self.engine), self.engine.world_epoch), (self.scene.world, self.scene.services, self.scene.runner.aff, self.scene.runner))
        aff = self.scene.runner.aff
        self.assertFalse(bool(aff.mask(["h_a"])[0][__import__("systems.decision.matrix", fromlist=["x"]).ACTION_INDEX["eat"]]))     # Tier 1 mask: roster_driven
        esc.hook(self.engine)
        self.assertEqual(esc.counts["trigger:unmet_need"], 0)                                    # the world allows eating; the roster loop carries it out

    def test_on_sweep_runs_the_accepted_plan_through_the_runner(self):
        self.plane.set_modes(tier3_resident="on")
        esc = self.escalator(batch=2)
        before = self.scene.digest()
        esc.hook(self.engine)
        self.assertEqual(esc.status()["waiting_for_plan"], 1)
        for tick in range(1, 80):
            self.engine.tick = tick                                                              # period 1: later ticks sweep again, the cooldown holds
            esc.hook(self.engine)
            for task in list(self.scene.records["h_a"].get("tasks", [])):
                self.scene.ops.finish_task("h_a", task["id"], tick=tick)                         # the engine finishes the queued task; the cursor goes on
            if not esc.status()["waiting_for_plan"] and not esc.status()["plans_running"]:
                break
            time.sleep(0.05)
        runs = {k: v for k, v in esc.counts.items() if k == "run:ok" or k.startswith("run:failed")}
        self.assertEqual(sum(runs.values()), 1, runs)
        self.assertEqual(esc.counts["run:started"], 1)
        self.assertTrue(any(e["actor"] == "h_a" and not e["dry_run"] for e in self.scene.audit.entries))     # the runner ran and audited the first step
        if "run:ok" in runs:
            self.assertFalse(Scene.same(before, self.scene.digest()))

    def test_a_gate_rejection_leaves_the_resident_on_tier1(self):
        self.plane.set_modes(tier3_resident="on")
        self.router.gate = GateConfig(min_confidence=1.01)                                       # nothing passes
        esc = self.escalator(batch=2)
        before = self.scene.digest()
        esc.hook(self.engine)
        for tick in range(1, 80):
            self.engine.tick = tick
            esc.hook(self.engine)
            if not esc.status()["waiting_for_plan"]:
                break
            time.sleep(0.05)
        self.assertEqual(esc.counts["run:rejected"], 1)
        self.assertTrue(Scene.same(before, self.scene.digest()))
        self.assertEqual(self.plane.status()["tier3"]["reasons"]["plan:low_confidence"], 1)


class PlanAdapterTests(unittest.TestCase):
    def test_legacy_steps_map_to_s1_only_when_the_args_are_known(self):
        from systems.actions.plan_adapter import from_legacy, to_legacy
        from systems.actions.plan_ops import PLAN_OPS
        from systems.planning import PLAN_OP_DEFS
        out = from_legacy([{"op": "rest_until_safe"}, {"op": "move_to_target", "target_id": "h_b"}, {"op": "move_to_target"},
                           {"op": "gather_food_buffer"}, {"op": "attack_target_when_close", "target_id": "h_b"}, {"op": "dance"}])
        self.assertEqual(out["steps"], [{"op": "rest", "args": {}}, {"op": "follow", "args": {"target": "h_b"}}])
        self.assertEqual(out["unmapped"], [(2, "move_to_target", "missing_target"), (3, "gather_food_buffer", "needs_grounding"),
                                           (4, "attack_target_when_close", "no_s1_verb"), (5, "dance", "unknown_legacy_op")])
        back = to_legacy(out["steps"] + [{"op": "eat", "args": {"item": "rations"}}])
        self.assertEqual(back["steps"], [{"op": "rest_until_safe"}, {"op": "move_to_target", "target_id": "h_b"}])
        self.assertEqual(back["unmapped"], [(2, "eat", "no_legacy_op")])
        for step in back["steps"]:                                                                # the planning validator accepts what we hand back
            self.assertIn(step["op"], PLAN_OP_DEFS)
        for legacy, (verb, _fields) in __import__("systems.actions.plan_adapter", fromlist=["x"]).LEGACY_TO_S1.items():
            self.assertIn(legacy, PLAN_OP_DEFS)
            self.assertTrue(verb is None or verb in PLAN_OPS, legacy)

    def test_a_converted_legacy_plan_runs_through_the_runner(self):
        from systems.actions.plan_adapter import from_legacy
        scene = hungry_scene()
        steps = from_legacy([{"op": "rest_until_safe"}, {"op": "move_to_target", "target_id": "h_b"}])["steps"]
        outcome = run_plan(scene.runner, "h_a", steps, proposer="tier3", confidence=0.9)
        self.assertTrue(outcome["ok"] or outcome["failed_at"] is not None)
        self.assertEqual(len(outcome["results"]), outcome["completed"] + (0 if outcome["ok"] else 1))


class StatusRouteTests(unittest.TestCase):
    def make(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.model_routes import build_model_router
        from test_modelplane_client import FakeEngine as ClientFakeEngine
        engine = ClientFakeEngine()
        plane = ModelPlane(config_for("http://127.0.0.1:9"), ModelSwitch(), transport=NoNetworkTransport())
        app = FastAPI()
        app.include_router(build_model_router(lambda: engine, plane))
        return engine, plane, TestClient(app)

    def test_per_role_modes_round_trip_and_the_tier3_block_is_reported(self):
        engine, plane, client = self.make()
        body = client.get("/model_status").json()
        self.assertEqual({k: body["switch"][k] for k in ("tier3_resident", "tier3_dialogue", "tier3_world")}, {k: "off" for k in ("tier3_resident", "tier3_dialogue", "tier3_world")})
        self.assertIn("escalation", body["tier3"])
        reply = client.post("/control/models", json={"tier3_resident": "shadow", "tier3_dialogue": "on", "tier3_world": "shadow"}).json()
        self.assertEqual((reply["tier3_resident"], reply["tier3_dialogue"], reply["tier3_world"]), ("shadow", "on", "shadow"))
        switch = client.get("/model_status").json()["switch"]
        self.assertEqual((switch["tier3_resident"], switch["tier3_dialogue"], switch["tier3_world"]), ("shadow", "on", "shadow"))
        self.assertEqual(client.post("/control/models", json={"tier3_world": "off"}).json()["tier3_world"], "off")
        self.assertEqual(client.post("/control/models", json={"tier3_world": "loud"}).status_code, 400)
        self.assertEqual(client.get("/model_status").json()["switch"]["tier3_world"], "off")
        client.post("/control/models", json={"all_off": True})
        switch = client.get("/model_status").json()["switch"]
        self.assertEqual({switch[k] for k in ("tier2", "tier3_resident", "tier3_dialogue", "tier3_world")}, {"off"})

    def test_gate_reasons_show_up_in_model_status(self):
        engine, plane, client = self.make()
        client.post("/control/models", json={"tier3_resident": "on"})
        plane.tier3.status()                                                                      # router exists after build_model_router
        plane.metrics.reason("resident", "gate:low_confidence")
        self.assertIn("gate:low_confidence", str(client.get("/model_status").json()))


if __name__ == "__main__":
    unittest.main()
