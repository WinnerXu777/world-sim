# 1008 model API: the wire contract and how to plug a model in

Status 2026-10-08. Written by the model-plane worker for plan section WS-A (`../designs/implementation.md`). **Everything here is built and tested against a deterministic mock server; no real model has been connected.** The user supplies real endpoints later; nothing in the game imports a model library.

Files: `model_server/contract.py` (the contract, stdlib only), `model_server/schema_v1.json` and `openapi_v1.json` (generated from the dataclasses and drift-tested), `model_server/examples/*.json` (generated worked examples, drift-tested), `model_server/app.py` (mock/rules/recorded/live server), `at_the_beginning/systems/modelplane/` (the game side), `tools/model_conformance.py` (the pass/fail check for any endpoint).

## 1. What a model server must do

Accept `POST /v1/{decide,resident,dialogue,world}` with a JSON **envelope**, return a JSON **response envelope** whose `result` matches the role. That is all. Optional but useful: `GET /health`, `GET /ready`, `GET /v1/models`, `POST /v1/cancel`.

Request envelope (`Envelope`):

| Field | Type | Meaning |
| --- | --- | --- |
| `job_id` | string | unique id; echo it back |
| `role` | `decide` \| `resident` \| `dialogue` \| `world` | must match the route |
| `world_epoch` | string | game world epoch; echo back unchanged. A reply that disagrees is dropped as stale |
| `state_revision` | int >= 0 | revision of the state the question was built from; echo back unchanged |
| `priority` | `critical` \| `active` \| `background` | default `active` |
| `deadline_ms` | int 1..60000 | the caller stops waiting after this; default 1000 |
| `cancel_token` | string | optional group id; `POST /v1/cancel {"cancel_token": ...}` means "stop work, nobody is waiting" |
| `schema_version` | int | currently `1`; refuse others with 400 `schema_version_unsupported` |
| `payload` | object | role specific, below |

Response envelope (`ResponseEnvelope`): `job_id`, `role`, `world_epoch`, `state_revision` (all echoed), `schema_version`, `ok` (true), `provider_mode` (`rules` \| `mock` \| `recorded` \| `live` \| `fallback`; a real model returns `live`), `latency_ms` (number >= 0), `model_id` (string), `result` (role specific). On failure: HTTP 4xx/5xx, `ok: false`, `error: {code, message, retryable}`, empty `result`.

HTTP status by error code: `malformed_request`, `invalid_payload`, `unknown_role`, `schema_version_unsupported` = 400; `cancelled` = 409; `backend_not_implemented` = 501; `backend_error` (the model produced something invalid) = 502; `backend_unavailable` = 503; `deadline_exceeded` = 504; `internal_error` = 500. The game treats **every** non-200, timeout, unparseable body, echo mismatch or contract violation the same way: the call becomes a *fallback* and the deterministic stand-in is used. Failures are never fatal.

**Deadlines.** The game gives up after `deadline_ms` (plus 50 ms grace) and discards a later answer. A server should stop work and answer `504` rather than answer late. `critical` jobs have about 400 ms, `active` 1 to 1.5 s, `background` 2.5 to 8 s (set by the game, not guaranteed).

## 2. Roles, payloads, results

`result` is validated by the game and by the conformance tool with `model_server/contract.py::validate_result` before it touches the game. The JSON Schema is `schema_v1.json` (`$defs`: `DecidePayload`, `DecideResult`, `ResidentPayload`, `ResidentResult`, `DialoguePayload`, `DialogueResult`, `WorldPayload`, `WorldResult`).

### `decide` (Tier 2, Clef-style typed choice, no text)

Payload: `resident_id`, `trigger` (event type plus causal event id), `question_kind` (`choice` or `yes_no`), `options` (1 to 64 items `{id, description, tags}`; **already legal**, the model must never add or drop one), `tick`, `topic`, `state` (object snapshot). Result: `{"probabilities": {option id: p}}`: exactly the offered ids, finite, `>= 0`, sum `1 +- 1e-3`. One legal option must get `p = 1`.

Worked example (generated; `model_server/examples/decide_commission.json`):

