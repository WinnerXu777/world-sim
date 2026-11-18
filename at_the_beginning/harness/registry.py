"""Declared systems, actions and powers: ``@system``, ``@action``, ``@power`` register themselves and generate the manifest.

This replaces float priorities (``instinct_move`` at 38, ``instinct_player_control_override`` at 37.75) and the hand-written
tool registry with declarations that can be checked:

* ``@system(name, phase, reads, writes, every, after)``: a per-tick system. ``reads``/``writes`` are ``"table.field"`` strings
  (``"humans.*"`` for a whole table). ``Registry.schedule()`` orders systems phase by phase; two systems that write the same
  field in one phase without an explicit ``after`` ordering are a build-time ``ScheduleError``, and a reader is placed after
  the writer of what it reads.
* ``@action(name, ...)``: something a resident can do (typed parameters, optional legality predicate name, risk, cost).
* ``@power(name, ...)``: a god/world power with ``plan(...)`` (pure) and ``apply`` semantics; flagged ``risk``.

``Registry.manifest()`` is the capability manifest: JSON-serialisable, deterministic, with a JSON Schema per callable and
``retrieval_text`` for ToolRAG. Legacy ``instinct_*``/``tool_*`` functions are declared in ``legacy_manifest.py`` and checked for
drift against the source by ``tests/test_harness_registry.py``.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Callable, Optional

from .schema import schema_for_function, validate

PHASES = ("sense", "needs", "decide", "act", "resolve", "world", "record")
AUDIENCES = ("system", "resident", "god")
RISKS = ("reversible", "destructive", "irreversible")
MANIFEST_VERSION = 1


class ScheduleError(ValueError):
    """Systems declared an impossible or ambiguous order."""


class RegistryError(ValueError):
    """Duplicate or malformed declaration."""


@dataclass
class Spec:
    kind: str
    name: str
    fn: Callable
    doc: str
    schema: dict
    audience: str
    module: str = ""
    extra: dict = field(default_factory=dict)

    def retrieval_text(self) -> str:
        params = ", ".join(self.schema.get("properties", {}))
        return f"{self.kind} {self.name}: {self.doc} Parameters: {params or 'none'}."


@dataclass
class SystemSpec(Spec):
    phase: str = "act"
    reads: tuple = ()
    writes: tuple = ()
    every: int = 1
    after: tuple = ()


def _first_line(fn: Callable) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _fields(values) -> tuple:
    out = tuple(sorted(set(values)))
    for item in out:
        if not isinstance(item, str) or "." not in item:
            raise RegistryError(f"field reference {item!r} must look like 'table.field' or 'table.*'")
    return out


def _overlap(a: tuple, b: tuple) -> set:
    """Field references that collide, treating ``table.*`` as every field of that table."""
    hits = set(a) & set(b)
    for x in a:
        for y in b:
            xt, xf = x.split(".", 1)
            yt, yf = y.split(".", 1)
            if xt == yt and (xf == "*" or yf == "*"):
                hits.add(x if xf != "*" else y)
    return hits


def _item_declaration(consumes, produces) -> dict:
    """Manifest fields for the items an action/power may destroy or create (empty = neither: the common case adds no keys)."""
    out = {}
    if consumes:
        out["consumes"] = _item_names(consumes)
    if produces:
        out["produces"] = _item_names(produces)
    return out


def _item_names(declared):
    names = sorted(declared.keys() if isinstance(declared, dict) else declared)
    for name in names:
        if not isinstance(name, str) or not name:
            raise RegistryError(f"declared item names must be non-empty strings, got {name!r}")
    return names


class Registry:
    def __init__(self):
        self.systems: dict[str, SystemSpec] = {}
        self.actions: dict[str, Spec] = {}
        self.powers: dict[str, Spec] = {}

    # registration ---------------------------------------------------------------
    def add_system(self, fn, name, *, phase, reads=(), writes=(), every=1, after=()) -> SystemSpec:
        name = name or fn.__name__
        if phase not in PHASES:
            raise RegistryError(f"system {name!r}: phase must be one of {PHASES}")
        if not isinstance(every, int) or every < 1:
            raise RegistryError(f"system {name!r}: 'every' must be an integer >= 1")
        if name in self.systems:
            raise RegistryError(f"system {name!r} is already registered")
        spec = SystemSpec(kind="system", name=name, fn=fn, doc=_first_line(fn), schema=schema_for_function(fn), audience="system",
                          module=getattr(fn, "__module__", ""), phase=phase, reads=_fields(reads), writes=_fields(writes),
                          every=every, after=tuple(sorted(after)))
        self.systems[name] = spec
        return spec

    def add_action(self, fn, name, *, risk="reversible", precondition="", cost=0.0, cooldown_ticks=0, interruptible=True,
                   consumes=(), produces=()) -> Spec:
        return self._add(self.actions, "action", fn, name, "resident", risk,
                         {"precondition": precondition, "cost": cost, "cooldown_ticks": cooldown_ticks, "interruptible": interruptible,
                          **_item_declaration(consumes, produces)})

    def add_power(self, fn, name, *, risk="reversible", authority="god", precondition="", consumes=(), produces=()) -> Spec:
        return self._add(self.powers, "power", fn, name, "god", risk, {"authority": authority, "precondition": precondition,
                                                                     **_item_declaration(consumes, produces)})

    def _add(self, store, kind, fn, name, audience, risk, extra) -> Spec:
        name = name or fn.__name__
        if risk not in RISKS:
            raise RegistryError(f"{kind} {name!r}: risk must be one of {RISKS}")
        if name in store:
            raise RegistryError(f"{kind} {name!r} is already registered")
        spec = Spec(kind=kind, name=name, fn=fn, doc=_first_line(fn), schema=schema_for_function(fn), audience=audience,
                    module=getattr(fn, "__module__", ""), extra={"risk": risk, **extra})
        store[name] = spec
        return spec

    # scheduling -----------------------------------------------------------------
    def schedule(self, tick: Optional[int] = None) -> list:
        """Systems in execution order (phase order, then dependencies). With ``tick``, only those due on that tick."""
        ordered: list[SystemSpec] = []
        for phase in PHASES:
            members = {n: s for n, s in self.systems.items() if s.phase == phase}
            ordered.extend(self._order_phase(phase, members))
        if tick is not None:
            ordered = [s for s in ordered if tick % s.every == 0]
        return ordered

    def _order_phase(self, phase: str, members: dict) -> list:
        names = sorted(members)
        edges = {n: set() for n in names}                      # edges[a] contains b: a must run before b
        explicit = set()
        for n, spec in members.items():
            for dep in spec.after:
                if dep not in members:
                    raise ScheduleError(f"system {n!r} runs after {dep!r}, which is not registered in phase {phase!r}")
                edges[dep].add(n)
                explicit.add(frozenset((dep, n)))
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                conflict = _overlap(members[a].writes, members[b].writes)
                if conflict and not self._ordered(edges, a, b) and not self._ordered(edges, b, a):
                    raise ScheduleError(f"phase {phase!r}: {a!r} and {b!r} both write {sorted(conflict)} with no 'after' order")
        for a in names:                                        # a reader runs after the writer of what it reads
            for b in names:
                if a != b and _overlap(members[a].writes, members[b].reads):
                    edges[a].add(b)
        order, state = [], {}

        def visit(n):
            if state.get(n) == 2:
                return
            if state.get(n) == 1:
                raise ScheduleError(f"phase {phase!r}: dependency cycle through {n!r}")
            state[n] = 1
            for pred in sorted(p for p in names if n in edges[p]):
                visit(pred)
            state[n] = 2
            order.append(n)
        for n in names:
            visit(n)
        return [members[n] for n in order]

    @staticmethod
    def _ordered(edges, a, b) -> bool:
        """True if a path a -> b already exists."""
        seen, stack = set(), [a]
        while stack:
            n = stack.pop()
            if n == b:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(edges[n])
        return False

    def check_item_permit(self, name: str, permit, kind: str = "action") -> list:
        """Problems if ``permit`` asks to consume/produce items the spec did not declare (empty = within the declaration)."""
        store = {"action": self.actions, "power": self.powers}[kind]
        if name not in store:
            return [f"unknown {kind} {name!r}"]
        extra = store[name].extra
        problems = []
        for label, wanted in (("consumes", permit.consume), ("produces", permit.produce)):
            for item in sorted(set(wanted) - set(extra.get(label, ()))):
                problems.append(f"{kind} {name!r} does not declare {label} {item!r}")
        return problems

    # manifest -------------------------------------------------------------------
    def manifest(self, legacy: Optional[list] = None) -> dict:
        def entry(spec: Spec) -> dict:
            out = {"id": spec.name, "kind": spec.kind, "audience": spec.audience, "description": spec.doc, "args": spec.schema,
                   "module": spec.module, "retrieval_text": spec.retrieval_text(), **spec.extra}
            if isinstance(spec, SystemSpec):
                out.update(phase=spec.phase, reads=list(spec.reads), writes=list(spec.writes), every=spec.every, after=list(spec.after))
            return out
        return {"manifest_version": MANIFEST_VERSION,
                "systems": [entry(s) for s in self.schedule()],
                "actions": [entry(self.actions[n]) for n in sorted(self.actions)],
                "powers": [entry(self.powers[n]) for n in sorted(self.powers)],
                "legacy": [row for row in (legacy or []) if not row.get("legacy_frozen")],
                "legacy_frozen": sorted(row["id"] for row in (legacy or []) if row.get("legacy_frozen"))}

    def validate_call(self, name: str, args: dict, kind: str = "action") -> list:
        """Structured errors for a proposed call (empty = acceptable). The unknown name is itself an error."""
        store = {"action": self.actions, "power": self.powers, "system": self.systems}[kind]
        if name not in store:
            return [f"$: unknown {kind} {name!r}; known: {sorted(store)}"]
        return validate(store[name].schema, args)


# -- module-level default registry and decorators ----------------------------------------------------------------------
DEFAULT = Registry()


def system(name: Optional[str] = None, *, phase: str, reads=(), writes=(), every: int = 1, after=(), registry: Optional[Registry] = None):
    def wrap(fn):
        (registry or DEFAULT).add_system(fn, name, phase=phase, reads=reads, writes=writes, every=every, after=after)
        return fn
    return wrap


def action(name: Optional[str] = None, *, risk: str = "reversible", precondition: str = "", cost: float = 0.0, cooldown_ticks: int = 0,
           interruptible: bool = True, consumes=(), produces=(), registry: Optional[Registry] = None):
    """``consumes``/``produces``: item names this action may destroy/create (listed in the manifest; the per-call quantity cap
    comes from the ``ItemPermit`` the runner passes to ``World.apply``)."""
    def wrap(fn):
        (registry or DEFAULT).add_action(fn, name, risk=risk, precondition=precondition, cost=cost, cooldown_ticks=cooldown_ticks,
                                         interruptible=interruptible, consumes=consumes, produces=produces)
        return fn
    return wrap


def power(name: Optional[str] = None, *, risk: str = "reversible", authority: str = "god", precondition: str = "",
          consumes=(), produces=(), registry: Optional[Registry] = None):
    def wrap(fn):
        (registry or DEFAULT).add_power(fn, name, risk=risk, authority=authority, precondition=precondition, consumes=consumes,
                                        produces=produces)
        return fn
    return wrap
