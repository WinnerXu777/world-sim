"""Backend interface. A backend turns a validated request envelope into a role ``result`` dict; the app validates it."""
from __future__ import annotations

import threading

from ..contract import ContractError, Envelope


class BackendError(ContractError):
    """A backend failure. ``code`` is a contract error code (backend_error, backend_unavailable, backend_not_implemented)."""


class CallContext:
    """Cooperative cancellation and the deadline for one call. Backends should poll ``cancelled`` during long waits."""

    def __init__(self, deadline_s: float, event: threading.Event | None = None):
        self.deadline_s = deadline_s
        self.event = event or threading.Event()

    def cancelled(self) -> bool:
        return self.event.is_set()

    def sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; returns False when cancelled early."""
        return not self.event.wait(max(0.0, seconds))


class Backend:
    kind = "base"
    provider_mode = "mock"
    model_id = "none"

    def ready(self) -> tuple[bool, str]:
        return True, "ok"

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        raise NotImplementedError
