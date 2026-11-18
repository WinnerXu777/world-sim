"""Creature balance attribution observer (R0.3 concrete evidence prerequisite).

Provides reversible, narrowly scoped instrumentation of actual simulation damage and death
paths to record TRUE death causes and human HP damage sources rather than after-the-fact
nearest-creature spatial inference.

Key contracts:
1. Reversible: original functions and engine callbacks are restored bit-for-bit, including on raised exceptions.
2. Exact causality: records victim identity (slot + UID at time of blow). For genuine single attacker blows,
   records exact attacker UID, species, requested vs actual applied damage, and overkill. For ambiguous
   simultaneous multi-attacker lethal blows, reports killer UID/slot/species as 'unknown' rather than
   fabricating a single killer, while storing bounded attacker candidates with exact contributions.
3. Structurally memory-bounded: bounds memory structurally per actual cfg.MAX_HUMANS slots, finite known
   causes and species labels (summary damage_by_species never uses unbounded joined strings), capped latest
   damage ring per resident (cap 16), capped first-death summaries (cap 8), and capped attacker candidates (cap 8).
4. Slot isolation & authoritative UID sync: validates slot bounds and synchronizes with authoritative
   engine UIDs; on resident death, reset, or unexpected engine UID replacement, active history for the slot
   is cleared so recycled slots never leak past lethal records.
5. Honesty: unattributed HP loss is recorded as "unattributed_hp_loss" / "unknown", never faked
   as an animal or old-age death. Unresolved type zeroing remains "unresolved_type_removal".

"""
from __future__ import annotations

import collections
from collections import deque
from dataclasses import asdict, dataclass
import inspect
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
if str(ROOT / "at_the_beginning") not in sys.path:
    sys.path.insert(0, str(ROOT / "at_the_beginning"))

try:
    import genesis_config as cfg
    from systems.creatures import table
except ImportError:
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.systems.creatures import table

LEGACY_NAMES: dict[int, str] = {row["id"]: name for name, row in table.CREATURES.items()}


@dataclass
class DamageEvent:
    tick: int
    probe_tick: int
    phase: str
    victim_slot: int
    victim_uid: Optional[str]
    source: str
    attacker_uid: Optional[str]
    attacker_species: Optional[str]
    attacker_slot: Optional[Any]
    damage_requested: float
    damage_applied: float
    victim_hp_before: float
    victim_hp_after: float
    is_lethal: bool
    overkill: float
    attacker_candidates: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)



