"""Pausing: simulation time stops, transport and commands keep working.

While paused ``Engine.step`` calls ``pause_step`` first and returns: no tick advances, no instinct, task, movement,
decision or commission tick runs. Queued commands (god powers, inventory, commissions) are still drained, so they
apply at this controlled boundary (the start of each paused step) and the frame is rebuilt so the client sees them.
"""
from .state import is_paused


def pause_step(engine):
    """While time is paused: drain queued commands, refresh the frame if asked, return True (the caller then skips the tick)."""
    if not is_paused(engine):
        return False
    from simulation.dispatch import DISPATCH
    engine.command_inbox.drain(engine, DISPATCH.execute)
    if engine._force_frame_refresh:
        h_mask, a_mask, _ = engine._current_masks()
        engine._build_frame_payload(h_mask, a_mask)
        engine._force_frame_refresh = False
    return True
