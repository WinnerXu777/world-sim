"""Registered Actions for the S1 verbs (17 + the batches of 1008_actions.md section 10.10), on their own harness ``Registry`` (kept apart from ``harness.registry.DEFAULT`` so the legacy
manifest and its drift tests are unaffected). Importing this package registers them."""
from harness.registry import Registry

REGISTRY = Registry()

from . import conflict, economy, exploration, social, survival, work  # noqa: E402,F401  (registration side effects)

__all__ = ["REGISTRY"]
