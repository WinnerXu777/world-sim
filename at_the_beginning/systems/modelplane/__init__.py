"""Model plane (game side): async client, per-role budgets, circuit breakers, the off|shadow|on LLM switch, legacy-hook adapters.

Default is everything OFF: no thread, no socket. See 1008_model_api.md.
"""
from .breaker import CircuitBreaker
from .budget import Admission
from .client import Job, ModelClient, Outcome
from .config import Endpoint, ModelPlaneConfig
from .metrics import ModelMetrics
from .plane import AnswerCache, Completed, ModelPlane, case_key
from .switch import MODES, ROLE_SLOT, SLOTS, ModelSwitch, SwitchError
from .transport import HttpxTransport, Transport, TransportError, TransportReply, TransportTimeout

__all__ = ["Admission", "AnswerCache", "CircuitBreaker", "Completed", "Endpoint", "HttpxTransport", "Job", "MODES", "ModelClient",
           "ModelMetrics", "ModelPlane", "ModelPlaneConfig", "ModelSwitch", "Outcome", "ROLE_SLOT", "SLOTS", "SwitchError", "Transport",
           "TransportError", "TransportReply", "TransportTimeout", "case_key"]
