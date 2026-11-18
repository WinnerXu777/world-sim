"""Conformance check for a model endpoint: does it speak wire contract v1 well enough to be switched on?

    python tools/model_conformance.py http://127.0.0.1:8100 --role all
    python tools/model_conformance.py https://my-host --role decide --key-env MY_API_KEY --model-id my-model
    python tools/model_conformance.py --selftest            # starts the bundled mock server on an ephemeral port and checks it

Checks per role: schema of the reply envelope and result, echo of job_id / world_epoch / state_revision, provider_mode, probability
sums and option-set equality (decide), one packet per case and packet structure (resident, dialogue, world), the deadline (an answer or
a clean 504 within the request's deadline_ms plus grace), error behaviour (malformed JSON, wrong schema_version, wrong role, empty
options all answer 4xx with an error body, never 5xx or a hang), and a small concurrency burst. Prints PASS/FAIL per check and exits 0
only when every check passes. The API key is read from the NAMED environment variable and never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from model_server import contract as c

GRACE_S = 0.75
SCALE = 1.0   # multiplies the request deadlines (--deadline-scale); tests shrink it
CASES = {
    "urgent_react": [{"human_id": "h_000001", "local_state": {"distress": 0.7, "threat": 82.0, "hp": 54.0}, "nearby": {}}],
    "normal_live": [{"human_id": "h_000001", "local_state": {"hunger": 71.0, "thirst": 42.0}, "nearby": {}}],
    "resident_reasoning": [{"world_model_mode": "resident_reasoning", "resident_id": "h_000001", "reason": "attack_event",
                            "resident_context": {}}],
    "talk_reply": [{"resident_model_mode": "talk_reply", "talk_mode": "direct_talk", "speaker_id": "h_player", "listener_id": "h_000001",
                    "prompt_case": {"utterance": "I am going to kill you", "allowed_physical_intents": ["flee", "back_away", "call_help"]}}],
    "ambient_npc_talk": [{"resident_model_mode": "ambient_npc_talk", "speaker_id": "h_000111", "listener_id": "h_000147",
                          "prompt_case": {"speech_act": "warn", "topic": "danger", "tone": "tense"}}],
    "decree": [{"world_model_mode": "decree", "query": "let rain fall on the north fields", "sub_queries": []}],
    "plan_ops": [{"resident_id": "h_000001", "tick": 100, "reason": "replan", "needs": {"hunger": 80.0, "thirst": 10.0},
                  "options": [{"verb": "eat", "params": {"item": "rations"}}, {"verb": "rest", "params": {}}],
                  "plan_ops": ["eat", "rest"], "limits": {"max_steps": 3, "min_confidence": 0.6}}],
    "director": [{"query": "bless the harvest", "reason": "decree", "world": {"tick": 100},
                  "powers": [{"name": "bless", "risk": "reversible", "example": {"targets": {"ids": ["h_000001"]}}}], "limits": {"max_intents": 2}}],
}


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def passed(self):
        return all(ok for _, ok, _ in self.rows)

    def render(self):
        width = max((len(n) for n, _, _ in self.rows), default=10)
        lines = [f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}".rstrip() for name, ok, detail in self.rows]
        failed = sum(1 for _, ok, _ in self.rows if not ok)
        lines.append(f"\n{len(self.rows) - failed}/{len(self.rows)} checks passed" + ("" if not failed else f", {failed} FAILED"))
        return "\n".join(lines)


class Probe:
    def __init__(self, base_url, key_env="", model_id="", timeout_s=10.0):
        self.base = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        key = os.environ.get(key_env, "") if key_env else ""
        if key:
            self.headers["Authorization"] = f"Bearer {key}"
        if model_id:
            self.headers["X-Model-Id"] = model_id
        self.client = httpx.Client(trust_env=False, timeout=timeout_s)

    def post(self, role, body=None, raw=None, timeout=None):
        started = time.perf_counter()
        try:
            reply = self.client.post(self.base + c.ROLE_ROUTES[role], headers=self.headers, timeout=timeout,
                                     **({"content": raw} if raw is not None else {"json": body}))
            return reply, time.perf_counter() - started, None
        except httpx.HTTPError as exc:
            return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"

    def get(self, path):
        try:
            return self.client.get(self.base + path, headers=self.headers)
        except httpx.HTTPError:
            return None


def decide_body(job="conf-decide", options=("accept", "refuse", "defer", "ask_brain"), kind="choice", deadline_ms=None, **over):
    deadline_ms = deadline_ms if deadline_ms is not None else max(1, int(2000 * SCALE))
    body = {"job_id": job, "role": "decide", "world_epoch": "conformance-epoch", "state_revision": 7, "priority": "active",
            "deadline_ms": deadline_ms, "cancel_token": "", "schema_version": c.SCHEMA_VERSION,
            "payload": {"resident_id": "h_000001", "trigger": "commission_request:o_000001", "question_kind": kind, "tick": 100,
                        "topic": "generic", "state": {"closeness": 0.4, "traits": {"greed": 0.6}},
                        "options": [{"id": o, "description": f"Option {o}", "tags": ["conformance"]} for o in options]}}
    body.update(over)
    return body


def batch_body(role, mode, job=None, deadline_ms=None, **over):
    deadline_ms = deadline_ms if deadline_ms is not None else max(1, int(3000 * SCALE))
    body = {"job_id": job or f"conf-{role}-{mode}", "role": role, "world_epoch": "conformance-epoch", "state_revision": 7,
            "priority": "active", "deadline_ms": deadline_ms, "cancel_token": "", "schema_version": c.SCHEMA_VERSION,
            "payload": {"mode": mode, "cases": CASES[mode]}}
    body.update(over)
    return body


def check_reply(report, label, reply, elapsed, err, body, deadline_ms):
    """Shared checks for one valid request. Returns the parsed ResponseEnvelope or None."""
    if not report.check(f"{label}: answers", reply is not None and reply.status_code == 200,
                        err or (f"HTTP {reply.status_code}: {reply.text[:120]}" if reply is not None and reply.status_code != 200 else "")):
        return None
    try:
        data = reply.json()
    except ValueError:
        report.check(f"{label}: reply is JSON", False, reply.text[:80])
        return None
    report.check(f"{label}: reply is JSON", True)
    request = c.parse_envelope(body)
    try:
        parsed = c.parse_response(data, request)
    except c.ContractError as exc:
        report.check(f"{label}: schema, echo and result valid", False, str(exc)[:200])
        return None
    report.check(f"{label}: schema, echo and result valid", True, f"provider_mode={parsed.provider_mode} model_id={parsed.model_id!r}")
    report.check(f"{label}: within deadline", elapsed <= deadline_ms / 1000.0 + GRACE_S, f"{elapsed * 1000:.0f} ms of {deadline_ms} ms")
    return parsed


def check_decide(probe, report):
    body = decide_body()
    reply, elapsed, err = probe.post("decide", body)
    parsed = check_reply(report, "decide", reply, elapsed, err, body, body["deadline_ms"])
    if parsed is not None:
        probs = parsed.result["probabilities"]
        report.check("decide: option set equals the offered set", set(probs) == {o["id"] for o in body["payload"]["options"]})
        report.check("decide: probabilities sum to 1", abs(sum(probs.values()) - 1.0) <= 1e-3, f"sum={sum(probs.values()):.6f}")
        report.check("decide: probabilities finite and >= 0", all(0.0 <= v <= 1.0 for v in probs.values()))
    body = decide_body(job="conf-decide-one", options=("only",))
    reply, elapsed, err = probe.post("decide", body)
    parsed = check_reply(report, "decide (single option)", reply, elapsed, err, body, body["deadline_ms"])
    if parsed is not None:
        report.check("decide (single option): that option gets p=1", abs(parsed.result["probabilities"]["only"] - 1.0) <= 1e-3)
    body = decide_body(job="conf-decide-yesno", options=("yes", "no"), kind="yes_no")
    reply, elapsed, err = probe.post("decide", body)
    check_reply(report, "decide (yes_no)", reply, elapsed, err, body, body["deadline_ms"])
    many = tuple(f"opt_{i:02d}" for i in range(c.MAX_OPTIONS))
    body = decide_body(job="conf-decide-many", options=many)
    reply, elapsed, err = probe.post("decide", body)
    check_reply(report, f"decide ({c.MAX_OPTIONS} options)", reply, elapsed, err, body, body["deadline_ms"])
    body = decide_body(job="conf-decide-unicode", options=("接受", "拒绝", "café"))
    reply, elapsed, err = probe.post("decide", body)
    check_reply(report, "decide (non-ASCII option ids)", reply, elapsed, err, body, body["deadline_ms"])


def check_batch(probe, report, role):
    for mode in c.ROLE_MODES[role]:
        body = batch_body(role, mode)
        reply, elapsed, err = probe.post(role, body)
        parsed = check_reply(report, f"{role}/{mode}", reply, elapsed, err, body, body["deadline_ms"])
        if parsed is not None:
            report.check(f"{role}/{mode}: one packet per case", len(parsed.result["responses"]) == len(CASES[mode]))
            report.check(f"{role}/{mode}: result mode echoes the request", parsed.result["mode"] == mode)


def check_errors(probe, report, role):
    good = decide_body() if role == "decide" else batch_body(role, c.ROLE_MODES[role][0])

    def expect_4xx(label, reply, err):
        ok = reply is not None and 400 <= reply.status_code < 500
        detail = err or (f"HTTP {reply.status_code}" if reply is not None else "no reply")
        body_ok = False
        if ok:
            try:
                data = reply.json()
                body_ok = data.get("ok") is False and isinstance(data.get("error"), dict) and bool(data["error"].get("code"))
            except ValueError:
                body_ok = False
        report.check(f"{role} errors: {label} -> 4xx", ok, detail)
        report.check(f"{role} errors: {label} -> error body with a code", body_ok)

    reply, _, err = probe.post(role, raw=b"{this is not json")
    expect_4xx("malformed JSON", reply, err)
    reply, _, err = probe.post(role, {**good, "schema_version": 99})
    expect_4xx("unsupported schema_version", reply, err)
    other = "resident" if role != "resident" else "world"
    reply, _, err = probe.post(role, {**good, "role": other})
    expect_4xx("role does not match the route", reply, err)
    broken = json.loads(json.dumps(good))
    if role == "decide":
        broken["payload"]["options"] = []
    else:
        broken["payload"]["cases"] = []
    reply, _, err = probe.post(role, broken)
    expect_4xx("empty options/cases", reply, err)
    missing = {k: v for k, v in good.items() if k != "job_id"}
    reply, _, err = probe.post(role, missing)
    expect_4xx("missing job_id", reply, err)


def check_deadline(probe, report, role):
    good = decide_body(deadline_ms=1) if role == "decide" else batch_body(role, c.ROLE_MODES[role][0], deadline_ms=1)
    reply, elapsed, err = probe.post(role, good, timeout=5.0)
    clean = reply is not None and (reply.status_code == 200 or reply.status_code in (503, 504))
    report.check(f"{role} deadline: a 1 ms deadline ends cleanly (answer or 503/504)", clean, err or f"HTTP {reply.status_code if reply else '-'}")
    report.check(f"{role} deadline: ... and does not hang", elapsed <= 2.0, f"{elapsed * 1000:.0f} ms")


def check_concurrency(probe, report, role, n=8):
    def one(i):
        body = decide_body(job=f"conf-par-{i}") if role == "decide" else batch_body(role, c.ROLE_MODES[role][0], job=f"conf-par-{role}-{i}")
        reply, elapsed, err = probe.post(role, body)
        try:
            ok = reply is not None and reply.status_code == 200 and c.parse_response(reply.json(), c.parse_envelope(body)) is not None
        except Exception:  # noqa: BLE001
            ok = False
        return ok

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(one, range(n)))
    report.check(f"{role} concurrency: {n} parallel requests all valid", all(results), f"{sum(results)}/{n}")


def run(base_url, roles, key_env="", model_id="", quick=False):
    probe = Probe(base_url, key_env, model_id)
    report = Report()
    health = probe.get("/health")
    report.check("GET /health", health is not None and health.status_code == 200,
                 "optional for non-bundled servers" if health is None or health.status_code != 200 else "")
    if health is None and probe.get("/v1/models") is None:
        report.check("endpoint reachable", False, f"cannot connect to {probe.base}")
        return report
    for role in roles:
        if role == "decide":
            check_decide(probe, report)
        else:
            check_batch(probe, report, role)
        check_errors(probe, report, role)
        check_deadline(probe, report, role)
        if not quick:
            check_concurrency(probe, report, role)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", nargs="?", help="base URL of the model server")
    parser.add_argument("--role", default="all", choices=["all", *c.ROLES])
    parser.add_argument("--key-env", default="", help="NAME of the environment variable holding the API key")
    parser.add_argument("--model-id", default="", help="sent as X-Model-Id")
    parser.add_argument("--deadline-scale", type=float, default=1.0, help="multiply the request deadlines (default 1.0 = 2 s / 3 s)")
    parser.add_argument("--quick", action="store_true", help="skip the concurrency burst")
    parser.add_argument("--selftest", action="store_true", help="check the bundled mock server on an ephemeral port")
    args = parser.parse_args(argv)
    global SCALE
    SCALE = args.deadline_scale
    roles = list(c.ROLES) if args.role == "all" else [args.role]
    if args.selftest:
        sys.path.insert(0, str(ROOT / "at_the_beginning"))
        from model_server.app import create_app
        from model_server.config import ServerConfig
        from systems.modelplane.testing import ServerThread
        with ServerThread(create_app(ServerConfig())) as server:
            report = run(server.url, roles, quick=args.quick)
    else:
        if not args.url:
            parser.error("a URL is required (or --selftest)")
        report = run(args.url, roles, args.key_env, args.model_id, args.quick)
    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
