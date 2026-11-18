from __future__ import annotations

"""Declarative task kinds for resident activity execution."""

from typing import Final


def _task_kind(
    label: str,
    *,
    family: str,
    default_priority: float,
    interruptible: bool = True,
    notes: str = "",
) -> dict[str, object]:
    return {
        "label": str(label),
        "family": str(family),
        "default_priority": round(max(0.0, min(1.0, float(default_priority))), 3),
        "interruptible": bool(interruptible),
        "notes": str(notes or ""),
    }


TASK_KIND_DEFS: Final[dict[str, dict[str, object]]] = {
    "idle": _task_kind(
        "Idle",
        family="baseline",
        default_priority=0.1,
        notes="Fallback when nothing more concrete is queued.",
    ),
    "move_to_place": _task_kind(
        "Move To Place",
        family="movement",
        default_priority=0.35,
        notes="Approach a worksite, home, resource, or target point.",
    ),
    "approach_target": _task_kind(
        "Approach Target",
        family="movement",
        default_priority=0.44,
        notes="Close distance to a human or entity target for social, strategic, or combat follow-through.",
    ),
    "follow_target": _task_kind(
        "Follow Target",
        family="movement",
        default_priority=0.33,
        notes="Stay near a moving human target for escort or observation.",
    ),
    "return_home": _task_kind(
        "Return Home",
        family="movement",
        default_priority=0.42,
        notes="Return to a home anchor or safe household area.",
    ),
    "gather_material": _task_kind(
        "Gather Material",
        family="gather",
        default_priority=0.6,
        notes="Collect raw materials such as wood, fiber, stone, or herbs.",
    ),
    "withdraw_item": _task_kind(
        "Withdraw Item",
        family="inventory",
        default_priority=0.62,
        notes="Take an item from accessible storage or household inventory.",
    ),
    "store_item": _task_kind(
        "Store Item",
        family="inventory",
        default_priority=0.4,
        notes="Deposit carried items into a nearby container or stockpile.",
    ),
    "craft_item": _task_kind(
        "Craft Item",
        family="crafting",
        default_priority=0.68,
        notes="Craft a tool, weapon, component, or consumable.",
    ),
    "ensure_required_tool": _task_kind(
        "Ensure Required Tool",
        family="crafting",
        default_priority=0.72,
        notes="High-level occupation provisioning task that expands into withdraw, gather, and craft steps.",
    ),
    "equip_item": _task_kind(
        "Equip Item",
        family="inventory",
        default_priority=0.55,
        notes="Put a carried tool or weapon into the active equipment slot.",
    ),
    "fish_work": _task_kind(
        "Fish Work",
        family="occupation_work",
        default_priority=0.56,
        notes="Ordinary shoreline or water-adjacent fishing work.",
    ),
    "chop_wood": _task_kind(
        "Chop Wood",
        family="occupation_work",
        default_priority=0.56,
        notes="Cut or gather wood as baseline labor.",
    ),
    "farm_work": _task_kind(
        "Farm Work",
        family="occupation_work",
        default_priority=0.54,
        notes="Ordinary farming and field labor.",
    ),
    "gather_work": _task_kind(
        "Gather Work",
        family="occupation_work",
        default_priority=0.52,
        notes="Ordinary gathering work for herbs, fiber, or misc wild goods.",
    ),
    "build_work": _task_kind(
        "Build Work",
        family="occupation_work",
        default_priority=0.53,
        notes="Builder work that turns materials into useful construction components.",
    ),
    "designate_build_site": _task_kind(
        "Designate Build Site",
        family="construction",
        default_priority=0.58,
        notes="Choose and stamp a concrete site for an active building project.",
    ),
    "build_project": _task_kind(
        "Build Project",
        family="construction",
        default_priority=0.64,
        notes="Gather carry materials, move to site, and advance build progress on an active project.",
    ),
    "hunt_work": _task_kind(
        "Hunt Work",
        family="occupation_work",
        default_priority=0.57,
        notes="Ordinary hunting work in wild areas with a simple tool loadout.",
    ),
    "heal_work": _task_kind(
        "Heal Work",
        family="occupation_work",
        default_priority=0.48,
        notes="Healer task for assisting a nearby injured resident.",
    ),
    "trade_run": _task_kind(
        "Trade Run",
        family="occupation_work",
        default_priority=0.45,
        notes="Basic trader route between settlement spaces and storage/value exchange.",
    ),
    "patrol_area": _task_kind(
        "Patrol Area",
        family="occupation_work",
        default_priority=0.5,
        notes="Guard or patrol routine for safe areas and settlements.",
    ),
    "fetch_water": _task_kind(
        "Fetch Water",
        family="survival",
        default_priority=0.88,
        notes="Emergency or ordinary water acquisition task.",
    ),
    "eat_food": _task_kind(
        "Eat Food",
        family="survival",
        default_priority=0.9,
        notes="Emergency or ordinary food acquisition and consumption task.",
    ),
    "sleep": _task_kind(
        "Sleep",
        family="survival",
        default_priority=0.52,
        notes="Rest or sleep task anchored to home or shelter.",
    ),
    "seek_shelter": _task_kind(
        "Seek Shelter",
        family="survival",
        default_priority=0.86,
        notes="Move to the nearest safe shelter or settlement anchor.",
    ),
    "socialize": _task_kind(
        "Socialize",
        family="social",
        default_priority=0.28,
        notes="Ordinary low-stakes nearby social behavior.",
    ),
    "talk_to_target": _task_kind(
        "Talk To Target",
        family="social",
        default_priority=0.46,
        notes="Short directed talk task for human-mode interaction.",
    ),
    "warn_target": _task_kind(
        "Warn Target",
        family="social",
        default_priority=0.58,
        notes="Approach and warn a nearby resident about threat or danger.",
    ),
    "call_for_help": _task_kind(
        "Call For Help",
        family="social",
        default_priority=0.72,
        notes="Signal nearby allies or bystanders for support during danger.",
    ),
    "help_target": _task_kind(
        "Help Target",
        family="social",
        default_priority=0.56,
        notes="Move to and assist a nearby resident, usually wounded or distressed.",
    ),
    "deliver_item": _task_kind(
        "Deliver Item",
        family="social",
        default_priority=0.43,
        notes="Bring an item to another resident as help, trade, or support.",
    ),
    "escort_target": _task_kind(
        "Escort Target",
        family="social",
        default_priority=0.54,
        notes="Lead a vulnerable resident toward shelter or a safer group anchor.",
    ),
    "return_to_group": _task_kind(
        "Return To Group",
        family="social",
        default_priority=0.36,
        notes="Return from a temporary social excursion to a safe settlement or home anchor.",
    ),
    "thank_helper": _task_kind(
        "Thank Helper",
        family="social",
        default_priority=0.32,
        notes="Offer short gratitude after being helped or healed.",
    ),
    "comfort_target": _task_kind(
        "Comfort Target",
        family="social",
        default_priority=0.41,
        notes="Stay near and reassure a distressed resident after danger or injury.",
    ),
    "report_crime": _task_kind(
        "Report Crime",
        family="social",
        default_priority=0.63,
        notes="Approach a guard or nearby authority figure and report a witnessed threat or theft.",
    ),
    "challenge_target": _task_kind(
        "Challenge Target",
        family="social",
        default_priority=0.66,
        notes="Confront a resident verbally before escalating into combat or dismissal.",
    ),
    "seek_mate": _task_kind(
        "Seek Mate",
        family="social",
        default_priority=0.34,
        notes="Approach a compatible nearby mate candidate when routine and safety allow it.",
    ),
    "mate_with_target": _task_kind(
        "Mate With Target",
        family="social",
        default_priority=0.38,
        notes="Complete a nearby mating interaction once both residents are compatible and close enough.",
    ),
    "attack_target": _task_kind(
        "Attack Target",
        family="combat",
        default_priority=0.95,
        interruptible=False,
        notes="Immediate hostile attack task created by urgent or planned combat.",
    ),
    "chase_target": _task_kind(
        "Chase Target",
        family="combat",
        default_priority=0.83,
        interruptible=False,
        notes="Close on a target that is not yet in attack range.",
    ),
    "retreat_from_target": _task_kind(
        "Retreat From Target",
        family="combat",
        default_priority=0.91,
        interruptible=False,
        notes="Tactical retreat from a dangerous nearby target.",
    ),
    "guard_area": _task_kind(
        "Guard Area",
        family="combat",
        default_priority=0.59,
        notes="Hold and defend a named place while scanning for threats.",
    ),
    "guard_target": _task_kind(
        "Guard Target",
        family="combat",
        default_priority=0.64,
        notes="Stay near and defend a human target such as a healer, trader, or civilian.",
    ),
    "hold_position": _task_kind(
        "Hold Position",
        family="combat",
        default_priority=0.57,
        notes="Hold a tactical position for a short duration without advancing.",
    ),
    "finish_hunt": _task_kind(
        "Finish Hunt",
        family="combat",
        default_priority=0.61,
        notes="Process a downed prey target into carried food after the kill.",
    ),
    "loot_after_kill": _task_kind(
        "Loot After Kill",
        family="combat",
        default_priority=0.52,
        notes="Recover goods from a defeated target when safe to do so.",
    ),
    "protect_target": _task_kind(
        "Protect Target",
        family="combat",
        default_priority=0.74,
        notes="Move to a vulnerable ally and stay ready to intercept nearby threats.",
    ),
    "intercept_target": _task_kind(
        "Intercept Target",
        family="combat",
        default_priority=0.86,
        notes="Close on a threatening target before it reaches a defended resident or place.",
    ),
    "flee_target": _task_kind(
        "Flee Target",
        family="survival",
        default_priority=0.97,
        interruptible=False,
        notes="High-priority flee task when danger overrides ordinary work.",
    ),
    "acquire_weapon": _task_kind(
        "Acquire Weapon",
        family="strategic",
        default_priority=0.64,
        notes="Strategically obtain, craft, or equip a weapon before acting.",
    ),
    "move_to_ambush_point": _task_kind(
        "Move To Ambush Point",
        family="strategic",
        default_priority=0.58,
        notes="Move into a hidden or advantageous position before a planned action.",
    ),
    "wait_in_hiding": _task_kind(
        "Wait In Hiding",
        family="strategic",
        default_priority=0.41,
        notes="Stay quiet and hold position until a strategic condition is met.",
    ),
    "recruit_ally": _task_kind(
        "Recruit Ally",
        family="strategic",
        default_priority=0.5,
        notes="Approach and persuade a nearby resident to support a current plan.",
    ),
    "steal_from_container": _task_kind(
        "Steal From Container",
        family="strategic",
        default_priority=0.57,
        notes="Move to a target container and take a valuable item when safe.",
    ),
    "escape_area": _task_kind(
        "Escape Area",
        family="strategic",
        default_priority=0.72,
        notes="Break contact and reach a safer zone before resuming long-horizon plans.",
    ),
    "scout_area": _task_kind(
        "Scout Area",
        family="strategic",
        default_priority=0.46,
        notes="Move into a target area, observe briefly, and return usable information to memory or planning.",
    ),
    "protect_home": _task_kind(
        "Protect Home",
        family="strategic",
        default_priority=0.61,
        notes="Return to a home anchor and hold a protective posture there.",
    ),
    "gather_food_buffer": _task_kind(
        "Gather Food Buffer",
        family="strategic",
        default_priority=0.58,
        notes="Collect emergency food stores before a longer retreat, siege, or revenge chain.",
    ),
}


TASK_KIND_IDS: Final[tuple[str, ...]] = tuple(sorted(TASK_KIND_DEFS.keys()))
