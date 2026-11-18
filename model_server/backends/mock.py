"""Deterministic mock backend: same request, same answer, in every process. No randomness, no network."""
from __future__ import annotations

from ..contract import Envelope
from .base import Backend, CallContext
from .heuristics import batch_result, decide_probabilities


class MockBackend(Backend):
    kind = "mock"
    provider_mode = "mock"
    model_id = "mock-v1"

    def __init__(self, delay_ms: float = 0.0):
        self.delay_ms = float(delay_ms)

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        if self.delay_ms:
            ctx.sleep(self.delay_ms / 1000.0)
        if envelope.role == "decide":
            return {"probabilities": decide_probabilities(envelope.payload)}
        return batch_result(envelope.payload, "mock_model_server")
