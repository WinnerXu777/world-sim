"""Install the harness into the live Engine through the hooks that already exist (``simulation.dispatch.DISPATCH``), behind a flag.

Nothing here edits ``Engine.step``. With ``EDEN_HARNESS=1`` in the environment, ``install(DISPATCH)`` registers (idempotently, as
builtin hooks so ``DISPATCH.clear()`` in tests does not silently remove them):

* genesis hook ``harness_world``     (S0) build the shared ``EngineWorld`` and attach it as ``engine.harness``;
* post-step hook ``harness_events``   (S1) mirror god events (``inventory_state['god']['events']``) into the harness ``EventLedger``;
* post-step hook ``harness_parity``   (S2) check the harness's record of the legacy system order against ``engine._registry``;
* executor ``harness_power``          (S4) apply a harness power (plan then atomic apply) from a command in the inbox.

With ``EDEN_SPACES=1`` (independent of ``EDEN_HARNESS``) ``install`` also registers the space-column refresh (post-step hook
``harness_spaces`` and genesis hook ``harness_spaces_genesis``, P3b) and refuses to boot without ``EDEN_PERCEPTION_BOUNDED=1``.

S0-S2 only read the engine (they never write tensors or legacy state); S4 changes the world only when a client sends the new
command. A failure inside a hook is recorded in ``engine.harness.errors`` (the dispatcher would otherwise only log it).
See ``1008_scheduler_design.md``.
"""
from __future__ import annotations

import os
from typing import Any, Optional

FLAG = "EDEN_HARNESS"
HOOK_NAMES = ("harness_world", "harness_events", "harness_parity", "harness_spaces", "harness_spaces_genesis", "harness_window",
              "harness_window_genesis", "harness_creatures", "harness_temperature_genesis", "harness_wounds", "harness_steering_genesis", "harness_sleep_genesis", "harness_darkness_genesis")
EXECUTOR = "harness_power"
MAX_ERRORS = 64


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


class HarnessRuntime:
    """Per-engine harness state. Rebuilt when the engine starts a new world (``engine.world_epoch`` changes)."""

    def __init__(self, engine):
        from . import powers
        from .adapter import EngineWorld
        from .registry import Registry
        self.engine = engine
        self.epoch = engine.world_epoch
        self.world = EngineWorld(engine)
        self.errors: list = []
        self.registry = powers.REGISTRY
        self._mirrored: dict = {}                  # legacy god event id -> number of witnesses already mirrored
        self._legacy_ids: tuple = ()
        self._signature_now: tuple = ()
        self._schedule_problem: Optional[str] = None
        self.legacy = Registry()
        self.record_legacy_order()

    # S1 ----------------------------------------------------------------------------------------------------------
    def mirror_god_events(self) -> int:
        """Copy new god events (and new witnesses of known ones) into the harness ledger. Read-only on legacy state."""
        god = self.engine.inventory_state.get("god")
        events = god.get("events") if isinstance(god, dict) else None
        if not events:
            return 0
        ledger, copied = self.world.events, 0
        for event_id, entry in list(events.items()):
            witnesses = tuple(entry.get("witnesses", ()))
            if self._mirrored.get(event_id) == len(witnesses):
                continue
            point = entry.get("point")
            ledger.emit(str(entry.get("kind", "god_event")), actors=(entry["target_id"],) if entry.get("target_id") else (),
                        place=None if point is None else (float(point[0]), float(point[1])), visibility="local",
                        witnesses=witnesses, event_id=f"god:{event_id}", cause="legacy:god", tick=int(entry.get("tick", 0)),
                        payload={"legacy_event_id": event_id})
            self._mirrored[event_id] = len(witnesses)
            copied += 1
        return copied

    # S2 ----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _order(engine) -> tuple:
        return tuple((getattr(e["fn"], "__name__", repr(e["fn"])), e["priority"]) for e in engine._registry)

    @staticmethod
    def _signature(engine) -> tuple:
        """Cheap per-tick fingerprint of the registry (function identity and priority, in order)."""
        return tuple((id(e["fn"]), e["priority"]) for e in engine._registry)

    def record_legacy_order(self) -> tuple:
        """(Re)declare every ``engine._registry`` entry as a harness legacy system in the engine's order."""
        from .registry import Registry
        self.legacy = Registry()
        order = self._order(self.engine)
        previous = None
        for index, (name, _priority) in enumerate(order):
            unique = f"{index:03d}:{name}"
            self.legacy.add_system(lambda world: None, unique, phase="act", after=(previous,) if previous else ())
            previous = unique
        self._legacy_ids = order
        self._signature_now = self._signature(self.engine)
        scheduled = tuple(spec.name.split(":", 1)[1] for spec in self.legacy.schedule())
        self._schedule_problem = (None if scheduled == tuple(name for name, _ in order)
                                  else "harness schedule order differs from engine._registry order")
        return order

    def parity(self) -> Optional[str]:
        """None when the harness's record matches ``engine._registry`` (names, priorities, order) and its schedule runs in that
        order; otherwise a description of the first difference."""
        if self._signature(self.engine) == self._signature_now:       # fast path every tick: no names, no scheduling
            return self._schedule_problem
        now = self._order(self.engine)
        return f"engine._registry changed: {len(self._legacy_ids)} -> {len(now)} entries or order differs"

    def note_error(self, where: str, exc: BaseException) -> None:
        self.errors.append((int(self.engine.tick), where, repr(exc)))
        del self.errors[:-MAX_ERRORS]