```json
// request
{
  "job_id": "o_000001:decide",
  "role": "decide",
  "world_epoch": "6f1c0d52-3a5e-4c1b-9d0a-0b5e7a1f2c11",
  "state_revision": 3,
  "priority": "active",
  "deadline_ms": 1000,
  "cancel_token": "o_000001",
  "schema_version": 1,
  "payload": {
    "resident_id": "h_000004",
    "trigger": "commission_request:o_000001",
    "question_kind": "choice",
    "tick": 5120,
    "topic": "commission",
    "state": {
      "closeness": 0.4,
      "rival": false,
      "traits": {
        "greed": 0.6,
        "discipline": 0.7
      },
      "pressures": {
        "security": 0.1
      },
      "price": 18,
      "open_orders": 1,
      "capacity": 3,
      "missing": [],
      "forge_available": true
    },
    "options": [
      {
        "id": "accept_commission",
        "description": "Accept the commission and reserve the materials and payment.",
        "tags": [
          "commission"
        ]
      },
      {
        "id": "refuse_busy",
        "description": "Refuse: too many open orders already.",
        "tags": [
          "commission"
        ]
      }
    ]
  }
}
// response
{
  "job_id": "o_000001:decide",
  "role": "decide",
  "world_epoch": "6f1c0d52-3a5e-4c1b-9d0a-0b5e7a1f2c11",
  "state_revision": 3,
  "schema_version": 1,
  "ok": true,
  "provider_mode": "mock",
  "latency_ms": 1.0,
  "model_id": "mock-v1",
  "result": {
    "probabilities": {
      "accept_commission": 0.687374,
      "refuse_busy": 0.312626
    }
  }
}
```

### `resident` (Tier 3, goals, plans, tiny reactions)

Payload `{mode, cases[1..32]}`, `mode` one of `urgent_react`, `normal_live`, `resident_reasoning`, `plan_ops`. Result `{mode, responses[]}` with **one `{packet, source}` per case, in order**. The packet keeps the legacy structured contract from `../archive/implement_llm.md`:
- `urgent_react` / `normal_live`: `packet.intent` non-empty string; optional `action {type, ...}`, `confidence` in [0,1], `followup`.
- `resident_reasoning`: `packet.resident_id`, `goal_updates` (list), `plans` (list), `goal_review`, `auto_plan`. Plans must come from the plan catalog sent in the case; the game's planning validator still rejects anything else.

- `plan_ops` (round 2, `../designs/tier3.md`): the case is `{resident_id, tick, reason, needs, scene, goals, plan, options[{verb, params, distance?}], plan_ops[], limits}` (typed, never a raw state dump); the packet is `{resident_id, confidence in [0,1], steps[<=8 of {op, args}], summary?}`. `op` must be one of `case.plan_ops` and `args` should repeat an offered option's params; the game gates the plan (confidence, known ops, schema, the runner's dry run of step 0) and falls back to Tier 1 with a logged reason.

Examples: `examples/resident_urgent_react.json`, `examples/resident_resident_reasoning.json`, `examples/resident_plan_ops.json`.

### `dialogue` (Tier 3, wording from an already decided outcome)

Payload `{mode, cases}`, `mode` is `talk_reply` or `ambient_npc_talk`. Packet: `speech_text` (1..500 chars), `speech_act`, `tone`, `physical_intent` (**empty or one of** `case.prompt_case.allowed_physical_intents`), `danger_upgrade`, `relationship_delta`, `pressure_deltas`, `memory_salience`. Dialogue cannot accept obligations; it only words an outcome Python already decided.