class AttributionObserver:
    """Non-invasive, reversible observer for human damage and death attribution."""

    def __init__(
        self,
        engine: Any = None,
        humans_count: int = 6,
        ring_size: int = 16,
        max_first_deaths: int = 8,
    ) -> None:
        self.engine = engine
        max_slots = getattr(cfg, "MAX_HUMANS", 64)
        self.humans_count = min(max(humans_count, 1), max_slots)
        self.ring_size = max(1, ring_size)
        self.max_first_deaths = max(1, max_first_deaths)

        # Bounded resident damage rings and active state per valid slot
        self.damage_rings: dict[int, deque] = {
            i: deque(maxlen=self.ring_size) for i in range(self.humans_count)
        }
        self.latest_lethal_records: dict[int, Optional[dict[str, Any]]] = {
            i: None for i in range(self.humans_count)
        }
        self.old_age_flags: dict[int, bool] = {i: False for i in range(self.humans_count)}
        self.victim_uids: dict[int, Optional[str]] = {i: None for i in range(self.humans_count)}

        # Run-wide aggregates (bounded: finite known causes and species labels)
        self.first_deaths: list[dict[str, Any]] = []
        self.total_deaths: int = 0
        self.total_damage_applied: float = 0.0
        self.deaths_by_cause: dict[str, int] = collections.defaultdict(int)
        self.deaths_by_killer_species: dict[str, int] = collections.defaultdict(int)
        self.damage_by_source: dict[str, float] = collections.defaultdict(float)
        self.damage_by_species: dict[str, float] = collections.defaultdict(float)
        self.proximity_match_count: int = 0

        # Instrumentation internals
        self._installed: bool = False
        self._patched_modules: list[Tuple[Any, str, Any]] = []
        self._patched_registry_entries: list[Tuple[dict, Any]] = []
        self._current_context: Optional[dict[str, Any]] = None
        self._current_probe_tick: int = 0

    def _validate_and_sync_slot(self, slot: int) -> Optional[str]:
        """Validate slot bounds and sync with authoritative engine UID.

        If authoritative engine UID changes unexpectedly (e.g. root recycling fixture),
        clears stored damage ring and lethal records so recycled slots never leak stale history.
        """
        if not (0 <= slot < self.humans_count):
            return None

        authoritative_uid: Optional[str] = None
        if self.engine is not None and hasattr(self.engine, "_human_uid_by_slot"):
            uids = self.engine._human_uid_by_slot
            if 0 <= slot < len(uids):
                val = uids[slot]
                if val:
                    authoritative_uid = str(val)

        stored_uid = self.victim_uids.get(slot)
        if authoritative_uid is not None:
            if stored_uid is not None and stored_uid != authoritative_uid:
                self.on_human_reset(slot, new_uid=authoritative_uid)
                return authoritative_uid
            elif stored_uid is None:
                self.victim_uids[slot] = authoritative_uid
                return authoritative_uid

        return stored_uid

    def set_probe_tick(self, tick: int) -> None:
        self._current_probe_tick = tick

    def get_victim_uid(self, slot: int) -> Optional[str]:
        return self._validate_and_sync_slot(slot)

    def set_victim_uid(self, slot: int, uid: str) -> None:
        if 0 <= slot < self.humans_count:
            stored = self.victim_uids.get(slot)
            new_uid_str = str(uid)
            if stored is not None and stored != new_uid_str:
                self.on_human_reset(slot, new_uid=new_uid_str)
            else:
                self.victim_uids[slot] = new_uid_str

    def on_human_reset(self, slot: int, new_uid: Optional[str] = None) -> None:
        """Clear all active history for slot to ensure slot recycling does not leak stale state."""
        if not (0 <= slot < self.humans_count):
            return
        if slot in self.damage_rings:
            self.damage_rings[slot].clear()
        self.latest_lethal_records[slot] = None
        self.old_age_flags[slot] = False
        self.victim_uids[slot] = str(new_uid) if new_uid is not None else None

    def record_old_age_death(self, slot: int) -> None:
        if 0 <= slot < self.humans_count:
            self.old_age_flags[slot] = True

    def record_damage_event(
        self,
        victim_slot: int,
        damage_requested: float,
        damage_applied: float,
        victim_hp_before: float,
        victim_hp_after: float,
        *,
        source: str = "unknown",
        attacker_uid: Optional[str] = None,
        attacker_species: Optional[str] = None,
        attacker_slot: Optional[Any] = None,
        phase: Optional[str] = None,
        is_lethal: Optional[bool] = None,
        overkill: Optional[float] = None,
        tick: Optional[int] = None,
        probe_tick: Optional[int] = None,
        attacker_candidates: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Record an ordered damage event for a resident, updating ring and lethal transition."""
        if not (0 <= victim_slot < self.humans_count):
            return None

        # Authoritative UID validation & unexpected replacement detection
        victim_uid = self._validate_and_sync_slot(victim_slot)

        if is_lethal is None:
            is_lethal = bool(victim_hp_before > 0.0 and victim_hp_after <= 0.0)
        if overkill is None:
            overkill = max(0.0, float(damage_requested) - float(damage_applied))
        cur_tick = int(self.engine.tick) if self.engine is not None else int(tick or 0)
        cur_probe_tick = int(probe_tick if probe_tick is not None else self._current_probe_tick)

        # Cap candidates structurally
        capped_candidates = None
        if attacker_candidates is not None:
            capped_candidates = list(attacker_candidates[:8])

        event = DamageEvent(
            tick=cur_tick,
            probe_tick=cur_probe_tick,
            phase=str(phase or "damage"),
            victim_slot=int(victim_slot),
            victim_uid=victim_uid,
            source=str(source),
            attacker_uid=str(attacker_uid) if attacker_uid is not None else None,
            attacker_species=str(attacker_species) if attacker_species is not None else None,
            attacker_slot=int(attacker_slot) if isinstance(attacker_slot, int) else (str(attacker_slot) if attacker_slot is not None else None),
            damage_requested=round(float(damage_requested), 2),
            damage_applied=round(float(damage_applied), 2),
            victim_hp_before=round(float(victim_hp_before), 2),
            victim_hp_after=round(float(victim_hp_after), 2),
            is_lethal=bool(is_lethal),
            overkill=round(float(overkill), 2),
            attacker_candidates=capped_candidates,
        ).to_dict()

        if victim_slot not in self.damage_rings:
            self.damage_rings[victim_slot] = deque(maxlen=self.ring_size)
        self.damage_rings[victim_slot].append(event)

        if is_lethal:
            self.latest_lethal_records[victim_slot] = event

        # Aggregates
        applied_val = float(damage_applied)
        self.total_damage_applied += applied_val
        self.damage_by_source[str(source)] += applied_val

        # Summary damage_by_species: aggregate only fixed source/species table labels,
        # never joined strings like "wolf/wolf" or "wolf/boar".
        # If multi-attacker ambiguous or unallocated, aggregate under explicit "unknown".
        if capped_candidates is not None and len(capped_candidates) > 1:
            self.damage_by_species["unknown"] += applied_val
        elif attacker_species:
            sp_str = str(attacker_species)
            if sp_str in table.CREATURES:
                self.damage_by_species[sp_str] += applied_val
            elif sp_str == "unknown":
                self.damage_by_species["unknown"] += applied_val
            else:
                self.damage_by_species["unknown"] += applied_val

        return event

    def describe_death(
        self,
        i: int,
        tick: int,
        hp_before: float,
        *,
        pre_reset_state: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Produce a true causal death summary, preserving diagnostic continuity."""
        if not (0 <= i < self.humans_count):
            i = max(0, min(i, self.humans_count - 1))

        # Check authoritative UID
        cur_victim_uid = self._validate_and_sync_slot(i)

        h = self.engine.state.h_tensor if self.engine is not None else None
        m = self.engine.state.m_tensor[:cfg.MAX_ENTITIES] if self.engine is not None else None

        cur_tick = int(self.engine.tick) if self.engine is not None else int(tick)

        if pre_reset_state is not None:
            type_now = float(pre_reset_state.get("type", 0.0))
            hunger = float(pre_reset_state.get("hunger", 0.0))
            thirst = float(pre_reset_state.get("thirst", 0.0))
            age = float(pre_reset_state.get("age", 0.0))
        else:
            type_now = float(h[i, cfg.TYPE]) if h is not None else 0.0
            hunger = float(h[i, cfg.HUNGER]) if h is not None else 0.0
            thirst = float(h[i, cfg.THIRST]) if h is not None else 0.0
            age = float(h[i, cfg.H_AGE]) if h is not None else 0.0

        lethal_record = self.latest_lethal_records.get(i)
        # Check if lethal_record belongs to a previous resident UID in this slot
        if lethal_record is not None:
            rec_uid = lethal_record.get("victim_uid")
            if cur_victim_uid is not None and rec_uid is not None and rec_uid != cur_victim_uid:
                # Stale lethal record from recycled UID! Do not leak!
                lethal_record = None
                self.latest_lethal_records[i] = None

        is_old_age = self.old_age_flags.get(i, False)

        candidates: list[dict[str, Any]] = []
        if lethal_record is not None:
            candidates = lethal_record.get("attacker_candidates") or []
            is_ambiguous = len(candidates) > 1 or lethal_record.get("attacker_uid") == "unknown" or lethal_record.get("attacker_species") == "unknown"

            true_source = lethal_record["source"]
            is_creature = (
                lethal_record["attacker_species"] is not None
                or true_source in ("creature_kernel_attack", "legacy_predator_attack")
            )
            true_cause = "creature" if is_creature else true_source

            if is_ambiguous:
                # Ambiguous multiattacker lethal damage: report killer_uid/killer_slot/species UNKNOWN
                killer_species = "unknown"
                killer_uid = "unknown"
                killer_slot = "unknown"
            else:
                killer_species = lethal_record["attacker_species"]
                killer_uid = lethal_record["attacker_uid"]
                killer_slot = lethal_record["attacker_slot"]

            lethal_source = true_source
            damage_applied = lethal_record["damage_applied"]
            damage_requested = lethal_record["damage_requested"]
            overkill = lethal_record["overkill"]
        elif is_old_age:
            true_cause = "old_age"
            lethal_source = "instinct_die"
            killer_species = None
            killer_uid = None
            killer_slot = None
            damage_applied = 0.0
            damage_requested = 0.0
            overkill = 0.0
        elif hp_before > 0.0 and ((h is not None and float(h[i, cfg.HP]) <= 0.0) or type_now == 0.0):
            true_cause = "unattributed_hp_loss"
            lethal_source = "unknown"
            killer_species = None
            killer_uid = None
            killer_slot = None
            damage_applied = round(float(hp_before), 1)
            damage_requested = round(float(hp_before), 1)
            overkill = 0.0
        else:
            true_cause = "unresolved_type_removal"
            lethal_source = "unknown_removal"
            killer_species = None
            killer_uid = None
            killer_slot = None
            damage_applied = 0.0
            damage_requested = 0.0
            overkill = 0.0

        # Nearest creature check (retained for comparison & spatial diagnostics)
        nearest_creature = None
        if m is not None and h is not None:
            live = (
                (m[:, cfg.M_HP] > 0)
                & (m[:, cfg.M_SPACE] == 0)
                & (m[:, cfg.M_TYPE] >= 40)
                & (m[:, cfg.M_TYPE] < 80)
            )
            if bool(live.any()):
                d = ((m[:, cfg.CX] - h[i, cfg.X]) ** 2 + (m[:, cfg.CY] - h[i, cfg.Y]) ** 2).sqrt()
                d = torch.where(live, d, torch.full_like(d, float("inf")))
                k = int(d.argmin())
                sp_id = int(m[k, cfg.M_TYPE])
                sp_name = LEGACY_NAMES.get(sp_id, sp_id)
                nearest_creature = [sp_name, round(float(d[k]), 1)]

        proximity_matches = bool(
            nearest_creature is not None
            and killer_species is not None
            and str(nearest_creature[0]) == str(killer_species)
            and killer_species != "unknown"
        )
        if proximity_matches:
            self.proximity_match_count += 1

        recent_damage = list(self.damage_rings.get(i, []))

        out: dict[str, Any] = {
            "tick": cur_tick,
            "probe_tick": int(tick),
            "victim_slot": int(i),
            "victim_uid": cur_victim_uid,
            "hp_before": round(hp_before, 1),
            "type_now": type_now,
            "hunger": round(hunger, 1),
            "thirst": round(thirst, 1),
            "age": round(age, 1),
            "true_cause": true_cause,
            "lethal_source": lethal_source,
            "killer_species": killer_species,
            "killer_uid": killer_uid,
            "killer_slot": killer_slot,
            "damage_applied": damage_applied,
            "damage_requested": damage_requested,
            "overkill": overkill,
            "attacker_candidates": candidates,
            "nearest_creature": nearest_creature,
            "proximity_matches_true_killer": proximity_matches,
            "recent_damage": recent_damage,
            "attribution_method": "instrumented_actual_damage",
        }

        # Update run stats
        self.total_deaths += 1
        self.deaths_by_cause[true_cause] += 1
        if killer_species is not None:
            self.deaths_by_killer_species[str(killer_species)] += 1
        if len(self.first_deaths) < self.max_first_deaths:
            self.first_deaths.append(out)

        return out

    def summary(self) -> dict[str, Any]:
        """Bounded run-wide diagnostic summary."""
        total = self.total_deaths
        match_rate = round(self.proximity_match_count / max(total, 1), 3) if total else 0.0
        return {
            "total_deaths": total,
            "deaths_by_cause": dict(self.deaths_by_cause),
            "deaths_by_killer_species": dict(self.deaths_by_killer_species),
            "damage_by_source": {k: round(v, 1) for k, v in self.damage_by_source.items()},
            "damage_by_species": {k: round(v, 1) for k, v in self.damage_by_species.items()},
            "total_damage_applied": round(self.total_damage_applied, 1),
            "proximity_matches_true_killer_rate": match_rate,
            "unattributed_deaths": self.deaths_by_cause.get("unattributed_hp_loss", 0),
            "unresolved_deaths": self.deaths_by_cause.get("unresolved_type_removal", 0),
        }

    # -------------------------------------------------------------------------
    # Reversible Instrumentation
    # -------------------------------------------------------------------------

    def install(self) -> None:
        """Install reversible wrappers across actual simulation damage functions."""
        if self._installed:
            return

        observer = self

        # 1. Patch apply_human_damage in every module importing it
        modules_to_patch = []
        for mod_name in (
            "systems.health.damage",
            "at_the_beginning.systems.health.damage",
            "systems.health",
            "at_the_beginning.systems.health",
            "systems.creatures.kernel",
            "at_the_beginning.systems.creatures.kernel",
            "instincts_and_tools",
            "at_the_beginning.instincts_and_tools",
            "systems.survival.hunger",
            "at_the_beginning.systems.survival.hunger",
            "systems.survival.thirst",
            "at_the_beginning.systems.survival.thirst",
        ):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "apply_human_damage"):
                modules_to_patch.append((mod, "apply_human_damage"))

        # Find original function
        orig_apply_human_damage = None
        for mod, attr in modules_to_patch:
            fn = getattr(mod, attr)
            if orig_apply_human_damage is None:
                orig_apply_human_damage = fn
            break

        if orig_apply_human_damage is not None:
            def wrapped_apply_human_damage(mask: torch.Tensor, h_tensor: torch.Tensor, amount: Any, *, hp_col: int = cfg.HP) -> bool:
                if not bool(mask.any()):
                    return orig_apply_human_damage(mask, h_tensor, amount, hp_col=hp_col)

                slots = torch.where(mask)[0].tolist()
                hp_before = {s: float(h_tensor[s, hp_col]) for s in slots}

                # Execute original call (exact math, tensors, clamping, and semantics)
                result = orig_apply_human_damage(mask, h_tensor, amount, hp_col=hp_col)

                hp_after = {s: float(h_tensor[s, hp_col]) for s in slots}

                # Attribute damage to active context or inspecting caller frame
                ctx = observer._current_context
                caller_name = ""
                caller_locals = {}
                if ctx is None:
                    try:
                        frame = sys._getframe(1)
                        caller_name = frame.f_code.co_name
                        caller_locals = frame.f_locals
                    except Exception:
                        pass

                for idx, s in enumerate(slots):
                    before = hp_before[s]
                    after = hp_after[s]
                    applied = max(0.0, before - after)

                    # Determine requested amount
                    if isinstance(amount, torch.Tensor):
                        if amount.numel() == len(slots):
                            req = float(amount[idx])
                        elif amount.numel() == h_tensor.shape[0]:
                            req = float(amount[s])
                        else:
                            req = float(amount.flatten()[0])
                    else:
                        req = float(amount)

                    # Contextual attribution
                    candidates = None
                    if ctx is not None and ctx.get("phase") == "kernel_attack":
                        attackers = ctx.get("attackers_by_victim", {}).get(s, [])
                        if len(attackers) == 1:
                            atk = attackers[0]
                            source = ctx.get("source", "creature_kernel_attack")
                            species = atk.get("creature_species")
                            uid = atk.get("creature_uid")
                            c_slot = atk.get("creature_slot")
                            candidates = [atk]
                        elif len(attackers) > 1:
                            # Multiple same-tick attackers on this victim:
                            # Aggregated simultaneous damage does NOT prove first attacker delivered lethal blow.
                            # Report killer_uid/killer_slot/species UNKNOWN, while storing bounded candidates.
                            source = ctx.get("source", "creature_kernel_attack")
                            species = "unknown"
                            uid = "unknown"
                            c_slot = "unknown"
                            candidates = list(attackers[:8])
                        else:
                            source = ctx.get("source", "creature_kernel_attack")
                            species = None
                            uid = None
                            c_slot = None
                        phase = "kernel_attack"
                    elif caller_name == "animal_instinct_predator_attack":
                        i_pred = caller_locals.get("i")
                        sp_id = caller_locals.get("species")
                        c_ctx = caller_locals.get("ctx", {})
                        eng = c_ctx.get("engine", observer.engine)
                        species = LEGACY_NAMES.get(int(sp_id)) if sp_id is not None else "unknown_predator"
                        uid = None
                        if eng is not None and hasattr(eng, "_entity_uid_by_slot") and i_pred is not None:
                            if 0 <= i_pred < len(eng._entity_uid_by_slot):
                                uid = eng._entity_uid_by_slot[i_pred]
                        source = "legacy_predator_attack"
                        c_slot = i_pred
                        candidates = [{
                            "creature_slot": i_pred,
                            "creature_uid": uid,
                            "creature_species": species,
                            "damage_requested": req,
                        }]
                        phase = "legacy_predator_attack"
                    elif caller_name == "apply_hunger_tick":
                        source = "starvation"
                        species = None
                        uid = None
                        c_slot = None
                        phase = "needs_hunger"
                    elif caller_name == "apply_thirst_tick":
                        source = "dehydration"
                        species = None
                        uid = None
                        c_slot = None
                        phase = "needs_thirst"
                    else:
                        source = f"generic_damage:{caller_name}" if caller_name else "apply_human_damage"
                        species = None
                        uid = None
                        c_slot = None
                        phase = caller_name or "unknown"

                    is_lethal = bool(before > 0.0 and after <= 0.0)
                    overkill = max(0.0, req - applied)
                    observer.record_damage_event(
                        victim_slot=s,
                        damage_requested=req,
                        damage_applied=applied,
                        victim_hp_before=before,
                        victim_hp_after=after,
                        source=source,
                        attacker_uid=uid,
                        attacker_species=species,
                        attacker_slot=c_slot,
                        phase=phase,
                        is_lethal=is_lethal,
                        overkill=overkill,
                        attacker_candidates=candidates,
                    )
                return result

            for mod, attr in modules_to_patch:
                orig = getattr(mod, attr)
                self._patched_modules.append((mod, attr, orig))
                setattr(mod, attr, wrapped_apply_human_damage)

        # 2. Patch kernel._attack to capture attacker table identities
        for mod_name in ("systems.creatures.kernel", "at_the_beginning.systems.creatures.kernel"):
            k_mod = sys.modules.get(mod_name)
            if k_mod is not None and hasattr(k_mod, "_attack"):
                orig_attack = getattr(k_mod, "_attack")

                def wrapped_attack(engine, cidx, p, col, attacking, use_human, h_slots, dh_arg, a_slots, dp_arg):
                    m = engine.state.m_tensor
                    who = attacking.nonzero(as_tuple=False).flatten()
                    hit_human = use_human[who]
                    attackers_by_victim = collections.defaultdict(list)
                    if bool(hit_human.any()):
                        human_attackers = who[hit_human]
                        damage = p[human_attackers][:, col["damage"]]
                        victim_indices = dh_arg[human_attackers]
                        victims = h_slots[victim_indices]
                        for k in range(human_attackers.numel()):
                            c_slot = int(cidx[human_attackers[k]])
                            v_slot = int(victims[k])
                            dmg = float(damage[k])
                            c_type = int(m[c_slot, cfg.M_TYPE])
                            sp_name = LEGACY_NAMES.get(c_type, f"type_{c_type}")
                            c_uid = None
                            if hasattr(engine, "_entity_uid_by_slot") and 0 <= c_slot < len(engine._entity_uid_by_slot):
                                c_uid = engine._entity_uid_by_slot[c_slot]
                            attackers_by_victim[v_slot].append({
                                "creature_slot": c_slot,
                                "creature_uid": c_uid,
                                "creature_species": sp_name,
                                "creature_species_id": c_type,
                                "damage_requested": dmg,
                            })

                    observer._current_context = {
                        "phase": "kernel_attack",
                        "source": "creature_kernel_attack",
                        "attackers_by_victim": dict(attackers_by_victim),
                        "engine": engine,
                    }
                    try:
                        return orig_attack(engine, cidx, p, col, attacking, use_human, h_slots, dh_arg, a_slots, dp_arg)
                    finally:
                        observer._current_context = None

                self._patched_modules.append((k_mod, "_attack", orig_attack))
                setattr(k_mod, "_attack", wrapped_attack)
                break

        # 3. Patch instinct_die to catch non-HP old age deaths
        for mod_name in ("instincts_and_tools", "at_the_beginning.instincts_and_tools"):
            iat_mod = sys.modules.get(mod_name)
            if iat_mod is not None and hasattr(iat_mod, "instinct_die"):
                orig_die = getattr(iat_mod, "instinct_die")

                def wrapped_die(ctx: dict, h_tensor: torch.Tensor, pop_count_ref: list, **kw):
                    h_mask = ctx.get("h_mask")
                    if h_mask is not None and bool(h_mask.any()):
                        dead = h_mask & (h_tensor[:, cfg.H_AGE] > h_tensor[:, cfg.H_LIFE_EXP])
                        if bool(dead.any()):
                            for s in torch.where(dead)[0].tolist():
                                observer.record_old_age_death(s)
                    return orig_die(ctx, h_tensor, pop_count_ref, **kw)

                self._patched_modules.append((iat_mod, "instinct_die", orig_die))
                setattr(iat_mod, "instinct_die", wrapped_die)

                # Also patch engine._registry entry if engine is loaded
                if self.engine is not None and hasattr(self.engine, "_registry"):
                    for entry in self.engine._registry:
                        if entry.get("fn") is orig_die:
                            self._patched_registry_entries.append((entry, orig_die))
                            entry["fn"] = wrapped_die
                break

        self._installed = True

    def uninstall(self) -> None:
        """Restore all original functions and callbacks bit-for-bit."""
        if not self._installed:
            return

        for entry, orig_fn in self._patched_registry_entries:
            entry["fn"] = orig_fn
        self._patched_registry_entries.clear()

        for mod, attr, orig_fn in reversed(self._patched_modules):
            try:
                setattr(mod, attr, orig_fn)
            except Exception:
                pass
        self._patched_modules.clear()

        self._installed = False

    def __enter__(self) -> AttributionObserver:
        self.install()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.uninstall()