# -- accessor ----------------------------------------------------------------------------------------------------------
def runtime(engine) -> HarnessRuntime:
    """The engine's harness runtime, built on first use and rebuilt for a new world."""
    current = getattr(engine, "harness", None)
    if current is None or current.epoch != engine.world_epoch:
        current = HarnessRuntime(engine)
        engine.harness = current
    return current


# -- hooks -------------------------------------------------------------------------------------------------------------
def _guarded(where: str):
    def wrap(fn):
        def hook(engine, *args):
            try:
                return fn(engine, *args)
            except Exception as exc:  # noqa: BLE001 - recorded, never allowed to abort the tick
                try:
                    runtime(engine).note_error(where, exc)
                except Exception:  # noqa: BLE001 - even the recorder failed; the dispatcher logs it
                    raise exc
        hook.__name__ = where
        return hook
    return wrap


@_guarded("harness_world")
def genesis_hook(engine, map_name=None) -> None:
    from . import needs, resources
    if needs.enabled():                                  # S3 pilot: swap before the runtime records the registry order
        needs.install(engine)
    engine.node_regrow_external = False                  # a new world starts with the legacy node regrow
    if resources.enabled():                              # G-005 step 3: harness node regrow after the legacy regrow entry
        resources.install(engine)
    runtime(engine)


@_guarded("harness_events")
def events_hook(engine) -> None:
    runtime(engine).mirror_god_events()


@_guarded("harness_parity")
def parity_hook(engine) -> None:
    rt = runtime(engine)
    problem = rt.parity()
    if problem:
        rt.note_error("harness_parity", RuntimeError(problem))
        rt.record_legacy_order()                    # re-record so one change is reported once, not every tick


@_guarded("harness_spaces")
def spaces_hook(engine) -> None:
    from . import spaces
    spaces.refresh(engine, gated=True)


@_guarded("harness_spaces_genesis")
def spaces_genesis_hook(engine, map_name=None) -> None:
    from . import spaces
    spaces.refresh(engine)


@_guarded("harness_window")
def window_hook(engine) -> None:
    from . import window_manager
    window_manager.manager_for(engine).tick()


@_guarded("harness_creatures")
def creatures_hook(engine) -> None:
    from systems.creatures import kernel
    kernel.step(engine)


@_guarded("harness_steering_genesis")
def steering_genesis_hook(engine, map_name=None) -> None:
    from . import steering
    if steering.enabled():                               # 2.A1: the six steering instincts join the registry before the runtime records its order
        steering.install(engine)


@_guarded("harness_wounds")
def wounds_hook(engine) -> None:
    from . import wounds
    wounds.step(engine)


