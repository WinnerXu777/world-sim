"""Import shim for the shared wire contract (``model_server/contract.py`` at the repo root, stdlib only).

The game runs with ``at_the_beginning`` on ``sys.path``; the contract lives one level up so a standalone model server can use
it without the game. This module puts the repo root on ``sys.path`` when needed and re-exports the contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from model_server import contract
except ImportError:  # pragma: no cover - depends on how the game was launched
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from model_server import contract

Envelope = contract.Envelope
ContractError = contract.ContractError
ClefMappingHeld = contract.ClefMappingHeld
ROLES = contract.ROLES
ROLE_ROUTES = contract.ROLE_ROUTES
ROLE_TIER = contract.ROLE_TIER
LEGACY_MODE_ROLE = contract.LEGACY_MODE_ROLE
SCHEMA_VERSION = contract.SCHEMA_VERSION
parse_response = contract.parse_response
validate_probabilities = contract.validate_probabilities