```json
// request
{
  "job_id": "dialogue:t1",
  "role": "dialogue",
  "world_epoch": "6f1c0d52-3a5e-4c1b-9d0a-0b5e7a1f2c11",
  "state_revision": 5120,
  "priority": "active",
  "deadline_ms": 1500,
  "cancel_token": "",
  "schema_version": 1,
  "payload": {
    "mode": "talk_reply",
    "cases": [
      {
        "resident_model_mode": "talk_reply",
        "talk_mode": "direct_talk",
        "speaker_id": "h_player",
        "listener_id": "h_000123",
        "prompt_case": {
          "utterance": "I am going to kill you",
          "personality_summary": "guarded (caution=0.84, aggression=0.31)",
          "relationship_summary": "neighbor",
          "allowed_physical_intents": [
            "flee",
            "back_away",
            "scan_and_prepare",
            "counterattack",
            "call_help"
          ]
        }
      }
    ]
  }
}
// response
{
  "job_id": "dialogue:t1",
  "role": "dialogue",
  "world_epoch": "6f1c0d52-3a5e-4c1b-9d0a-0b5e7a1f2c11",
  "state_revision": 5120,
  "schema_version": 1,
  "ok": true,
  "provider_mode": "mock",
  "latency_ms": 1.0,
  "model_id": "mock-v1",
  "result": {
    "mode": "talk_reply",
    "responses": [
      {
        "packet": {
          "resident_model_mode": "talk_reply",
          "mode": "direct_talk",
          "speaker_id": "h_player",
          "listener_id": "h_000123",
          "speech_text": "Stay away from me!",
          "speech_act": "threat_response",
          "tone": "neutral",
          "physical_intent": "counterattack",
          "danger_upgrade": false,
          "reasoning_followup": false,
          "witness_policy": "nearby_hear",
          "relationship_delta": "neutral",
          "pressure_deltas": {},
          "memory_salience": 0.3
        },
        "source": "mock_model_server"
      }
    ]
  }
}
```

### `world` (Tier 3, god decrees and world operations)

Payload `{mode, cases}`, `mode` is `decree` or `director`. `decree` packet: `thought`, `map_actions`, `human_actions`, `new_entities`, `new_instincts` (lists). `director` (round 2): the case is `{query, reason, tick, residents, powers[{name, risk, args, example}], max_intents}`; the packet is `{thought, intents[<=6 of {power, args, reason?}]}`. The game plans every intent with the harness powers, refuses unknown/invalid ones and destructive ones unless allowed, and applies nothing in shadow mode. Nothing the model returns is executed directly: the existing decree validation and execution pipeline checks every action. Examples: `examples/world_decree.json`, `examples/world_director.json`.

## 3. Serving your own model: the hook-up kit

1. **Read** this file and `schema_v1.json`. Implement the four routes (or only the roles you serve; unserved roles stay `off`).
2. **Check** your endpoint: `.venv/Scripts/python.exe tools/model_conformance.py https://host --role decide --key-env MY_KEY_VAR --model-id my-model`. It checks schema and echo, probability sums and option-set equality, one packet per case, deadline behaviour (a 1 ms deadline must end cleanly), error behaviour (malformed JSON, wrong `schema_version`, wrong role, empty options, missing `job_id` must all answer 4xx with an error body), and an 8-way concurrency burst. It prints PASS/FAIL per check and exits non-zero on any failure. Run it against the bundled mock first: `tools/model_conformance.py --selftest` (113 of 113 pass).
3. **Configure** (names only, keys stay in the environment): `EDEN_MODEL_URL=https://host` (or per role `EDEN_TIER2_URL`, `EDEN_TIER3_RESIDENT_URL`, ...), `EDEN_TIER2_KEY_ENV=MY_KEY_VAR` (the name of the variable that holds the key; sent as `Authorization: Bearer`), `EDEN_TIER2_MODEL=my-model` (sent as `X-Model-Id`).
4. **Shadow first**: `EDEN_TIER2=shadow` (or `POST /control/models {"tier2": "shadow"}`). The model is called on real triggers, its answer is logged beside the rules answer (`type: "shadow"` in the decision log, agreement shown in `/model_status`), and the rules answer is applied.
5. **Then `on`** per role, one at a time. Any failure falls back for that call only. `POST /control/models {"all_off": true}` is the kill switch.

If you would rather not write a server, the bundled server can call an OpenAI-compatible endpoint (vLLM, SGLang, Ollama, hosted): `EDEN_MODEL_BACKEND_DECIDE=openai_compat EDEN_MODEL_DECIDE_URL=http://host:8000/v1 EDEN_MODEL_DECIDE_MODEL=name EDEN_MODEL_DECIDE_KEY_ENV=VAR python -m model_server`. It asks for JSON and the contract validator rejects anything malformed (tested against a stand-in upstream only; never run against a real model).

**Clef.** The request/response mapping to the real Clef API is deliberately held. `model_server/backends/clef.py` and `at_the_beginning/systems/modelplane/adapters/clef.py` are documented stubs that raise `ClefMappingHeld`; the server answers 501 `backend_not_implemented` and `/ready` says why. When the API is supplied, only those two files change (`to_native` builds the provider request from a `DecidePayload`, `from_native` returns `{option id: probability}`).

