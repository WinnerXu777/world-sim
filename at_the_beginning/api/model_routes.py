"""Model plane routes: ``GET /model_status`` and ``POST /control/models`` (the LLM switch).

Hook (the only change needed in map_test.py, after ``engine`` and ``app`` exist):

    from api.model_routes import build_model_router          # with the other api imports
    app.include_router(build_model_router(lambda: engine))

POST is covered by the session-capability middleware like every other write. The mode is process state: it is not part of a saved
world, so a save made with models on loads and plays with them off. Every role defaults to ``off``.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from systems.modelplane import ModelPlane, SwitchError
from systems.modelplane.adapters.legacy import sync_installation
from systems.modelplane.switch import SLOTS, TIER1_POLICIES


def _reject(reason: str, status: int = 400):
    return JSONResponse({"ok": False, "reason": reason}, status_code=status)


def build_model_router(get_engine, plane: ModelPlane | None = None) -> APIRouter:
    router = APIRouter()
    engine = get_engine()
    plane = plane or engine.__dict__.get("_model_plane") or ModelPlane()
    engine.__dict__["_model_plane"] = plane
    installed: dict = {}
    try:
        from systems.commission.engine import decision_service
        service = decision_service(engine)
        plane.log = plane.log or service.log
        service.status_extras["models"] = plane.brief
    except Exception:  # noqa: BLE001 - status surfacing is optional; the routes work without it
        pass
    plane.on_switch(lambda _snapshot: sync_installation(get_engine(), plane, installed))
    sync_installation(engine, plane, installed)   # env-configured modes take effect at startup
    try:                                          # Tier 3 escalation sweep: a builtin post-step hook, a no-op while the resident role is off
        from simulation.dispatch import DISPATCH
        from systems.modelplane.tier3.escalation import install as install_escalation
        install_escalation(DISPATCH, plane)
    except Exception:  # noqa: BLE001 - optional; the routes work without it
        pass

    @router.get("/model_status")
    async def model_status():
        return {"ok": True, **plane.status(), "world_epoch": get_engine().world_epoch}

    @router.post("/control/models")
    async def control_models(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return _reject("body must be a JSON object")
        if not isinstance(body, dict):
            return _reject("body must be a JSON object")
        allowed = {"tier1", "all_off", *SLOTS}
        unknown = sorted(set(body) - allowed)
        if unknown:
            return _reject(f"unknown fields {unknown}; allowed {sorted(allowed)}")
        try:
            slots = {slot: "off" for slot in SLOTS} if body.get("all_off") is True else {}
            slots.update({slot: body[slot] for slot in SLOTS if slot in body})
            tier1 = body.get("tier1")
            if tier1 is not None and tier1 not in TIER1_POLICIES:
                return _reject(f"tier1 must be one of {list(TIER1_POLICIES)}")
            result = plane.set_modes(tier1, **slots)
        except SwitchError as exc:
            return _reject(str(exc))
        return {"ok": True, "changed": result["changed"], **plane.switch.snapshot()}

    return router
