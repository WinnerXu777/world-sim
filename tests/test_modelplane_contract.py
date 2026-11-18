"""Wire contract v1, schema export, mock/rules/recorded/openai_compat/clef backends and the FastAPI server (in-process)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import httpx
from fastapi.testclient import TestClient

from model_server import contract as c
from model_server import schema
from model_server.app import create_app
from model_server.backends import (BackendError, CallContext, ClefBackend, MockBackend, OpenAICompatBackend, RecordedBackend,
                                   Recorder, RulesBackend, make_backend)
from model_server.config import ServerConfig


def decide_env(job="j1", options=("a", "b", "c"), **over):
    body = {"job_id": job, "role": "decide", "world_epoch": "E1", "state_revision": 4, "deadline_ms": 1000,
            "payload": {"resident_id": "h_1", "trigger": "t:1", "question_kind": "choice",
                        "options": [{"id": i, "description": f"option {i}"} for i in options]}}
    body.update(over)
    return body


def batch_env(role, mode, cases, job="b1"):
    return {"job_id": job, "role": role, "world_epoch": "E1", "state_revision": 4, "payload": {"mode": mode, "cases": cases}}


CASES = {
    ("resident", "urgent_react"): [{"human_id": "h_1", "local_state": {"threat": 80}}],
    ("resident", "normal_live"): [{"human_id": "h_1", "local_state": {"hunger": 71, "thirst": 42}}],
    ("resident", "resident_reasoning"): [{"resident_id": "h_1", "reason": "attack_event"}],
    ("dialogue", "talk_reply"): [{"speaker_id": "p", "listener_id": "h_1",
                                  "prompt_case": {"utterance": "hello", "allowed_physical_intents": ["flee", "call_help"]}}],
    ("dialogue", "ambient_npc_talk"): [{"speaker_id": "h_1", "listener_id": "h_2", "prompt_case": {"speech_act": "warn"}}],
    ("world", "decree"): [{"world_model_mode": "decree", "query": "bless the harvest"}],
}


class ContractTests(unittest.TestCase):
    def test_envelope_round_trip_and_defaults(self):
        env = c.parse_envelope(decide_env())
        self.assertEqual((env.priority, env.cancel_token, env.schema_version), ("active", "", 1))
        self.assertEqual(list(env.to_dict())[:5], ["job_id", "role", "world_epoch", "state_revision", "priority"])

    def test_bad_envelopes_are_rejected_with_codes(self):
        cases = {
            "malformed_request": [None, [], decide_env(job_id=""), decide_env(state_revision=-1), decide_env(state_revision=True),
                                  decide_env(priority="urgent"), decide_env(deadline_ms=0), decide_env(deadline_ms=10 ** 9),
                                  decide_env(payload="x"), decide_env(cancel_token=5)],
            "schema_version_unsupported": [decide_env(schema_version=2)],
            "unknown_role": [decide_env(role="oracle")],
            "invalid_payload": [decide_env(payload={}), batch_env("resident", "decree", [{}]), batch_env("world", "decree", []),
                                batch_env("dialogue", "talk_reply", ["x"])],
        }
        for code, bodies in cases.items():
            for body in bodies:
                with self.subTest(code=code, body=str(body)[:60]):
                    with self.assertRaises(c.ContractError) as ctx:
                        c.parse_envelope(body)
                    self.assertEqual(ctx.exception.code, code)

    def test_duplicate_and_empty_option_ids_rejected(self):
        for opts in (("a", "a"), ("",)):
            with self.assertRaises(c.ContractError):
                c.parse_envelope(decide_env(options=opts))

    def test_probability_validation(self):
        ids = ["a", "b"]
        self.assertEqual(c.validate_probabilities(ids, {"a": 0.25, "b": 0.75}), {"a": 0.25, "b": 0.75})
        for bad in ({"a": 1.0}, {"a": 0.5, "b": 0.5, "c": 0.0}, {"a": 0.5, "b": 0.6}, {"a": -0.1, "b": 1.1},
                    {"a": float("nan"), "b": 1.0}, {"a": "x", "b": 1.0}, {"a": True, "b": 0.0}, [0.5, 0.5], None):
            with self.subTest(bad=bad):
                with self.assertRaises(c.ContractError):
                    c.validate_probabilities(ids, bad)

    def test_talk_reply_physical_intent_must_be_an_allowed_intent(self):
        payload = batch_env("dialogue", "talk_reply", CASES[("dialogue", "talk_reply")])["payload"]
        good = {"mode": "talk_reply", "responses": [{"packet": {"speech_text": "Go away", "physical_intent": "flee"}}]}
        self.assertEqual(c.validate_result("dialogue", payload, good)["responses"][0]["packet"]["physical_intent"], "flee")
        for bad in ({"speech_text": "Go away", "physical_intent": "teleport"}, {"speech_text": "", "physical_intent": ""},
                    {"speech_text": "x" * 501}, "text"):
            with self.assertRaises(c.ContractError):
                c.validate_result("dialogue", payload, {"mode": "talk_reply", "responses": [{"packet": bad}]})

    def test_response_count_and_mode_must_match(self):
        payload = {"mode": "urgent_react", "cases": [{}, {}]}
        one = {"mode": "urgent_react", "responses": [{"packet": {"intent": "guard"}}]}
        with self.assertRaises(c.ContractError):
            c.validate_result("resident", payload, one)
        with self.assertRaises(c.ContractError):
            c.validate_result("resident", {"mode": "urgent_react", "cases": [{}]}, {"mode": "normal_live", "responses": one["responses"]})

    def test_parse_response_detects_stale_and_bad_replies(self):
        env = c.parse_envelope(decide_env())
        good = {"job_id": "j1", "role": "decide", "world_epoch": "E1", "state_revision": 4, "provider_mode": "mock", "latency_ms": 1.0,
                "ok": True, "result": {"probabilities": {"a": 0.2, "b": 0.3, "c": 0.5}}}
        self.assertEqual(c.parse_response(good, env).result["probabilities"]["c"], 0.5)
        for patch, code in (({"world_epoch": "E0"}, "stale_reply"), ({"state_revision": 5}, "stale_reply"), ({"job_id": "other"}, "stale_reply"),
                            ({"provider_mode": "magic"}, "bad_reply"), ({"latency_ms": -1}, "bad_reply"),
                            ({"result": {"probabilities": {"a": 1.0}}}, "backend_error"), ({"schema_version": 9}, "bad_reply")):
            with self.subTest(patch=patch):
                with self.assertRaises(c.ContractError) as ctx:
                    c.parse_response({**good, **patch}, env)
                self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(c.ContractError):
            c.parse_response({**good, "ok": False, "error": {"code": "deadline_exceeded", "message": "slow"}}, env)


class SchemaExportTests(unittest.TestCase):
    def test_committed_schema_files_match_the_dataclasses(self):
        def disk(path):
            return path.read_bytes().decode("utf-8").replace("\r\n", "\n")   # a checkout may convert line endings

        self.assertEqual(disk(schema.SCHEMA_PATH), schema.render(schema.json_schema()),
                         "regenerate with: python -m model_server.schema --write")
        self.assertEqual(disk(schema.OPENAPI_PATH), schema.render(schema.openapi()))

    def test_schema_describes_the_envelope(self):
        defs = schema.json_schema()["$defs"]
        envelope = defs["Envelope"]
        self.assertEqual(envelope["required"], ["job_id", "role", "world_epoch", "state_revision", "payload"])
        self.assertEqual(envelope["properties"]["role"]["enum"], list(c.ROLES))
        self.assertEqual(defs["ResponseEnvelope"]["properties"]["provider_mode"]["enum"], list(c.PROVIDER_MODES))
        self.assertEqual(defs["DecideResult"]["properties"]["probabilities"]["additionalProperties"], {"type": "number"})
        self.assertEqual(sorted(schema.openapi()["paths"]), ["/health", "/ready", "/v1/cancel", "/v1/contract", "/v1/decide", "/v1/dialogue",
                                                              "/v1/models", "/v1/resident", "/v1/world"])
        json.dumps(schema.openapi())


class BackendTests(unittest.TestCase):
    def ctx(self):
        return CallContext(1.0)

    def test_mock_is_deterministic_and_valid_for_every_role_and_mode(self):
        backend = MockBackend()
        first = backend.handle(c.parse_envelope(decide_env()), self.ctx())
        again = backend.handle(c.parse_envelope(decide_env(job="other-job")), self.ctx())
        self.assertEqual(first, again)   # depends on resident, trigger and options, not on the job id
        self.assertAlmostEqual(sum(first["probabilities"].values()), 1.0)
        for (role, mode), cases in CASES.items():
            with self.subTest(role=role, mode=mode):
                env = c.parse_envelope(batch_env(role, mode, cases))
                result = backend.handle(env, self.ctx())
                self.assertEqual(c.validate_result(role, env.payload, result)["mode"], mode)
                self.assertEqual(result, backend.handle(env, self.ctx()))

    def test_single_option_gets_probability_one(self):
        env = c.parse_envelope(decide_env(options=("only",)))
        self.assertEqual(MockBackend().handle(env, self.ctx()), {"probabilities": {"only": 1.0}})

    def test_rules_backend_matches_the_game_scorer(self):
        from systems.commission.decide import make_rules_provider
        from systems.decision.contract import DecisionOption, DecisionRequest
        state = {"closeness": 0.6, "rival": False, "traits": {"greed": 0.7, "discipline": 0.4}, "pressures": {"security": 0.2}}
        ids = ["accept_commission", "refuse_no_materials", "refuse_busy"]
        env = c.parse_envelope(decide_env(options=ids))
        env.payload.update(topic="commission", state=state)
        got = RulesBackend().handle(env, self.ctx())["probabilities"]
        req = DecisionRequest("j1", "h_1", "E1", 4, 0, "t:1", "choice", tuple(DecisionOption(i) for i in ids), state, topic="commission")
        want = make_rules_provider().decide(req)
        for key in ids:
            self.assertAlmostEqual(got[key], want[key], places=9)

    def test_recorded_replays_decision_logs_and_misses_raise(self):
        rec = RecordedBackend(records=[{"type": "decision", "resident_id": "h_1", "trigger": "t:1",
                                        "probabilities": {"a": 0.1, "b": 0.2, "c": 0.7}}])
        self.assertEqual(rec.handle(c.parse_envelope(decide_env()), self.ctx())["probabilities"]["c"], 0.7)
        with self.assertRaises(BackendError):
            rec.handle(c.parse_envelope(decide_env(payload={**decide_env()["payload"], "trigger": "t:2"})), self.ctx())
        self.assertFalse(RecordedBackend(path=str(ROOT / "does" / "not" / "exist.jsonl")).ready()[0])

    def test_recorder_writes_a_corpus_the_recorded_backend_replays(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "corpus.jsonl")
            recorder = Recorder(MockBackend(), path)
            env = c.parse_envelope(batch_env("dialogue", "ambient_npc_talk", CASES[("dialogue", "ambient_npc_talk")]))
            wanted = recorder.handle(env, self.ctx())
            self.assertEqual(RecordedBackend(path=path).handle(env, self.ctx()), wanted)

    def test_clef_backend_is_a_documented_stub(self):
        backend = ClefBackend()
        self.assertFalse(backend.ready()[0])
        with self.assertRaises(BackendError) as ctx:
            backend.handle(c.parse_envelope(decide_env()), self.ctx())
        self.assertEqual(ctx.exception.code, "backend_not_implemented")
        self.assertIn("held", ctx.exception.message)

    def test_make_backend_rejects_unknown_kinds(self):
        with self.assertRaises(ValueError):
            make_backend("gpt-nine")

    def test_openai_compat_parses_upstream_json_and_maps_failures(self):
        seen = {}

        def upstream(request: httpx.Request):
            seen["auth"] = request.headers.get("authorization")
            seen["model"] = json.loads(request.content)["model"]
            return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"a\": 0.9, \"b\": 0.05, \"c\": 0.05}\n```"}}]})

        import os
        os.environ["EDEN_TEST_KEY"] = "secret-value"
        try:
            backend = OpenAICompatBackend("http://upstream.invalid/v1", "EDEN_TEST_KEY", "tiny-model",
                                          client=httpx.Client(transport=httpx.MockTransport(upstream)))
            out = backend.handle(c.parse_envelope(decide_env()), self.ctx())
            self.assertEqual(out["probabilities"]["a"], 0.9)
            self.assertEqual((seen["auth"], seen["model"]), ("Bearer secret-value", "tiny-model"))
            for handler, code in ((lambda r: httpx.Response(500), "backend_unavailable"),
                                  (lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no json here"}}]}), "backend_error"),
                                  (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), "backend_unavailable")):
                bad = OpenAICompatBackend("http://upstream.invalid/v1", "EDEN_TEST_KEY", "tiny-model",
                                          client=httpx.Client(transport=httpx.MockTransport(handler)))
                with self.assertRaises(BackendError) as ctx:
                    bad.handle(c.parse_envelope(decide_env()), self.ctx())
                self.assertEqual(ctx.exception.code, code)
        finally:
            del os.environ["EDEN_TEST_KEY"]
        self.assertFalse(OpenAICompatBackend("", "", "").ready()[0])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ServerConfig(fault_admin=True))
        cls.client = TestClient(cls.app)

    def post(self, role, body, **kw):
        return self.client.post(f"/v1/{role}", json=body, **kw)

    def test_every_role_answers_with_a_full_envelope(self):
        reply = self.post("decide", decide_env())
        self.assertEqual(reply.status_code, 200)
        body = reply.json()
        self.assertEqual((body["ok"], body["provider_mode"], body["model_id"], body["world_epoch"], body["state_revision"]),
                         (True, "mock", "mock-v1", "E1", 4))
        self.assertGreaterEqual(body["latency_ms"], 0)
        for (role, mode), cases in CASES.items():
            with self.subTest(role=role, mode=mode):
                body = self.post(role, batch_env(role, mode, cases)).json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["result"]["mode"], mode)
                self.assertEqual(len(body["result"]["responses"]), len(cases))

    def test_error_behaviour(self):
        self.assertEqual(self.client.post("/v1/decide", content="not json").status_code, 400)
        self.assertEqual(self.client.post("/v1/decide", content="[1]").json()["error"]["code"], "malformed_request")
        self.assertEqual(self.post("decide", decide_env(schema_version=7)).json()["error"]["code"], "schema_version_unsupported")
        self.assertEqual(self.post("resident", decide_env()).json()["error"]["code"], "malformed_request")   # role vs route
        bad = self.post("decide", decide_env(options=("a", "a")))
        self.assertEqual((bad.status_code, bad.json()["error"]["code"], bad.json()["ok"]), (400, "invalid_payload", False))
        self.assertEqual(self.client.get("/v1/nothing").status_code, 404)

    def test_health_ready_models_contract(self):
        self.assertEqual(self.client.get("/health").json()["ok"], True)
        self.assertEqual(self.client.get("/ready").status_code, 200)
        models = self.client.get("/v1/models").json()["models"]
        self.assertEqual(sorted(models), sorted(c.ROLES))
        self.assertEqual(self.client.get("/v1/contract").json()["$id"], "eden-model-contract-v1")

    def test_a_slow_backend_is_cut_off_at_the_deadline_with_504(self):
        app = create_app(ServerConfig(faults=[{"kind": "slow", "rate": 1.0, "delay_ms": 600}]))
        reply = TestClient(app).post("/v1/decide", json=decide_env(deadline_ms=80))
        self.assertEqual((reply.status_code, reply.json()["error"]["code"], reply.json()["error"]["retryable"]), (504, "deadline_exceeded", True))

    def test_unready_backend_reports_503_on_ready_and_501_on_calls(self):
        config = ServerConfig(backends={role: ("clef", {}) for role in c.ROLES})
        client = TestClient(create_app(config))
        self.assertEqual(client.get("/ready").status_code, 503)
        reply = client.post("/v1/decide", json=decide_env())
        self.assertEqual((reply.status_code, reply.json()["error"]["code"]), (501, "backend_not_implemented"))

    def test_each_fault_kind_produces_the_documented_failure(self):
        def run(spec, role="decide", env=None):
            app = create_app(ServerConfig(faults=[spec]))
            return TestClient(app).post(f"/v1/{role}", json=env or decide_env())

        self.assertEqual(run({"kind": "error500"}).status_code, 500)
        for variant in range(4):
            reply = run({"kind": "garbage", "variant": variant})
            self.assertEqual(reply.status_code, 200)
            with self.assertRaises(Exception):
                c.parse_response(reply.json(), c.parse_envelope(decide_env()))
        stale = run({"kind": "stale"}).json()
        with self.assertRaises(c.ContractError) as ctx:
            c.parse_response(stale, c.parse_envelope(decide_env()))
        self.assertEqual(ctx.exception.code, "stale_reply")
        for variant in range(3):
            for role, mode in (("decide", None), ("dialogue", "talk_reply"), ("resident", "resident_reasoning"), ("world", "decree")):
                env = decide_env() if role == "decide" else batch_env(role, mode, CASES[(role, mode)])
                body = run({"kind": "bad_result", "variant": variant}, role, env).json()
                with self.subTest(variant=variant, role=role):
                    with self.assertRaises(c.ContractError):
                        c.parse_response(body, c.parse_envelope(env))

    def test_fault_selection_is_deterministic_per_job(self):
        spec = {"kind": "error500", "rate": 0.5}
        first = [create_app(ServerConfig(faults=[spec], fault_seed=3)).state.faults.pick(f"job{i}", "decide", "error500") is not None
                 for i in range(40)]
        again = [create_app(ServerConfig(faults=[spec], fault_seed=3)).state.faults.pick(f"job{i}", "decide", "error500") is not None
                 for i in range(40)]
        self.assertEqual(first, again)
        self.assertTrue(0 < sum(first) < 40)

    def test_fault_admin_route_sets_faults_at_runtime(self):
        client = TestClient(create_app(ServerConfig(fault_admin=True)))
        self.assertEqual(client.post("/v1/decide", json=decide_env()).status_code, 200)
        self.assertTrue(client.post("/v1/mock/faults", json={"faults": [{"kind": "error500"}]}).json()["ok"])
        self.assertEqual(client.post("/v1/decide", json=decide_env()).status_code, 500)
        self.assertEqual(client.post("/v1/mock/faults", json={"faults": [{"kind": "nope"}]}).status_code, 400)
        self.assertEqual(TestClient(create_app(ServerConfig())).post("/v1/mock/faults", json={}).status_code, 404)

    def test_cancel_token_abandons_work(self):
        client = TestClient(create_app(ServerConfig()))
        self.assertTrue(client.post("/v1/cancel", json={"cancel_token": "tok"}).json()["ok"])
        reply = client.post("/v1/decide", json=decide_env(cancel_token="tok"))
        self.assertEqual((reply.status_code, reply.json()["error"]["code"]), (409, "cancelled"))
        self.assertEqual(client.post("/v1/cancel", json={}).status_code, 400)

    def test_oversized_body_is_refused(self):
        client = TestClient(create_app(ServerConfig(max_body_bytes=200)))
        self.assertEqual(client.post("/v1/decide", json=decide_env()).status_code, 400)


if __name__ == "__main__":
    unittest.main()
