"""Clef backend: a documented stub. The request/response mapping is HELD until the real Clef API is supplied.

When it arrives, only this file (and ``systems/modelplane/adapters/clef.py`` for a direct game-to-Clef path) changes:
``to_native`` builds the provider request from a ``DecidePayload``, ``from_native`` returns ``{option id: probability}``.
Until then the backend raises ``ClefMappingHeld`` and the server answers 501 ``backend_not_implemented``; the game keeps
using Tier 1 / rules.
"""
from __future__ import annotations

from ..contract import ClefMappingHeld, Envelope
from .base import Backend, BackendError, CallContext

HELD_MESSAGE = ("Clef request/response mapping is held until the real API is supplied "
                "(see model_server/backends/clef.py to_native/from_native)")


def to_native(envelope: Envelope) -> dict:
    raise ClefMappingHeld(HELD_MESSAGE)


def from_native(native_reply, envelope: Envelope) -> dict:
    raise ClefMappingHeld(HELD_MESSAGE)


class ClefBackend(Backend):
    kind = "clef"
    provider_mode = "live"
    model_id = "clef-unconfigured"

    def __init__(self, base_url: str = "", key_env: str = "", model: str = ""):
        self.base_url, self.key_env, self.model_id = base_url, key_env, model or self.model_id

    def ready(self):
        return False, HELD_MESSAGE

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        if envelope.role != "decide":
            raise BackendError("backend_not_implemented", "the clef backend serves the decide role only")
        try:
            to_native(envelope)
        except ClefMappingHeld as exc:
            raise BackendError("backend_not_implemented", str(exc)) from exc
        raise BackendError("backend_not_implemented", HELD_MESSAGE)  # unreachable until the mapping exists
