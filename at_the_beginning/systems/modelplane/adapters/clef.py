"""Clef adapter: a documented stub. The request/response mapping is HELD until the real Clef API is supplied.

This is the ONLY game-side file that changes when the Clef details are decided. Two paths exist, pick one when the API is known:

1. Through the model server (recommended): the server's ``clef`` backend (``model_server/backends/clef.py``) does the mapping and the
   game keeps speaking contract v1 to ``/v1/decide``. Then this file stays a stub.
2. Direct from the game: implement ``to_native`` / ``from_native`` below and register ``ClefAdapter`` as the transport for the
   ``decide`` role.

``to_native(request)`` must return ``(url, headers, body)`` for the provider; ``from_native(reply_json, request)`` must return
``{option id: probability}`` over exactly the offered options (the plane validates it like any other answer).
Until then both raise ``ClefMappingHeld`` and the system runs Tier 1 (matrix or rules) only.
"""
from __future__ import annotations

from ..wire import ClefMappingHeld

HELD = "Clef request/response mapping is held until the real API is supplied (systems/modelplane/adapters/clef.py)"


def to_native(request) -> tuple:
    raise ClefMappingHeld(HELD)


def from_native(reply_json, request) -> dict:
    raise ClefMappingHeld(HELD)


class ClefAdapter:
    def __init__(self, base_url: str = "", key_env: str = "", model: str = ""):
        self.base_url, self.key_env, self.model = base_url, key_env, model

    def build(self, request):
        return to_native(request)

    def parse(self, reply_json, request):
        return from_native(reply_json, request)