@_guarded("harness_temperature_genesis")
def temperature_genesis_hook(engine, map_name=None) -> None:
    from . import temperature
    if temperature.enabled():                            # 2.A2: the comfort instinct joins the registry before the runtime records its order
        temperature.install(engine)


@_guarded("harness_sleep_genesis")
def sleep_genesis_hook(engine, map_name=None) -> None:
    from . import sleep
    if sleep.enabled():                                  # 2.A2: sleep pressure joins the registry before the runtime records its order
        sleep.install(engine)


@_guarded("harness_darkness_genesis")
def darkness_genesis_hook(engine, map_name=None) -> None:
    from . import darkness
    if darkness.enabled():                               # 2.A2: darkness unease joins the registry before the runtime records its order
        darkness.install(engine)


@_guarded("harness_window_genesis")
def window_genesis_hook(engine, map_name=None) -> None:
    from . import window_manager
    window_manager.manager_for(engine)


def execute_power(engine, action, payload) -> dict:
    """Command executor: ``{"power": name, "args": {...}, "dry_run": bool}`` -> plan, then (unless dry run) atomic apply."""
    from . import powers
    payload = payload if isinstance(payload, dict) else {}
    name = payload.get("power")
    if not isinstance(name, str) or not name:
        return {"ok": False, "reason": "invalid_arguments", "errors": ["power must be a non-empty string"]}
    try:
        rt = runtime(engine)
        result = powers.call(rt.world, name, payload.get("args") or {}, dry_run=bool(payload.get("dry_run", False)),
                             registry=rt.registry)
    except Exception as exc:  # noqa: BLE001 - a command must answer, not crash the tick
        return {"ok": False, "reason": "internal_error", "errors": [repr(exc)]}
    plan = result.plan
    out: dict[str, Any] = {"ok": result.ok, "reason": result.reason, "errors": list(plan.errors) if plan else [],
                           "power": name, "dry_run": bool(payload.get("dry_run", False)), "risk": plan.risk if plan else "",
                           "targets": list(plan.targets) if plan else [], "preview": dict(plan.preview) if plan else {}}
    if result.ok and not out["dry_run"]:
        out["event_ids"] = list(result.event_ids)
        out["replanned"] = result.replanned
        engine._force_frame_refresh = True
        if any(table == "entities" for table in _tables_touched(plan)):
            engine._force_map_refresh = True
        from . import spaces
        spaces.refresh(engine)                           # a power may have moved or created rows: columns current for this tick's systems
    return out


def _tables_touched(plan) -> set:
    return {getattr(effect, "table", None) for effect in plan.effects} - {None}


