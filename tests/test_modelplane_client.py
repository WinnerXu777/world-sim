"""Game-side model plane: the LLM switch, OFF = zero network, async client, budgets, breaker, stale drops, providers, legacy adapters,
routes. Server-in-the-loop tests use an ephemeral loopback port."""
import socket
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.model_routes import build_model_router
from model_server.app import create_app
from model_server.config import ServerConfig
from systems.decision import (ClefDecisionProvider, DecisionLog, DecisionOption, DecisionRequest, DecisionService, ModelPending,
                              RulesDecisionProvider)
from systems.modelplane import (Admission, CircuitBreaker, Endpoint, Job, ModelClient, ModelPlane, ModelPlaneConfig, ModelSwitch,
                                SwitchError)
from systems.modelplane.adapters.legacy import LegacyModelHandler, install, sync_installation
from systems.modelplane.testing import NoNetworkTransport, ScriptedTransport, ServerThread
from systems.modelplane.transport import TransportError, TransportTimeout


def wait_for(predicate, timeout=5.0, step=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def drain_until(plane, count, timeout=5.0):
    got = []
    wait_for(lambda: (got.extend(plane.pump()), len(got) >= count)[1], timeout)
    return got


def request(n=1, options=("a", "b", "c"), epoch="E1", revision=1, resident="h_1", trigger=None, priority="active", deadline_ms=1000):
    return DecisionRequest(job_id=f"job{n}", resident_id=resident, world_epoch=epoch, state_revision=revision, tick=10,
                           trigger=trigger or f"t:{n}", question_kind="choice",
                           options=tuple(DecisionOption(i, f"option {i}", ("t",)) for i in options), priority=priority,
                           deadline_ms=deadline_ms)


def config_for(url, **over):
    cfg = ModelPlaneConfig(endpoints={r: Endpoint(url, "", "") for r in ("decide", "resident", "dialogue", "world")}, cooldown_s=0, **over)
    for limits in cfg.limits.values():
        limits.update(max_in_flight=64, per_minute=100000)
    return cfg


def on_plane(url, modes=("tier2",), mode="on", transport=None, **over):
    plane = ModelPlane(config_for(url, **over), ModelSwitch(modes={m: mode for m in modes}), transport=transport)
    return plane


class FakeEngine:
    def __init__(self):
        self.world_epoch = "E1"
        self.tick = 100
        self.tiny_model_handler = None
        self.resident_model_handler = None
        self.world_model_handler = None


class SwitchTests(unittest.TestCase):
    def test_default_is_everything_off_and_rules(self):
        switch = ModelSwitch()
        self.assertEqual(switch.snapshot(), {"tier1": "rules", "tier2": "off", "tier3_resident": "off", "tier3_dialogue": "off",
                                             "tier3_world": "off", "epoch": 0})
        self.assertFalse(switch.any_enabled())

    def test_environment_variables(self):
        switch = ModelSwitch.from_env({"EDEN_TIER1": "matrix", "EDEN_TIER2": "shadow", "EDEN_TIER3_WORLD": "ON"})
        self.assertEqual((switch.tier1, switch.mode("decide"), switch.mode("world"), switch.mode("resident"), switch.epoch),
                         ("matrix", "shadow", "on", "off", 0))
        for bad in ({"EDEN_TIER2": "maybe"}, {"EDEN_TIER1": "neural"}):
            with self.assertRaises(SwitchError):
                ModelSwitch.from_env(bad)

    def test_epoch_moves_only_when_something_changes(self):
        switch = ModelSwitch()
        self.assertEqual(switch.set(tier2="off")["changed"], {})
        self.assertEqual(switch.epoch, 0)
        self.assertEqual(switch.set(tier2="on")["epoch"], 1)
        self.assertEqual(switch.set(tier2="on", tier3_world="shadow")["changed"], {"tier3_world": ["off", "shadow"]})
        self.assertEqual(switch.epoch, 2)
        self.assertEqual(switch.all_off()["epoch"], 3)

    def test_invalid_values_change_nothing(self):
        switch = ModelSwitch()
        with self.assertRaises(SwitchError):
            switch.set(tier2="on", tier3_world="sometimes")
        with self.assertRaises(SwitchError):
            switch.set(tier9="on")
        self.assertEqual((switch.mode("decide"), switch.epoch), ("off", 0))


class OffMeansNoNetworkTests(unittest.TestCase):
    def test_default_plane_never_touches_the_network_or_starts_threads(self):
        def forbidden(*a, **k):
            raise AssertionError("socket used while every role is off")

        threads_before = threading.active_count()
        with mock.patch.object(socket.socket, "connect", forbidden), mock.patch.object(socket, "create_connection", forbidden):
            plane = ModelPlane(ModelPlaneConfig(), ModelSwitch(), transport=NoNetworkTransport())
            self.assertIsNotNone(plane.submit_decision(request()))                       # refused, never queued
            service = DecisionService(ClefDecisionProvider(plane))
            result = service.decide(request())
            handler = LegacyModelHandler(plane)
            for mode in ("urgent_react", "normal_live", "talk_reply", "ambient_npc_talk", "resident_reasoning", "decree"):
                self.assertIsNone(handler(mode=mode, cases=[{"x": 1}], engine=FakeEngine()))
            plane.pump()
        self.assertEqual((result.provider_mode, result.top_option), ("rules", "a"))
        self.assertEqual(plane.client.network_calls, 0)
        self.assertEqual(plane.client._threads, [])
        self.assertEqual(threading.active_count(), threads_before)

    def test_env_configured_urls_do_not_matter_while_off(self):
        plane = ModelPlane(env={"EDEN_MODEL_URL": "http://127.0.0.1:9", "EDEN_TIER2": "off"}, transport=NoNetworkTransport())
        outcome = plane.submit_decision(request())
        self.assertEqual((outcome.status, outcome.reason), ("skipped", "disabled"))
        self.assertEqual(plane.status()["network_enabled"], False)

    def test_a_bad_environment_value_keeps_everything_off_and_is_reported(self):
        plane = ModelPlane(env={"EDEN_TIER2": "maybe", "EDEN_MODEL_URL": "http://127.0.0.1:9"}, transport=NoNetworkTransport())
        status = plane.status()
        self.assertFalse(status["network_enabled"])
        self.assertIn("maybe", status["config_error"])
        self.assertEqual(plane.submit_decision(request()).reason, "disabled")

    def test_on_without_an_endpoint_is_a_fallback_not_an_error(self):
        plane = ModelPlane(env={"EDEN_TIER2": "on"}, transport=NoNetworkTransport())
        outcome = plane.submit_decision(request())
        self.assertEqual((outcome.status, outcome.reason), ("fallback", "no_endpoint"))
        self.assertEqual(plane.client.network_calls, 0)


class ClientAgainstServerTests(unittest.TestCase):
    def serve(self, **server_kw):
        return ServerThread(create_app(ServerConfig(**server_kw)))

    def test_decide_round_trip_through_the_provider_and_service(self):
        with self.serve() as server:
            plane = on_plane(server.url)
            log = DecisionLog(None)
            service = DecisionService(ClefDecisionProvider(plane), log=log)
            first = service.decide(request())
            self.assertEqual(first.provider_mode, "fallback")            # tick never waits: rules answer this time
            self.assertIn("ModelPending", first.note)
            done = drain_until(plane, 1)
            self.assertTrue(done[0].applicable)
            second = service.decide(request())
            self.assertEqual(second.provider_mode, "mock")
            self.assertAlmostEqual(sum(second.probabilities.values()), 1.0)
            self.assertTrue(service.apply_if_fresh(request(), second, world_epoch="E1", state_revision=1))
            snap = plane.status()["metrics"]["decide"]["active"]
            self.assertEqual((snap["requests"], snap["ok"], snap["fallbacks"]), (1, 1, 0))
            plane.close()

    def test_blocking_provider_for_tools(self):
        with self.serve() as server:
            plane = on_plane(server.url)
            result = DecisionService(ClefDecisionProvider(plane, blocking=True)).decide(request())
            self.assertEqual(result.provider_mode, "mock")
            plane.close()

    def test_stale_decision_is_dropped_by_apply_if_fresh(self):
        with self.serve() as server:
            plane = on_plane(server.url)
            service = DecisionService(ClefDecisionProvider(plane, blocking=True), log=DecisionLog(None))
            result = service.decide(request(revision=1))
            self.assertFalse(service.apply_if_fresh(request(revision=1), result, world_epoch="E1", state_revision=2))
            self.assertFalse(service.apply_if_fresh(request(revision=1), result, world_epoch="E2", state_revision=1))
            self.assertEqual(service.counts["stale_dropped"], 2)
            plane.close()

    def test_every_role_round_trips(self):
        cases = {"resident": ("urgent_react", [{"human_id": "h_1", "local_state": {"threat": 90}}]),
                 "dialogue": ("talk_reply", [{"speaker_id": "p", "prompt_case": {"allowed_physical_intents": ["flee"]}}]),
                 "world": ("decree", [{"query": "rain"}])}
        with self.serve() as server:
            plane = on_plane(server.url, modes=("tier3_resident", "tier3_dialogue", "tier3_world"))
            for role, (mode, case) in cases.items():
                outcome = plane.client.call_sync(Job(role=role, payload={"mode": mode, "cases": case}, world_epoch="E1", state_revision=1))
                with self.subTest(role=role):
                    self.assertEqual(outcome.status, "ok")
                    self.assertEqual(outcome.response.provider_mode, "mock")
            plane.close()

    def test_priority_order_critical_before_background(self):
        gate = threading.Event()
        order = []

        def handler(url, body):
            gate.wait(5)
            order.append(body["priority"])
            return 500, "no"

        transport = ScriptedTransport(handler)
        cfg = config_for("http://x", workers=1)
        plane = ModelPlane(cfg, ModelSwitch(modes={"tier2": "on"}), transport=transport)
        plane.submit_decision(request(1, priority="background"))
        wait_for(lambda: transport.calls)                                  # the single worker is now inside the handler
        plane.submit_decision(request(2, priority="background"))
        plane.submit_decision(request(3, priority="critical"))
        plane.submit_decision(request(4, priority="active"))
        gate.set()
        wait_for(lambda: len(order) == 4)
        self.assertEqual(order, ["background", "critical", "active", "background"])
        plane.close()

    def test_toggle_drops_in_flight_jobs_and_counts_them(self):
        gate = threading.Event()
        transport = ScriptedTransport(lambda url, body: (gate.wait(5), (500, "x"))[1])
        plane = ModelPlane(config_for("http://x"), ModelSwitch(modes={"tier2": "on"}), transport=transport)
        self.assertIsNone(plane.submit_decision(request()))
        wait_for(lambda: transport.calls)
        plane.set_modes(tier2="shadow")                                    # a toggle bumps the model epoch
        gate.set()
        done = drain_until(plane, 1)
        self.assertEqual((done[0].outcome.status, done[0].outcome.reason), ("dropped", "stale_model_epoch"))
        self.assertEqual(plane.status()["metrics"]["decide"]["active"]["stale_drops"], 1)
        plane.close()

    def test_toggle_to_off_drops_a_good_answer_that_arrives_late(self):
        with self.serve(faults=[{"kind": "slow", "rate": 1.0, "delay_ms": 150}]) as server:
            plane = on_plane(server.url)
            plane.submit_decision(request())
            plane.set_modes(tier2="off")
            done = drain_until(plane, 1)
            self.assertEqual(done[0].outcome.status, "dropped")
            self.assertEqual(len(plane.decisions), 0)
            plane.close()

    def test_submit_never_blocks_the_tick(self):
        release = threading.Event()
        plane = ModelPlane(config_for("http://x", workers=1), ModelSwitch(modes={"tier2": "on"}),
                           transport=ScriptedTransport(lambda url, body: (release.wait(5), (500, "x"))[1]))
        times = []
        for i in range(200):
            started = time.perf_counter()
            plane.submit_decision(request(i))
            plane.pump()
            times.append((time.perf_counter() - started) * 1000.0)
        release.set()
        self.assertLess(sorted(times)[-3], 5.0, f"slowest submit+pump calls (ms): {sorted(times)[-3:]}")
        plane.close()


class FaultTests(unittest.TestCase):
    def run_fault(self, spec, deadline_ms=300, **client_kw):
        server = ServerThread(create_app(ServerConfig(faults=[spec])))
        with server:
            plane = on_plane(server.url, **client_kw)
            outcome = plane.client.call_sync(Job(role="decide", payload={"resident_id": "h_1", "trigger": "t:1", "question_kind": "choice",
                                                                       "options": [{"id": "a"}, {"id": "b"}]},
                                                 world_epoch="E1", state_revision=1, deadline_ms=deadline_ms))
            plane.close()
            return outcome

    def test_each_injected_fault_ends_as_a_fallback_with_a_reason(self):
        expected = {"hang": "timeout", "slow": "http_504", "error500": "http_500", "garbage": ("bad_json", "invalid_reply"),
                    "bad_result": "invalid_reply", "stale": "stale_reply"}
        for kind, reasons in expected.items():
            spec = {"kind": kind, "rate": 1.0, "delay_ms": 2500 if kind == "hang" else 1500, "variant": 0}
            outcome = self.run_fault(spec)
            with self.subTest(kind=kind):
                self.assertEqual(outcome.status, "fallback")
                self.assertTrue(outcome.reason.startswith(reasons), outcome.reason)

    def test_breaker_opens_after_repeated_failures_and_stops_calling(self):
        transport = ScriptedTransport(lambda url, body: (500, "boom"))
        cfg = config_for("http://x", breaker_threshold=3, breaker_open_s=60.0)
        plane = ModelPlane(cfg, ModelSwitch(modes={"tier2": "on"}), transport=transport)
        for i in range(3):
            plane.client.call_sync(Job(role="decide", payload={"resident_id": "h", "trigger": "t", "question_kind": "choice",
                                                              "options": [{"id": "a"}]}, world_epoch="E", state_revision=i, job_id=f"j{i}"))
        calls = len(transport.calls)
        outcome = plane.submit_decision(request(9))
        self.assertEqual((outcome.status, outcome.reason), ("fallback", "breaker_open"))
        self.assertEqual(len(transport.calls), calls)
        self.assertEqual(plane.status()["client"]["breakers"]["http://x/v1/decide"]["state"], "open")
        plane.close()

    def test_pulling_the_server_out_degrades_to_rules(self):
        server = ServerThread(create_app(ServerConfig()))
        with server:
            plane = on_plane(server.url, breaker_threshold=2, breaker_open_s=60.0)
            service = DecisionService(ClefDecisionProvider(plane, blocking=True))
            self.assertEqual(service.decide(request(1, deadline_ms=500)).provider_mode, "mock")
        for n in range(2, 8):
            result = service.decide(request(n, deadline_ms=500))
            self.assertEqual((result.provider_mode, result.top_option), ("fallback", "a"))
        self.assertEqual(plane.status()["client"]["breakers"][f"{server.url}/v1/decide"]["state"], "open")
        plane.close()


class BreakerTests(unittest.TestCase):
    def test_closed_open_half_open_closed(self):
        now = [0.0]
        breaker = CircuitBreaker(3, 5.0, clock=lambda: now[0])
        for _ in range(2):
            breaker.record_failure()
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertEqual((breaker.state, breaker.allow()), ("open", False))
        now[0] = 5.5
        self.assertEqual(breaker.state, "half_open")
        self.assertTrue(breaker.allow())
        self.assertFalse(breaker.allow())            # only one probe at a time
        breaker.record_failure()                      # a failed probe re-opens immediately
        self.assertEqual(breaker.state, "open")
        now[0] = 11.0
        self.assertTrue(breaker.allow())
        breaker.record_success()
        self.assertEqual((breaker.state, breaker.snapshot()["consecutive_failures"]), ("closed", 0))


class AdmissionTests(unittest.TestCase):
    def make(self, **kw):
        self.now = [0.0]
        limits = {"decide": {"max_in_flight": 2, "per_minute": 3}}
        return Admission(limits, clock=lambda: self.now[0], **kw)

    def test_in_flight_cap_and_release(self):
        a = self.make(cooldown_s=0)
        self.assertTrue(a.admit("decide")[0] and a.admit("decide")[0])
        self.assertEqual(a.admit("decide"), (False, "budget_in_flight"))
        a.release("decide")
        self.assertTrue(a.admit("decide")[0])

    def test_rate_per_game_minute_slides(self):
        a = self.make(cooldown_s=0)
        for _ in range(3):
            self.assertTrue(a.admit("decide")[0])
            a.release("decide")
        self.assertEqual(a.admit("decide"), (False, "budget_rate"))
        self.now[0] = 61.0
        self.assertTrue(a.admit("decide")[0])

    def test_per_resident_cooldown(self):
        a = self.make(cooldown_s=2.0)
        self.assertTrue(a.admit("decide", resident_id="h_1")[0])
        a.release("decide")
        self.assertEqual(a.admit("decide", resident_id="h_1"), (False, "cooldown"))
        self.assertTrue(a.admit("decide", resident_id="h_2")[0])
        self.now[0] = 2.5
        a.release("decide")
        self.assertTrue(a.admit("decide", resident_id="h_1")[0])

    def test_dedupe_by_causal_event_id_with_ttl_and_forget(self):
        a = self.make(cooldown_s=0)
        self.assertTrue(a.admit("decide", causal_id="attack:e7")[0])
        a.release("decide")
        self.assertEqual(a.admit("decide", causal_id="attack:e7"), (False, "duplicate"))
        a.forget("decide", "attack:e7")
        self.assertTrue(a.admit("decide", causal_id="attack:e7")[0])
        a.release("decide")
        self.now[0] = 200.0
        self.assertTrue(a.admit("decide", causal_id="attack:e7")[0])

    def test_escalation_is_bounded_and_never_loops_back(self):
        a = Admission({"decide": {"max_in_flight": 9, "per_minute": 99}, "resident": {"max_in_flight": 9, "per_minute": 99}},
                      cooldown_s=0, max_depth=1, clock=lambda: 0.0)
        self.assertTrue(a.admit("resident", depth=1, parent_tier=2, tier=3)[0])          # tier 2 -> tier 3 is fine
        self.assertEqual(a.admit("resident", depth=2, parent_tier=2, tier=3), (False, "escalation_depth"))
        self.assertEqual(a.admit("decide", depth=1, parent_tier=3, tier=2), (False, "escalation_loop"))
        self.assertEqual(a.admit("resident", depth=1, parent_tier=3, tier=3), (False, "escalation_loop"))


class ClientBudgetIntegrationTests(unittest.TestCase):
    def test_cooldown_and_duplicate_skip_before_any_network_call(self):
        transport = ScriptedTransport(lambda url, body: (500, "x"))
        cfg = config_for("http://x")
        cfg.cooldown_s = 5.0
        plane = ModelPlane(cfg, ModelSwitch(modes={"tier2": "on"}), transport=transport)
        self.assertIsNone(plane.submit_decision(request(1, resident="h_1", trigger="e:1")))
        self.assertEqual(plane.submit_decision(request(2, resident="h_1", trigger="e:2")).reason, "cooldown")
        self.assertEqual(plane.submit_decision(request(3, resident="h_2", trigger="e:1")).reason, "duplicate")
        wait_for(lambda: len(transport.calls) == 1)
        self.assertEqual(len(transport.calls), 1)
        plane.close()

    def test_escalation_depth_blocks_a_second_hop(self):
        plane = ModelPlane(config_for("http://x"), ModelSwitch(modes={"tier3_resident": "on"}), transport=NoNetworkTransport())
        job = Job(role="resident", payload={"mode": "resident_reasoning", "cases": [{}]}, world_epoch="E", state_revision=1, depth=2, parent_tier=2)
        self.assertEqual(plane.client.submit(job).reason, "escalation_depth")
        plane.close()


class ShadowModeTests(unittest.TestCase):
    def test_shadow_applies_rules_and_logs_the_models_answer_beside_it(self):
        with ServerThread(create_app(ServerConfig())) as server:
            log = DecisionLog(None)
            plane = on_plane(server.url, mode="shadow")
            plane.log = log
            service = DecisionService(ClefDecisionProvider(plane), log=log)
            results = [service.decide(request(n, options=("a", "b", "c", "d"))) for n in range(1, 9)]
            self.assertTrue(all(r.provider_mode == "rules" and r.top_option == "a" for r in results))   # rules answer is applied
            drain_until(plane, 8)
            shadows = [r for r in log.records if r.get("type") == "shadow"]
            self.assertEqual(len(shadows), 8)
            for rec in shadows:
                self.assertEqual(rec["standin_top"], "a")
                self.assertIn(rec["model_top"], "abcd")
                self.assertEqual(rec["agree"], rec["model_top"] == "a")
            metrics = plane.status()["metrics"]["decide"]["active"]
            self.assertEqual(metrics["agreed"] + metrics["disagreed"], 8)
            self.assertIsNotNone(metrics["agreement"])
            self.assertEqual(len(plane.decisions), 0)          # a shadow answer is never served as a decision
            plane.close()


class LegacyAdapterTests(unittest.TestCase):
    TALK = {"speaker_id": "p", "listener_id": "h_1", "prompt_case": {"utterance": "hi", "allowed_physical_intents": ["flee", "call_help"]}}

    def test_on_mode_is_pull_based_and_keeps_the_legacy_packet_contract(self):
        with ServerThread(create_app(ServerConfig())) as server:
            plane = on_plane(server.url, modes=("tier3_dialogue", "tier3_resident"))
            handler, engine = LegacyModelHandler(plane), FakeEngine()
            self.assertEqual(handler(mode="talk_reply", cases=[self.TALK], engine=engine), [None])   # stand-in used this time
            self.assertTrue(wait_for(lambda: (plane.pump(), len(plane.answers))[1] >= 1))
            [answer] = handler(mode="talk_reply", cases=[self.TALK], engine=engine)
            self.assertIn(answer["packet"]["physical_intent"], ("flee", "call_help"))
            self.assertTrue(answer["packet"]["speech_text"])
            self.assertEqual(answer["source"], "mock_model_server")
            self.assertEqual(handler(mode="talk_reply", cases=[self.TALK], engine=engine), [None])   # an answer is applied once
            urgent = {"human_id": "h_1", "local_state": {"threat": 90}}
            handler(mode="urgent_react", cases=[urgent], engine=engine)
            self.assertTrue(wait_for(lambda: (plane.pump(), len(plane.answers))[1] >= 1))
            urgent["local_state"]["threat"] = 91                 # volatile numbers changed: still the same question
            [reaction] = handler(mode="urgent_react", cases=[urgent], engine=engine)
            self.assertIn(reaction["packet"]["intent"], ("flee_predator", "guard"))
            plane.close()

    def test_resident_reasoning_through_the_world_handler_uses_the_resident_role(self):
        transport = ScriptedTransport(lambda url, body: (500, "x"))
        plane = ModelPlane(config_for("http://x"), ModelSwitch(modes={"tier3_resident": "on"}), transport=transport)
        LegacyModelHandler(plane)(mode="resident_reasoning", cases=[{"resident_id": "h_1"}], engine=FakeEngine())
        wait_for(lambda: transport.calls)
        self.assertTrue(transport.calls[0][0].endswith("/v1/resident"))
        self.assertEqual(transport.calls[0][1]["payload"]["mode"], "resident_reasoning")
        plane.close()

    def test_shadow_mode_logs_but_never_returns_an_answer(self):
        with ServerThread(create_app(ServerConfig())) as server:
            plane = on_plane(server.url, modes=("tier3_world",), mode="shadow")
            plane.log = DecisionLog(None)
            handler = LegacyModelHandler(plane)
            self.assertIsNone(handler(mode="decree", cases=[{"query": "rain"}], engine=FakeEngine()))
            drain_until(plane, 1)
            self.assertIsNone(handler(mode="decree", cases=[{"query": "rain"}], engine=FakeEngine()))
            self.assertEqual([r["role"] for r in plane.log.records if r.get("type") == "shadow"], ["world"])
            plane.close()

    def test_answers_from_another_world_epoch_are_not_served(self):
        with ServerThread(create_app(ServerConfig())) as server:
            plane = on_plane(server.url, modes=("tier3_dialogue",))
            handler, engine = LegacyModelHandler(plane), FakeEngine()
            handler(mode="talk_reply", cases=[self.TALK], engine=engine)
            wait_for(lambda: (plane.pump(), len(plane.answers))[1] >= 1)
            engine.world_epoch = "E2"
            self.assertEqual(handler(mode="talk_reply", cases=[self.TALK], engine=engine), [None])
            plane.close()

    def test_install_and_uninstall_restore_the_original_handlers(self):
        engine, plane = FakeEngine(), ModelPlane(ModelPlaneConfig(), ModelSwitch(), transport=NoNetworkTransport())
        original = object()
        engine.world_model_handler = original
        state = {}
        plane.on_switch(lambda snap: sync_installation(engine, plane, state))
        sync_installation(engine, plane, state)
        self.assertIs(engine.world_model_handler, original)                   # all off: untouched
        plane.set_modes(tier3_world="shadow")
        self.assertIsInstance(engine.world_model_handler, LegacyModelHandler)
        self.assertIsInstance(engine.tiny_model_handler, LegacyModelHandler)
        plane.set_modes(tier3_world="off")
        self.assertIs(engine.world_model_handler, original)
        self.assertIsNone(engine.tiny_model_handler)
        restore = install(engine, plane)
        restore()
        self.assertIs(engine.world_model_handler, original)


class RoutesTests(unittest.TestCase):
    def make(self):
        engine = FakeEngine()
        plane = ModelPlane(ModelPlaneConfig(), ModelSwitch(), transport=NoNetworkTransport())
        app = FastAPI()
        app.include_router(build_model_router(lambda: engine, plane))
        return engine, plane, TestClient(app)

    def test_status_defaults_off(self):
        engine, plane, client = self.make()
        body = client.get("/model_status").json()
        self.assertEqual((body["ok"], body["switch"]["tier2"], body["switch"]["tier1"], body["network_enabled"], body["saved_in_worlds"]),
                         (True, "off", "rules", False, False))
        self.assertEqual(body["model_epoch"], 0)

    def test_control_models_flips_modes_and_bumps_the_epoch(self):
        engine, plane, client = self.make()
        body = client.post("/control/models", json={"tier2": "shadow", "tier3_resident": "on"}).json()
        self.assertTrue(body["ok"])
        self.assertEqual((body["tier2"], body["tier3_resident"], body["epoch"]), ("shadow", "on", 1))
        self.assertIsInstance(engine.tiny_model_handler, LegacyModelHandler)
        self.assertEqual(client.post("/control/models", json={"tier2": "shadow"}).json()["changed"], {})
        self.assertEqual(client.post("/control/models", json={"all_off": True}).json()["tier3_resident"], "off")
        self.assertIsNone(engine.tiny_model_handler)
        self.assertEqual(client.get("/model_status").json()["model_epoch"], 2)

    def test_bad_requests_are_400_and_change_nothing(self):
        engine, plane, client = self.make()
        for body in ({"tier2": "maybe"}, {"tier9": "on"}, {"tier1": "neural"}, [1], {"tier2": "on", "tier3_world": "x"}):
            reply = client.post("/control/models", json=body)
            self.assertEqual((reply.status_code, reply.json()["ok"]), (400, False), body)
        self.assertEqual(plane.switch.snapshot()["epoch"], 0)
        self.assertEqual(client.post("/control/models", content="nope").status_code, 400)

    def test_decision_status_field_shows_model_state(self):
        from systems.commission.engine import decision_service
        engine, plane, client = self.make()
        client.post("/control/models", json={"tier2": "shadow"})
        self.assertEqual(decision_service(engine).status()["models"]["tier2"], "shadow")


if __name__ == "__main__":
    unittest.main()
