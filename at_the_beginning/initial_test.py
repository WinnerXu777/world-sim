"""
initial_test.py
===============
Dedicated backend launcher for the small render/control testing sandbox.

This keeps the test-run profile in one place so we can iterate on the
playtest backend without repeatedly editing `map_test.py`.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress

import uvicorn

import genesis_config as cfg
# Keep this legacy launcher explicitly isolated, before the backend is imported.
os.environ.setdefault("EDEN_PROFILE", "render_fixture")
import map_test as backend


TEST_MAP_NAME = "render_test_village"
TEST_HOST = backend.LAUNCH_CONFIG.host
TEST_PORT = backend.LAUNCH_CONFIG.port
TEST_ACCESS_LOG = False
TEST_RUNTIME_PROFILE = "full"
TEST_NPC_MOVE_STEP = 0.16
TEST_GATHER_MOVE_STEP = 0.0

_ORIGINAL_LOAD_RENDER_TEST_VILLAGE = backend.load_render_test_village
_ORIGINAL_INSTINCT_MOVE = backend.iat.instinct_move


def _stationary_idle_move(ctx, h_tensor, device, m_tensor=None, **kwargs) -> None:
    """Sandbox override: residents idle in place, but threatened ones may still move/flee."""
    h_mask = ctx.get("h_mask")
    if h_mask is None:
        return
    pre_x = h_tensor[:, cfg.X].clone()
    pre_y = h_tensor[:, cfg.Y].clone()
    _ORIGINAL_INSTINCT_MOVE(ctx, h_tensor=h_tensor, device=device, m_tensor=m_tensor, **kwargs)
    threat_mask = h_tensor[:, cfg.THREAT] >= 1.0
    restore_mask = h_mask & ~threat_mask
    incarnation_slots = ctx.get("incarnation_slots", [])
    if incarnation_slots:
        restore_mask = restore_mask.clone()
        for slot in incarnation_slots:
            if 0 <= int(slot) < restore_mask.shape[0]:
                restore_mask[int(slot)] = False
    if bool(restore_mask.any()):
        h_tensor[restore_mask, cfg.X] = pre_x[restore_mask]
        h_tensor[restore_mask, cfg.Y] = pre_y[restore_mask]


def _apply_test_runtime_tuning() -> None:
    cfg.MOVE_STEP = float(TEST_NPC_MOVE_STEP)
    backend.iat.MOVE_STEP = float(TEST_NPC_MOVE_STEP)
    backend.BASELINE_GATHER_MOVE_STEP = float(TEST_GATHER_MOVE_STEP)
    backend.engine._runtime_profile = TEST_RUNTIME_PROFILE
    backend.engine.unregister(backend.iat.instinct_move)
    backend.engine.unregister(_stationary_idle_move)
    backend.engine.register(_stationary_idle_move, priority=38)


async def _load_render_test_village_for_test(*args, **kwargs):
    result = await _ORIGINAL_LOAD_RENDER_TEST_VILLAGE(*args, **kwargs)
    _apply_test_runtime_tuning()
    result["runtime_profile"] = backend.engine._runtime_profile
    result["npc_move_step"] = float(cfg.MOVE_STEP)
    result["gather_move_step"] = float(backend.BASELINE_GATHER_MOVE_STEP)
    return result


@asynccontextmanager
async def _initial_test_lifespan(_app):
    await backend.create_genesis(backend.engine, map_name=TEST_MAP_NAME)
    _apply_test_runtime_tuning()
    backend.engine.mock_tiny_model_enabled = True
    backend.engine.mock_reasoning_enabled = True
    task = asyncio.create_task(backend.engine.run_loop(), name="eden-fixture-simulation")
    _app.state.simulation_task = task
    try:
        yield
    finally:
        backend.engine.running = False
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def build_test_app():
    # Reuse the existing backend routes and engine, but swap in the
    # dedicated test startup profile.
    backend.load_render_test_village = _load_render_test_village_for_test
    backend.app.router.lifespan_context = _initial_test_lifespan
    return backend.app


def main() -> None:
    app = build_test_app()
    uvicorn.run(app, host=TEST_HOST, port=TEST_PORT, access_log=TEST_ACCESS_LOG)


if __name__ == "__main__":
    main()
