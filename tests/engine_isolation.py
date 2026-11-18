"""Test helper: undo what ``model_server.gate_a.configure_plane`` installs on the shared ``backend.engine`` (legacy model handlers, the decision service's provider,
the engine's plane), so a test that configures a real plane cannot leak it into later tests (``test_startup_preservation`` / ``test_smith_loop`` read those)."""
from __future__ import annotations

HANDLERS = ("tiny_model_handler", "resident_model_handler", "world_model_handler")


def restore_after(test, engine) -> None:
    """Call BEFORE ``configure_plane``: snapshots the engine's plane-facing state and registers a cleanup on ``test`` that puts it back."""
    from systems.commission.engine import decision_service
    handlers = {name: getattr(engine, name, None) for name in HANDLERS}
    service = decision_service(engine)
    provider = service.provider
    plane = engine.__dict__.get("_model_plane", None)
    had_plane = "_model_plane" in engine.__dict__

    def restore():
        for name, handler in handlers.items():
            setattr(engine, name, handler)
        service.provider = provider
        if had_plane:
            engine.__dict__["_model_plane"] = plane
        else:
            engine.__dict__.pop("_model_plane", None)

    test.addCleanup(restore)
