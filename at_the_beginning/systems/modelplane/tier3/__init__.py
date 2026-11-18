"""Tier 3 over the model plane (round 2, 1008_tier3.md): typed prompt context, reply parsers, the confidence gate, the router that
requests plans / dialogue lines / world intents without blocking the tick, and the escalation policy. Default everything off."""
from .context import (DecidedOutcome, assert_case, dialogue_case, power_catalog, relationship_words, resident_case, world_case)
from .escalation import EscalationConfig, Escalator, classify, install
from .parsers import (GateConfig, fallback_line, gate_plan, parse_intents, parse_line, parse_plan, vet_intents)
from .router import Tier3Router
from .types import (DialogueLine, GateResult, PacketError, PlanProposal, Ticket, Tier3Result, WorldIntent)

__all__ = ["EscalationConfig", "Escalator", "classify", "install", "DecidedOutcome", "DialogueLine", "GateConfig", "GateResult", "PacketError", "PlanProposal", "Ticket", "Tier3Result", "Tier3Router",
           "WorldIntent", "assert_case", "dialogue_case", "fallback_line", "gate_plan", "parse_intents", "parse_line", "parse_plan",
           "power_catalog", "relationship_words", "resident_case", "vet_intents", "world_case"]
