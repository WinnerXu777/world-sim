"""Declarations for the legacy ``instinct_*`` / ``tool_*`` functions and the drift check against the source.

Nothing in ``instincts_and_tools.py`` changes. This module reads that file with ``ast`` (no import, no torch) and produces:

* the signature of every function (``signatures()``), compared with the committed snapshot ``legacy_signatures.json`` by the
  drift test, so a new, removed or re-signed function fails CI until the declaration and the snapshot are updated deliberately;
* the **columns each function reads and writes**, found by scanning subscripts of ``h_tensor``/``m_tensor`` for the
  ``genesis_config`` column constants (``analyse()``). Direct uses are exact; ``via_calls`` adds those reached through other
  functions of the same module (a lower bound: calls into ``systems/*`` are listed, not followed). This is the first honest
  answer to "what does this instinct touch", replacing the undeclared ``ctx`` coupling;
* a **triage** (``TRIAGE``): audience, group and disposition per function, from the WS-H proposal (H.3), marked ``proposed``.
  Every function must be triaged; an unclassified or unknown name fails the drift test.

Regenerate the snapshot with ``python at_the_beginning/harness/legacy_manifest.py --write``.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IAT = ROOT / "at_the_beginning" / "instincts_and_tools.py"
CONFIG = ROOT / "at_the_beginning" / "genesis_config.py"
SNAPSHOT = Path(__file__).with_name("legacy_signatures.json")
NAME_RE = re.compile(r"^(instinct|tool)_\w+$")
TENSORS = {"h_tensor": "humans", "m_tensor": "entities", "h_tensor_ref": "humans"}
INPLACE = {"zero_", "copy_", "fill_", "index_fill_", "index_put_", "masked_fill_", "clamp_", "add_", "sub_", "mul_", "div_", "index_add_", "scatter_"}

# -- triage (proposal; see 1008implementation.md H.3) ----------------------------------------------------------------------
# name -> (audience, group, disposition). audience: system | god | internal | resident (a verb in disguise).
# disposition: keep | keep_chunk_aware | unify_mover | move_to_decision | merge:<target> | retire | primitive | to_verb:<verb>
_EXPLICIT = {
    # vital signs and physiology
    "instinct_age": ("system", "vital", "keep"), "instinct_hunger": ("system", "vital", "keep"),
    "instinct_thirst": ("system", "vital", "keep"), "instinct_stamina_tick": ("system", "vital", "keep"),
    "instinct_emotional_recovery": ("system", "vital", "keep"), "instinct_cooldown": ("system", "vital", "keep"),
    "instinct_die": ("system", "vital", "keep"), "instinct_hp_death": ("system", "vital", "keep"),
    "instinct_heal": ("system", "vital", "keep"), "instinct_shelter_check": ("system", "vital", "keep"),
    "instinct_structure_occupancy": ("system", "vital", "keep"), "instinct_infection_tick": ("system", "vital", "keep"),
    "instinct_eat": ("system", "vital", "keep"), "instinct_drink": ("system", "vital", "keep"),
    "instinct_proximity": ("system", "social", "keep"), "instinct_pairwise_relations": ("system", "social", "keep"),
    "instinct_reproduction_strategy": ("system", "social", "keep"), "instinct_attack": ("system", "conflict", "keep"),
    "instinct_born": ("internal", "population", "primitive"),
    # movement and steering
    "instinct_move": ("system", "movement", "unify_mover"), "instinct_search": ("system", "movement", "unify_mover"),
    "instinct_flee": ("system", "movement", "unify_mover"), "instinct_survival_navigation": ("system", "movement", "unify_mover"),
    "instinct_social_navigation": ("system", "movement", "unify_mover"), "instinct_schedule_navigation": ("system", "movement", "unify_mover"),
    "instinct_player_control_override": ("system", "movement", "unify_mover"), "instinct_incarnation_stabilize": ("system", "movement", "unify_mover"),
    # nature (chunk-aware, lazy for unloaded chunks)
    "instinct_nature_cycle": ("system", "nature", "keep_chunk_aware"), "instinct_fire_tick": ("system", "nature", "keep_chunk_aware"),
    "instinct_lava_tick": ("system", "nature", "keep_chunk_aware"), "instinct_resource_regrow": ("system", "nature", "keep_chunk_aware"),
    "instinct_water_cycle": ("system", "nature", "keep_chunk_aware"),
    "instinct_frontier_expand": ("system", "map", "retire"), "tool_expand_world_edge": ("god", "map", "retire"),
    # decision logic that sits in the tick loop but is not physics
    "tool_inherit_instinct": ("system", "decision", "move_to_decision"),
    # acquired instincts
    "tool_grant_instinct": ("god", "acquired_instincts", "keep"), "tool_revoke_instinct": ("god", "acquired_instincts", "keep"),
    # resident-level actions living as tools
    "tool_harvest_food": ("resident", "survival", "to_verb:gather_resource"), "tool_draw_water": ("resident", "survival", "to_verb:drink"),
    "tool_reproduce": ("system", "population", "keep"),
    # population powers
    "tool_baby_boom": ("god", "population", "keep"), "tool_migration": ("god", "population", "keep"),
    "tool_quarantine": ("god", "population", "keep"), "tool_cull": ("god", "population", "keep_destructive"),
    "tool_smite": ("god", "population", "keep_destructive"),
    # map-edit primitives
    "instinct_create_object": ("internal", "map_edit", "primitive"), "instinct_update_objects": ("internal", "map_edit", "primitive"),
    "instinct_retype_objects": ("internal", "map_edit", "primitive"), "instinct_create_scattered_objects": ("internal", "map_edit", "primitive"),
    "instinct_create_line_objects": ("internal", "map_edit", "primitive"),
}
_PREFIX_RULES = [
    # (regex on name, (audience, group, disposition))
    (r"^instinct_(designate_construction_site|gather_materials|build_with_humans|repair_with_humans|demolish_with_humans|find_buildable_site)$",
     ("internal", "structures", "merge:build_structure")),
    (r"^tool_(build_|construct_|designate_structure_site|find_buildable_site|gather_building_materials|repair_|demolish_|upgrade_houses)",
     ("god", "structures", "merge:build_structure")),
    (r"^tool_(wildfire|earthquake|storm|volcanic_eruption|drought|flood|plague|area_attack)$", ("god", "hazards", "merge:hazard")),
    (r"^(instinct_(populate_animals|relocate_animals)|tool_(spawn_animal_group|populate_|fill_land_with_animals|restock_lakes|herd_|scatter_animals|feed_animals|heal_animals|make_animals_flee|draw_animals|stampede))",
     ("god", "animals", "merge:animals")),
    (r"^tool_(bless|set_mood|set_threat|calm_area|panic_area|bounty_area|scarcity_area|set_aggression|enlighten|reset_cooldown|age_shift|life_exp_modify)$",
     ("god", "status", "merge:modify_attribute")),
    (r"^tool_(create_lake|settle_area|clear_land|irrigate_area|fertilize_area|regrow_forest|seed_world|create_wall|transform_area|create_forest_patch|create_mountain_chain|create_feature_near_feature)$",
     ("god", "terraform", "keep_chunk_aware")),
    (r"^animal_", ("system", "animals", "keep_chunk_aware")),
]


# D-005: frozen legacy functions. Kept in the repo and in the manifest rows (flagged ``legacy_frozen``), but never offered:
# ``Registry.manifest`` leaves them out of the listing that feeds ToolRAG / OpenAPI / god-API views.
FROZEN_LEGACY = frozenset({"instinct_frontier_expand", "tool_expand_world_edge"})


def triage(name: str):
    """(audience, group, disposition) for a legacy function name, or ``None`` if nobody classified it."""
    if name in _EXPLICIT:
        return _EXPLICIT[name]
    for pattern, value in _PREFIX_RULES:
        if re.search(pattern, name):
            return value
    return None


# -- source reading ------------------------------------------------------------------------------------------------------
def _tree(path: Path = IAT) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def functions(path: Path = IAT) -> dict:
    return {n.name: n for n in _tree(path).body if isinstance(n, ast.FunctionDef)}


def legacy_names(path: Path = IAT) -> list:
    return sorted(n for n in functions(path) if NAME_RE.match(n))


def signatures(path: Path = IAT) -> dict:
    """name -> ``ast.unparse`` of the argument list, for every ``instinct_*``/``tool_*`` function."""
    fns = functions(path)
    return {n: ast.unparse(fns[n].args) for n in legacy_names(path)}


def config_columns(path: Path = CONFIG) -> set:
    """Upper-case integer constants of genesis_config (the column names usable in subscripts)."""
    names = set()
    for node in _tree(path).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id.isupper() and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                names.add(node.targets[0].id)
    return names


def _column_names(slice_node, columns: set) -> set:
    found = set()
    for node in ast.walk(slice_node):
        if isinstance(node, ast.Name) and node.id in columns:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in columns:
            found.add(node.attr)
    return found


class _Analyser(ast.NodeVisitor):
    def __init__(self, columns):
        self.columns, self.reads, self.writes, self.calls, self.delegates = columns, set(), set(), set(), set()

    def visit_Subscript(self, node):
        base = node.value
        if isinstance(base, ast.Name) and base.id in TENSORS:
            table, cols = TENSORS[base.id], _column_names(node.slice, self.columns)
            fields = {f"{table}.{c}" for c in cols} or {f"{table}.*"}
            if isinstance(node.ctx, ast.Store):
                self.writes |= fields
            elif isinstance(node.ctx, ast.Del):
                self.writes |= fields
            else:
                self.reads |= fields
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Subscript) and isinstance(node.target.value, ast.Name) and node.target.value.id in TENSORS:
            table, cols = TENSORS[node.target.value.id], _column_names(node.target.slice, self.columns)
            fields = {f"{table}.{c}" for c in cols} or {f"{table}.*"}
            self.reads |= fields
            self.writes |= fields
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.add(ast.unparse(node.func))
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in TENSORS and node.func.attr in INPLACE:   # h_tensor.zero_(), .copy_(), ...
                self.writes.add(f"{TENSORS[base.id]}.*")
        passed = [a for a in [*node.args, *(k.value for k in node.keywords)] if isinstance(a, ast.Name) and a.id in TENSORS]
        if passed:   # the tensor is handed to another function: record who gets it (its effects are not followed)
            callee = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)
            self.delegates.add(f"{callee}({', '.join(sorted({TENSORS[a.id] for a in passed}))})")
        self.generic_visit(node)


def analyse(path: Path = IAT) -> dict:
    """name -> {reads_direct, writes_direct, reads, writes (through same-module callees), delegates_tensors_to, external_calls} for each legacy function."""
    columns, fns = config_columns(), functions(path)
    direct = {}
    for name, node in fns.items():
        analyser = _Analyser(columns)
        analyser.visit(node)
        direct[name] = analyser
    out = {}
    for name in legacy_names(path):
        reads, writes, seen, stack, external = set(direct[name].reads), set(direct[name].writes), {name}, [name], set()
        delegates = set(direct[name].delegates)
        while stack:
            current = stack.pop()
            for callee in direct[current].calls:
                if callee in fns and callee not in seen:
                    seen.add(callee)
                    stack.append(callee)
                    reads |= direct[callee].reads
                    writes |= direct[callee].writes
                    delegates |= direct[callee].delegates
                elif callee not in fns and "." in callee and not callee.startswith(("torch.", "math.", "random.", "np.", "self.")):
                    external.add(callee)
        out[name] = {"reads_direct": sorted(direct[name].reads), "writes_direct": sorted(direct[name].writes),
                     "reads": sorted(reads), "writes": sorted(writes), "delegates_tensors_to": sorted(delegates),
                     "external_calls": sorted(external)}
    return out


def legacy_entries(path: Path = IAT) -> list:
    """Manifest rows for every legacy function (declared, with triage and analysed columns)."""
    sigs, cols = signatures(path), analyse(path)
    rows = []
    for name in legacy_names(path):
        t = triage(name)
        rows.append({"id": name, "kind": name.split("_", 1)[0], "signature": sigs[name],
                     "audience": t[0] if t else None, "group": t[1] if t else None, "disposition": t[2] if t else None,
                     "status": "proposed" if t else "unclassified", "legacy_frozen": name in FROZEN_LEGACY, **cols[name]})
    return rows


# -- drift ---------------------------------------------------------------------------------------------------------------
def drift(path: Path = IAT, snapshot: Path = SNAPSHOT) -> dict:
    """What differs between the source, the committed signature snapshot and the triage table (all lists empty = no drift)."""
    current = signatures(path)
    saved = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
    return {
        "undeclared_new": sorted(set(current) - set(saved)),            # in the code, not in the snapshot
        "declared_but_gone": sorted(set(saved) - set(current)),         # in the snapshot, removed from the code
        "signature_changed": sorted(n for n in set(current) & set(saved) if current[n] != saved[n]),
        "unclassified": sorted(n for n in current if triage(n) is None),
        "triage_for_unknown": sorted(n for n in _EXPLICIT if n not in current),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="rewrite legacy_signatures.json from the current source")
    parser.add_argument("--manifest", type=Path, help="write the legacy manifest rows (JSON) here")
    args = parser.parse_args()
    if args.write:
        SNAPSHOT.write_text(json.dumps(signatures(), indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {SNAPSHOT} ({len(signatures())} functions)")
    if args.manifest:
        args.manifest.write_text(json.dumps(legacy_entries(), indent=1), encoding="utf-8")
    report = drift()
    print(json.dumps(report, indent=1))
    return 0 if not any(report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