# -- install -----------------------------------------------------------------------------------------------------------
def install(dispatch) -> bool:
    """Register the hooks and the executor on ``dispatch`` (idempotent). Returns False when no flag is on and nothing was added.
    Raises ``spaces.SpaceConfigError`` when EDEN_SPACES=1 without EDEN_PERCEPTION_BOUNDED=1."""
    from . import spaces
    from .numerics import spaces_enabled
    names = {name for hooks in (dispatch.step_hooks, dispatch.post_step_hooks, dispatch.genesis_hooks) for name, _ in hooks}
    with_spaces = spaces_enabled()
    if with_spaces:
        spaces.check_flags()
        if "harness_spaces_genesis" not in names:
            dispatch.register_genesis_hook("harness_spaces_genesis", spaces_genesis_hook, builtin=True)
        if "harness_spaces" not in names:
            dispatch.register_post_step_hook("harness_spaces", spaces_hook, builtin=True)
    if os.environ.get("EDEN_TEMPERATURE", "") == "1" and "harness_temperature_genesis" not in names:        # registered before harness_world: the registry is complete when the runtime records it
        dispatch.register_genesis_hook("harness_temperature_genesis", temperature_genesis_hook, builtin=True)
    if os.environ.get("EDEN_SLEEP", "") == "1" and "harness_sleep_genesis" not in names:
        dispatch.register_genesis_hook("harness_sleep_genesis", sleep_genesis_hook, builtin=True)
    if os.environ.get("EDEN_DARKNESS", "") == "1" and "harness_darkness_genesis" not in names:
        dispatch.register_genesis_hook("harness_darkness_genesis", darkness_genesis_hook, builtin=True)
    if os.environ.get("EDEN_STEERING", "") == "1" and "harness_steering_genesis" not in names:
        dispatch.register_genesis_hook("harness_steering_genesis", steering_genesis_hook, builtin=True)
    if os.environ.get("EDEN_DANGER", "") == "1":
        from . import danger
        danger.install()                                  # 2.A3: the danger ledger listens to the hit detector below
    if (os.environ.get("EDEN_WOUNDS", "") == "1" or os.environ.get("EDEN_DANGER", "") == "1") and "harness_wounds" not in names:                        # 2.A2: after the tick's damage and the resident movement: hits are the HP drops of the tick
        dispatch.register_post_step_hook("harness_wounds", wounds_hook, builtin=True)
    from .numerics import window_enabled
    if os.environ.get("EDEN_WINDOW_DORMANCY", "") == "1" and not window_enabled():
        raise spaces.SpaceConfigError("EDEN_WINDOW_DORMANCY=1 requires EDEN_WINDOW=1: dormancy is defined by the integrated window. Set it or unset EDEN_WINDOW_DORMANCY.")
    if os.environ.get("EDEN_STRUCTURE_STORE", "") == "1" and not window_enabled():
        raise spaces.SpaceConfigError("EDEN_STRUCTURE_STORE=1 requires EDEN_WINDOW=1: the store is keyed by window chunk. Set it or unset EDEN_STRUCTURE_STORE.")
    if os.environ.get("EDEN_CREATURES", "") == "1" and not window_enabled():
        raise spaces.SpaceConfigError("EDEN_CREATURES=1 requires EDEN_WINDOW=1: creatures are stored and spawned per window chunk. Set it or unset EDEN_CREATURES.")
    if window_enabled():
        spaces.check_window_flags()
        import map_geo
        from .window import POCKET_ORIGINS, WINDOW_FRAME
        if not map_geo.sparse_enabled():                  # the sliding frame's tile grid, before any geometry exists
            try:
                map_geo.configure_window(WINDOW_FRAME[0], WINDOW_FRAME[1], WINDOW_FRAME[2], sparse=True)
                map_geo.configure_pockets(POCKET_ORIGINS)
            except RuntimeError as exc:
                raise spaces.SpaceConfigError(f"EDEN_WINDOW=1 must be installed before a world exists: {exc}") from exc
        if "harness_window_genesis" not in names:
            dispatch.register_genesis_hook("harness_window_genesis", window_genesis_hook, builtin=True)
        if "harness_window" not in names:
            dispatch.register_step_hook("harness_window", window_hook, builtin=True)
        if os.environ.get("EDEN_CREATURES", "") == "1" and "harness_creatures" not in names:       # after the window hook: populate first, then act
            from systems.creatures import kernel as _creature_kernel
            _creature_kernel.install()
            dispatch.register_step_hook("harness_creatures", creatures_hook, builtin=True)
    if not enabled():
        return with_spaces or window_enabled()
    if "harness_world" not in names:
        dispatch.register_genesis_hook("harness_world", genesis_hook, builtin=True)
    if "harness_events" not in names:
        dispatch.register_post_step_hook("harness_events", events_hook, builtin=True)
    if "harness_parity" not in names:
        dispatch.register_post_step_hook("harness_parity", parity_hook, builtin=True)
    dispatch.register_executor(EXECUTOR, execute_power)
    return True


def uninstall(dispatch) -> None:
    """Remove what ``install`` added (tests)."""
    for name in HOOK_NAMES:
        dispatch.unregister_hook(name)
        dispatch.builtin_names.discard(name)
    try:
        from . import danger
        danger.uninstall()
    except ImportError:  # pragma: no cover
        pass
    try:
        from systems.creatures import kernel as _creature_kernel
        _creature_kernel.uninstall()
    except ImportError:  # pragma: no cover
        pass
    dispatch.executors.pop(EXECUTOR, None)
