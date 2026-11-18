"""Tier 1 decision seam: typed options in, probabilities out. Stage 1 runs entirely on rules (no model)."""
from .contract import (DecisionError, DecisionOption, DecisionRequest, DecisionResult, PROVIDER_MODES, summarize,
                       validate_probabilities, validate_request)
from .log import DecisionLog, read_log
from .providers import (ClefDecisionProvider, DecisionProvider, ModelPending, RecordedDecisionProvider, RulesDecisionProvider,
                        SOFTMAX_TEMPERATURE, softmax)
from .service import DecisionService
from .matrix import GateConfig, MatrixDecisionProvider, MatrixPolicy

__all__ = ["ClefDecisionProvider", "DecisionError", "DecisionLog", "DecisionOption", "DecisionProvider", "DecisionRequest",
           "DecisionResult", "DecisionService", "GateConfig", "MatrixDecisionProvider", "MatrixPolicy", "ModelPending", "PROVIDER_MODES", "RecordedDecisionProvider", "RulesDecisionProvider",
           "SOFTMAX_TEMPERATURE", "read_log", "softmax", "summarize", "validate_probabilities", "validate_request"]