## 4. Server backends

`python -m model_server` (loopback `127.0.0.1:8100`; `EDEN_MODEL_HOST`/`EDEN_MODEL_PORT`). Backend per role: `EDEN_MODEL_BACKEND` (default for all) or `EDEN_MODEL_BACKEND_<ROLE>` = `mock` | `rules` | `recorded` | `openai_compat` | `clef`.

| Backend | Behaviour |
| --- | --- |
| `mock` | deterministic (sha256-seeded), identical across processes; produces valid packets for every role and mode. `EDEN_MODEL_MOCK_SEED=<text>` prefixes the hash, so a different seed gives different (still valid, reproducible) answers; unset = the original answers |
| `rules` | `decide` uses the game's own `RulesDecisionProvider` scorers (needs the repo on the server path); the batch roles use the mock heuristics |
| `recorded` | replays a JSONL (`EDEN_MODEL_<ROLE>_PATH`): decision-log lines or `Recorder` output (`EDEN_MODEL_RECORD_TO` records any backend's successful answers); a missing recording is an error, so the game falls back |
| `openai_compat` | thin client of `/chat/completions`; config only |
| `clef` | stub, see above |

Mock fault injection (testing only): `EDEN_MODEL_FAULTS='[{"kind":"hang","rate":0.05}]'`, kinds `hang` (handler sleeps, the caller's timeout fires), `slow` (backend slower than the deadline, server answers 504), `garbage` (200 with a non-reply body), `bad_result` (valid envelope, contract-breaking result), `stale` (echoes a different epoch and revision), `error500`. Selection is a pure function of `(seed, job_id, kind)`, so runs are reproducible. `EDEN_MODEL_FAULT_ADMIN=1` enables `POST /v1/mock/faults` to change them at runtime.

## 5. The game side

`ModelPlane` (one per engine) owns the switch, an async `ModelClient` and the caches.

- **LLM switch** (`systems/modelplane/switch.py`). Tier 1 policy `EDEN_TIER1=rules|matrix`; per slot `EDEN_TIER2`, `EDEN_TIER3_RESIDENT`, `EDEN_TIER3_DIALOGUE`, `EDEN_TIER3_WORLD` = `off|shadow|on`. Default is everything `off` and `rules`. **`off` makes zero network calls, starts no thread and opens no socket** (tested with a patched socket layer and with the real engine). Any change bumps the **model epoch**; jobs sent under the old setting are dropped when they return (`stale_model_epoch`) and caches are cleared. The mode lives in the process and is **not** saved in a world.
- **Routes** (`api/model_routes.py`, hook pending the orchestrator's OK): `GET /model_status` (switch, endpoints without keys, per role and lane metrics, breakers, queue, caches) and `POST /control/models` with any of `{"tier1", "tier2", "tier3_resident", "tier3_dialogue", "tier3_world", "all_off": true}`; unknown fields or values are a 400 that changes nothing. `DecisionService.status()["models"]` carries a brief copy in `/status`.
- **Never blocks the tick.** `submit` and `pump` do bounded in-memory work; HTTP runs on worker threads (2 by default), started on the first accepted job. Admission control: per-role in-flight cap and requests per game minute, per-resident cooldown, dedupe by causal event id (TTL 120 game seconds), escalation depth cap 1 and no escalation to the same or a lower tier, queue limit 64. Circuit breaker per endpoint: 5 consecutive failures open it for 5 s, then one half-open probe.
- **Fallback taxonomy** (the `reasons` in `/model_status`): `disabled`, `no_endpoint`, `breaker_open`, `timeout`, `expired_in_queue`, `transport_error`, `http_<status>`, `bad_json`, `invalid_reply:<code>`, `stale_reply`, `late_reply`, `stale_model_epoch`, and the admission skips `cooldown`, `duplicate`, `budget_in_flight`, `budget_rate`, `queue_full`, `escalation_depth`, `escalation_loop`.
- **Tier 2 provider.** `ClefDecisionProvider(plane)` plugs into the existing `DecisionService`. `off`: rules answer, no network. `shadow`: rules answer applied, model answer logged. `on`: the model's validated answer once cached; on a miss the job is queued and `ModelPending` makes the service use rules *this time* (provider mode `fallback`), and the next ask for the same question gets the model answer. `blocking=True` waits up to the deadline and is for scripts only. `apply_if_fresh` still drops a result whose `world_epoch` or `state_revision` moved on.
- **Legacy hooks** (`adapters/legacy.py`). `LegacyModelHandler` is installed as `tiny_model_handler` / `resident_model_handler` / `world_model_handler` only while some role is on, and the originals are restored when everything is off. Mode to role: `urgent_react`, `normal_live`, `resident_reasoning` -> `resident`; `talk_reply`, `ambient_npc_talk` -> `dialogue`; `decree` -> `world`. The packets keep their existing structured contracts and go through the existing normalisers and executors; there is no second NPC stack. Because those hooks are synchronous, the adapter is pull-based: the first call for a question returns `None` (the runtime uses its built-in packet), a later call for the same question (keyed by resident, utterance or reason, not by volatile numbers) receives the validated model packet, once, within a per-mode TTL (urgent 2 s, talk 10 s, reasoning 60 s).

## 6. Observability

`/model_status` per role and lane (`critical`/`active`/`background`): `requests`, `ok`, `timeouts`, `fallbacks`, `stale_drops`, `validation_rejects`, `escalations`, `skipped`, `shadow_ok`, `agreed`/`disagreed` (and `agreement`), `breaker_open`, `transport_errors`, `http_errors`, latency p50/p95/p99, queue age p50/p99, `fallback_rate`; plus fallback reasons per role. The decision log (`DecisionLog`, JSONL under the data root, outside saves) gets `model_switch`, `shadow` and `shadow_failed` records. Keys are never logged or shown; `/model_status` reports only whether the named variable is set.

## 7. Gate A evidence

`python -m model_server.gate_a --compare --ticks 36000 --speed 2` runs the real headless engine for 30 game minutes with the model server in a separate process, injected timeouts, garbage, slow, bad-result, stale and 500 replies, the server killed at 60 percent of the run, models off versus on, and prints PASS/FAIL.

Full run, 2026-10-08 (36000 ticks each, paced at 2x real time, not instrumented per system, a few short targeted test runs of another workstream overlapped the first 25 minutes; raw files `.runtime/gate-a-off.json` and `gate-a-on.json`, gitignored):

| | p50 | p95 | p99 | max | exceptions to the tick | network calls |
| --- | --- | --- | --- | --- | --- | --- |
| models off | 15.22 ms | 31.52 ms | 37.87 ms | 73.25 ms | 0 | 0 |
| models on (all six faults, server killed at 60 percent) | 15.05 ms | 30.32 ms | 35.83 ms | 102.30 ms | 0 | 4864 |

All safety checks pass (every fault kind fired, every fault ended as a fallback or a refused stale answer, breakers opened on the killed endpoint, models off made no calls); the on-versus-off p99 difference is -2.0 ms. **The Stage 1 absolute baseline of 28 ms p99 is not met by either run** (models off is already 37.9 ms), so the cause is not the model plane; it is unexplained here (candidates: paced sleeps versus the unpaced Harness profile, synthetic hook traffic, machine load). An isolated, unpaced models-off rerun has not been done.

## 8. Not done / limits

- No real model has been contacted; `openai_compat` is tested against a stand-in upstream only.
- Clef mapping held (section 3). Tier 1 matrix policy: see `at_the_beginning/systems/decision/matrix.py` (R1-M2).
- **Legacy seam limitation (accepted, G-004).** The legacy tiny/world hooks are synchronous, so a model packet reaches the game **one call late** (the first call always uses the built-in packet). In shadow mode only the model's packet is logged (the handler never sees the stand-in). True shadow comparison (model next to stand-in, agreement metric) happens on the `DecisionService` path (Tier 1/2). Tier 3 moves to an async-native path on the harness Actions in round 2; the legacy adapter is not extended further.
- Escalation from Tier 1 or 2 into Tier 3 is enforced by admission control; the callers that would escalate (confidence gate wiring, `USE_BRAIN` options) land with phase P4.

## 9. Tier 1: the matrix policy (`systems/decision/matrix.py`)

Local, no network, not a wire role. `S = X @ W + (X @ U) * (P @ V) + b`, hysteresis bonus on the running action, masked softmax with temperature 0.35, one batched `torch` computation for the population (float64). `X` is N x 26 (`FEATURES`, schema version 1: needs, pressures, scene and plan flags, commission context, a constant `one`), `P` is N x 16 personality traits (same order as `systems/personality/catalog.py`), `M` is the N x 30 legality mask supplied by Python (illegal options have probability exactly 0 and cannot be chosen). `K = 30`: 24 macro-actions (`eat`, `drink`, `rest`, `sleep`, `work_at_station`, `gather`, `go_home`, `socialise`, `trade`, `help`, `avoid`, `flee`, `defend`, `attack`, `explore`, `build`, `repair`, `ask_for_help`, `hide`, `idle`, `continue_plan_step`, `USE_BRAIN`, `REPLAN`, `PLOT`) plus the six commission outcomes.

- **Rules equivalence.** The commission scorer is written into `W/U/V/b` exactly; on 10,000 random commission states with random legal subsets the matrix agrees with `RulesDecisionProvider` on the argmax 10,000 of 10,000 times and on the whole distribution to 1e-12 (`tests/test_decision_matrix.py`), and the real `submit_request` flow gives the same outcomes. **The 24 macro-action weights are new hand-set placeholders** (nothing existed to distil them from); tests check qualitative behaviour only (hungry eats, tired at night sleeps, threatened flees, an aggressive resident attacks where a timid one does not).
- **Provider.** `MatrixDecisionProvider` plugs into `DecisionService` (mode `matrix`); topics without a featurizer go to rules, options outside the menu fall back to rules.
- **Gate to Tier 2.** `MatrixPolicy.gate(result, significant, GateConfig(min_top_p, min_margin))` marks rows that are uncertain AND significant; thresholds are placeholders to be tuned from shadow data. Wiring it to `submit_decision` lands with the affordance engine and phase P4.
- **Weights file.** `weights/weights_v1.npz` holds `W,U,V,b`, version, feature and menu names, temperature, hysteresis and a sha256; loading refuses a hash mismatch or a different feature schema or menu. `weights_v1.npz` is the initial policy (a test pins this). No training code.
- **Benchmark** (`matrix.benchmark(100)`, 2000 repeats, inputs prebuilt, float64, 10 torch threads, dev machine shared with other sessions): mean 0.21 ms, p50 0.20 ms, p99 0.46 ms, max 0.69 ms per batch of 100 residents. The cost of building `X` from the tensors is not included.
- **Shadow comparison.** `systems/decision/report.py::compare` runs rules, matrix and a mock-Clef on the same requests and reports pairwise argmax agreement and errors.

## 10. Tier 2 for the agent driver: the macro-menu request (`systems/actions/tier2.py`, `EDEN_AGENT_TIER2=1`, default off, needs `EDEN_AGENT_TIER1=matrix`)

* **When.** `MatrixTier1` keeps, for each resident it scored, the legal macros and its distribution over them. A row is sent on when the matrix is unsure (`GateConfig`: top p under 0.45 or margin under 0.10, placeholders) **and** the situation matters (hunger or thirst >= 50, threat >= 30, HP < 50). Everything else stays Tier 1; a prior of 100 (the default) makes the matrix so sure that nothing is ever asked.
* **The question.** Topic `macro`, `question_kind` `choice`, options = the **legal** macros only (id, a one-line description, tag `destructive` for `attack` / `PLOT`), state = `{needs, running macro, routine, tier1: {macro: p}}`, priority `active`, deadline 1000 ms. `state_revision` and the trigger (`macro_review:<n>`) are a hash of the legal set, the running macro and the needs in 10-point buckets, so asking again in an unchanged situation hits the answer the model returned the first time (the plane's decision cache is keyed by resident, trigger, revision, epoch) and a changed situation is a new question.
* **Modes** are the plane's switch (`tier2`): `off` rules answer and no network; `shadow` rules answer applied, the model's answer logged beside it; `on` the model's answer once cached (Tier 1 stands while it is pending). The rules answer for topic `macro` is Tier 1's own distribution (a registered scorer), so a missing plane, a failing model, an answer that does not cover exactly the offered ids, and shadow all give exactly the Tier 1 macro; only a validated model answer changes it. `Tier2.counts` / `.log` and the service counters report asked / changed / modes.
* Not done: the real Clef mapping (held), significance from the escalation hooks (only the four numbers above), tuning the gate from shadow data.

