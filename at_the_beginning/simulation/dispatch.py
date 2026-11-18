"""Command executor registry and ordered engine hooks.

``CommandInbox.drain`` calls ``DISPATCH.execute``; actions are routed to registered executors and anything
unregistered goes to the default executor (the inventory executor, which is what ``drain`` used before this module
existed, so unknown actions behave exactly as they did). Three ordered hook lists let other systems extend the engine
without editing it:

* step hooks run once per tick from ``Engine.step`` after the movement reconcile (default: none);
* post-step hooks run once per tick after the slot/id sync, i.e. after resident task movement (default: none);
* genesis hooks run at the end of ``create_genesis`` (default: none).

A hook that raises is logged with its traceback and recorded in ``errors``; the remaining hooks still run, and the
tick is not aborted. Errors are never dropped silently.
"""
import logging
from collections import deque

LOG = logging.getLogger("eden.dispatch")


class Dispatcher:
    """Command executor registry plus the three ordered hook lists described above."""
    def __init__(self, default_executor=None):
        self.default_executor = default_executor
        self.executors = {}
        self.step_hooks = []     # [(name, fn(engine))]
        self.post_step_hooks = []  # [(name, fn(engine))] after the task phase
        self.genesis_hooks = []  # [(name, fn(engine, map_name))]
        self.builtin_names = set()  # hooks installed by the game itself; clear() keeps them
        self.errors = deque(maxlen=64)  # (kind, hook name, repr(exception)) of the most recent hook failures

    # command executors ------------------------------------------------------
    def register_executor(self, action, executor):
        if not isinstance(action, str) or not action or not callable(executor):
            raise ValueError("register_executor needs an action name and a callable")
        self.executors[action] = executor

    def execute(self, engine, action, payload):
        executor = self.executors.get(action, self.default_executor)
        if executor is None:
            return {"ok": False, "reason": "unknown_action"}
        return executor(engine, action, payload)

    # hooks ------------------------------------------------------------------
    def _register(self, hooks, name, fn, builtin=False):
        if not isinstance(name, str) or not name or not callable(fn):
            raise ValueError("a hook needs a name and a callable")
        if any(existing == name for existing, _ in hooks):
            raise ValueError(f"hook {name!r} is already registered")
        hooks.append((name, fn))
        if builtin:
            self.builtin_names.add(name)

    def register_step_hook(self, name, fn, builtin=False):
        self._register(self.step_hooks, name, fn, builtin)

    def register_post_step_hook(self, name, fn, builtin=False):
        self._register(self.post_step_hooks, name, fn, builtin)

    def register_genesis_hook(self, name, fn, builtin=False):
        self._register(self.genesis_hooks, name, fn, builtin)

    def unregister_hook(self, name):
        for hooks in (self.step_hooks, self.post_step_hooks, self.genesis_hooks):
            hooks[:] = [(n, fn) for n, fn in hooks if n != name]

    def clear(self, include_builtin=False):
        """Remove registered hooks except the game's own (builtin) ones; executors stay. Used by tests."""
        for hooks in (self.step_hooks, self.post_step_hooks, self.genesis_hooks):
            hooks[:] = [(n, fn) for n, fn in hooks if n in self.builtin_names and not include_builtin]
        if include_builtin:
            self.builtin_names.clear()
        self.errors.clear()

    def _run(self, kind, hooks, *args):
        failures = 0
        for name, fn in list(hooks):
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 - a hook must not abort the tick or the other hooks
                failures += 1
                self.errors.append((kind, name, repr(exc)))
                LOG.exception("%s hook %r failed", kind, name)
        return failures

    def run_step_hooks(self, engine):
        return self._run("step", self.step_hooks, engine) if self.step_hooks else 0

    def run_post_step_hooks(self, engine):
        return self._run("post_step", self.post_step_hooks, engine) if self.post_step_hooks else 0

    def run_genesis_hooks(self, engine, map_name):
        return self._run("genesis", self.genesis_hooks, engine, map_name) if self.genesis_hooks else 0


def _build_default():
    try:
        from simulation.inventory_commands import execute as inventory_execute
        from simulation.portal_commands import execute as portal_execute
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.simulation.inventory_commands import execute as inventory_execute
        from at_the_beginning.simulation.portal_commands import execute as portal_execute
    dispatcher = Dispatcher(default_executor=inventory_execute)
    for action in ("equip", "transfer"):
        dispatcher.register_executor(action, inventory_execute)
    dispatcher.register_executor("portal", portal_execute)
    return dispatcher


DISPATCH = _build_default()
