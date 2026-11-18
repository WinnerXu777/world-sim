"""FastAPI model server: POST /v1/{decide,resident,dialogue,world}, GET /health /ready /v1/models /v1/contract, POST /v1/cancel.

Every request is parsed strictly, run on a worker thread under the request's own ``deadline_ms`` (504 when exceeded), and the
backend's answer is validated against the contract before it is sent. Errors always carry ``ok: false`` and an ``error`` body.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import contract as c
from .backends import BackendError, CallContext, Recorder, make_backend
from .config import ServerConfig
from .faults import FaultPlan, corrupt_result, garbage_body
from .schema import json_schema

STATUS = {"malformed_request": 400, "invalid_payload": 400, "unknown_role": 400, "schema_version_unsupported": 400,
          "cancelled": 409, "backend_not_implemented": 501, "backend_error": 502, "backend_unavailable": 503,
          "deadline_exceeded": 504, "internal_error": 500}
RETRYABLE = {"backend_unavailable", "deadline_exceeded", "internal_error"}


def _error(code: str, message: str, job_id: str = "", role: str = "", epoch: str = "", revision: int = 0, started: float | None = None):
    latency = 0.0 if started is None else round((time.perf_counter() - started) * 1000.0, 3)
    body = c.ResponseEnvelope(job_id=job_id, role=role, world_epoch=epoch, state_revision=revision, provider_mode="fallback",
                              latency_ms=latency, model_id="", result={}, ok=False,
                              error=c.ErrorBody(code=code, message=message, retryable=code in RETRYABLE)).to_dict()
    return JSONResponse(body, status_code=STATUS.get(code, 500))


def create_app(config: ServerConfig | None = None, backends: dict | None = None) -> FastAPI:
    config = config or ServerConfig.from_env()
    if backends is None:
        backends = {}
        for role in c.ROLES:
            kind, options = config.backends.get(role, ("mock", {}))
            backend = make_backend(kind, options)
            backends[role] = Recorder(backend, config.record_to) if config.record_to else backend
    faults = FaultPlan(config.faults, config.fault_seed)
    pool = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="model-backend")
    stats = {"requests": Counter(), "ok": Counter(), "errors": Counter()}
    cancel_events: dict[str, list] = {}
    cancelled: deque = deque(maxlen=4096)
    lock = threading.Lock()
    @asynccontextmanager
    async def lifespan(_app):
        yield
        pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Eden model plane (mock/rules/recorded/live backends)", version=f"contract-v{c.SCHEMA_VERSION}",
                  lifespan=lifespan)
    app.state.faults = faults
    app.state.backends = backends
    app.state.stats = stats

    async def serve(role: str, request: Request):
        started = time.perf_counter()
        stats["requests"][role] += 1
        raw = await request.body()
        job_id = epoch = ""
        revision = 0

        def fail(code, message):
            stats["errors"][code] += 1
            return _error(code, message, job_id, role, epoch, revision, started)

        if len(raw) > config.max_body_bytes:
            return fail("malformed_request", f"body larger than {config.max_body_bytes} bytes")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return fail("malformed_request", "body is not valid JSON")
        if isinstance(body, dict):
            job_id = str(body.get("job_id", ""))[:80]
            epoch = str(body.get("world_epoch", ""))[:80]
            revision = body.get("state_revision") if isinstance(body.get("state_revision"), int) else 0
        try:
            envelope = c.parse_envelope(body)
        except c.ContractError as exc:
            return fail(exc.code, exc.message)
        if envelope.role != role:
            return fail("malformed_request", f"role {envelope.role!r} sent to the {role!r} route")
        if envelope.cancel_token and envelope.cancel_token in cancelled:
            return fail("cancelled", "cancel_token already cancelled")

        if (spec := faults.pick(envelope.job_id, role, "hang")) is not None:
            await asyncio.sleep(float(spec.get("delay_ms", 5000)) / 1000.0)
        if faults.pick(envelope.job_id, role, "error500") is not None:
            stats["errors"]["injected_error500"] += 1
            return PlainTextResponse("injected failure", status_code=500)

        event = threading.Event()
        if envelope.cancel_token:
            with lock:
                cancel_events.setdefault(envelope.cancel_token, []).append(event)
        backend = backends[role]
        slow = faults.pick(envelope.job_id, role, "slow")
        ctx = CallContext(envelope.deadline_ms / 1000.0, event)

        def call():
            if slow is not None:
                ctx.sleep(float(slow.get("delay_ms", 400)) / 1000.0)
            if ctx.cancelled():
                raise BackendError("cancelled", "cancelled before the backend ran")
            return backend.handle(envelope, ctx)

        try:
            future = asyncio.get_running_loop().run_in_executor(pool, call)
            remaining = max(0.001, envelope.deadline_ms / 1000.0 - (time.perf_counter() - started))
            try:
                result = await asyncio.wait_for(future, timeout=remaining)
            except asyncio.TimeoutError:
                event.set()
                return fail("deadline_exceeded", f"no answer within {envelope.deadline_ms} ms")
            except BackendError as exc:
                return fail(exc.code if exc.code in STATUS else "backend_error", exc.message)
            except Exception as exc:  # noqa: BLE001 - a backend bug must be an error reply, not a dropped connection
                return fail("internal_error", f"{type(exc).__name__}: {exc}")
        finally:
            if envelope.cancel_token:
                with lock:
                    events = cancel_events.get(envelope.cancel_token, [])
                    if event in events:
                        events.remove(event)
                    if not events:
                        cancel_events.pop(envelope.cancel_token, None)

        try:
            clean = c.validate_result(role, envelope.payload, result)
        except c.ContractError as exc:
            return fail("backend_error", exc.message)
        if (spec := faults.pick(envelope.job_id, role, "bad_result")) is not None:
            clean = corrupt_result(role, clean, spec, envelope.job_id)
        reply = c.ResponseEnvelope(job_id=envelope.job_id, role=role, world_epoch=envelope.world_epoch,
                                   state_revision=envelope.state_revision, provider_mode=backend.provider_mode,
                                   latency_ms=round((time.perf_counter() - started) * 1000.0, 3), model_id=backend.model_id,
                                   result=clean).to_dict()
        if faults.pick(envelope.job_id, role, "stale") is not None:
            reply["world_epoch"] = envelope.world_epoch + "-old"
            reply["state_revision"] = envelope.state_revision + 1
        if (spec := faults.pick(envelope.job_id, role, "garbage")) is not None:
            stats["errors"]["injected_garbage"] += 1
            return PlainTextResponse(garbage_body(spec, envelope.job_id), status_code=200)
        stats["ok"][role] += 1
        return JSONResponse(reply)

    def route(role):
        async def handler(request: Request):
            return await serve(role, request)
        handler.__name__ = f"post_{role}"
        return handler

    for role, path in c.ROLE_ROUTES.items():
        app.add_api_route(path, route(role), methods=["POST"], name=f"model_{role}")

    @app.post("/v1/cancel")
    async def cancel(request: Request):
        try:
            token = (await request.json()).get("cancel_token", "")
        except Exception:  # noqa: BLE001
            return _error("malformed_request", "body must be {\"cancel_token\": str}")
        if not isinstance(token, str) or not token:
            return _error("malformed_request", "cancel_token must be a non-empty string")
        with lock:
            cancelled.append(token)
            events = list(cancel_events.get(token, []))
        for event in events:
            event.set()
        return {"ok": True, "cancelled_in_flight": len(events)}

    @app.get("/health")
    async def health():
        return {"ok": True, "contract": c.SCHEMA_VERSION}

    @app.get("/ready")
    async def ready():
        report = {}
        for role, backend in backends.items():
            ok, why = backend.ready()
            report[role] = {"ready": ok, "backend": backend.kind, "detail": why}
        all_ready = all(r["ready"] for r in report.values())
        return JSONResponse({"ok": all_ready, "roles": report}, status_code=200 if all_ready else 503)

    @app.get("/v1/models")
    async def models():
        return {"models": {role: {"backend": b.kind, "model_id": b.model_id, "provider_mode": b.provider_mode,
                                  "ready": b.ready()[0]} for role, b in backends.items()}}

    @app.get("/v1/contract")
    async def contract_doc():
        return json_schema()

    @app.get("/v1/stats")
    async def stats_view():
        return {"requests": dict(stats["requests"]), "ok": dict(stats["ok"]), "errors": dict(stats["errors"]),
                "fault_hits": dict(faults.hits), "faults": faults.to_list()}

    if config.fault_admin:
        @app.post("/v1/mock/faults")
        async def set_faults(request: Request):
            try:
                body = await request.json()
                faults.set(body.get("faults", []))
                if "seed" in body:
                    faults.seed = int(body["seed"])
            except Exception as exc:  # noqa: BLE001
                return _error("malformed_request", f"bad fault spec: {exc}")
            return {"ok": True, "faults": faults.to_list(), "seed": faults.seed}

    return app
