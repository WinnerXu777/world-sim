"""Catalog of the 65 resident verbs (Appendix A.2 of 1008implementation.md): data, generated from the tables of 1008_actions.md section 2.

One row per verb. ``tests/test_actions_catalog.py`` fails if this file, the document and Appendix A.2 disagree on the set of ids, or if the
counts, the S1 flags or a registered Action do not match their rows. ``status``: now / glue / new (see the document, section 1).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerbRow:
    id: str
    group: str
    params: str            # human-readable signature from the document (the JSON Schema of a registered Action is generated from its function)
    predicate: str         # legality predicate id (document section 4)
    duration: str          # "instant" or "task"
    interruptible: bool
    risk: str              # reversible / destructive / irreversible
    task_kind: str         # first legacy task kind the verb enqueues (empty: none)
    macro: str             # Tier 1 macro(s) it belongs to
    op: str                # Tier 3 plan op (existing PLAN_OP_DEFS name or proposed new name)
    status: str            # now / glue / new
    s1: bool               # in the first slice (registered Action built in step 4)


CATALOG = (
    VerbRow('eat', 'survival', 'item?:I, place?:P', 'can_eat', 'task', True, 'reversible', 'eat_food', 'eat', 'eat (new op)', 'now', True),
    VerbRow('drink', 'survival', 'place?:P', 'can_drink', 'task', True, 'reversible', 'fetch_water', 'drink', 'drink', 'now', True),
    VerbRow('rest', 'survival', 'until?:{hp|stamina}', 'can_rest', 'task', True, 'reversible', 'sleep', 'rest', 'rest_until_safe, recover_until_hp', 'now', True),
    VerbRow('sleep', 'survival', 'place?:P', 'can_sleep', 'task', True, 'reversible', 'seek_shelter', 'sleep', 'sleep', 'now', True),
    VerbRow('seek_shelter', 'survival', 'place?:P', 'shelter_reachable', 'task', True, 'reversible', 'seek_shelter', 'go_home, hide', 'seek_shelter', 'now', True),
    VerbRow('light_fire', 'survival', 'place:P, fuel?:I', 'can_light_fire', 'task', False, 'reversible', '', 'build', 'light_fire', 'new', False),
    VerbRow('treat_wound', 'survival', 'target?:T, item?:I', 'can_treat', 'task', False, 'reversible', 'help_target', 'help', 'heal_target', 'glue', False),
    VerbRow('flee_to', 'survival', 'place?:P, from?:T', 'can_flee', 'task', True, 'reversible', 'flee_target', 'flee', 'escape_and_hide, flee_to', 'now', True),
    VerbRow('hide', 'survival', 'place?:P', 'can_hide', 'task', True, 'reversible', 'wait_in_hiding', 'hide', 'escape_and_hide', 'now', True),
    VerbRow('go_to_work', 'work', 'place?:P', 'has_work_anchor', 'task', True, 'reversible', 'move_to_place', 'work_at_station', 'move_to_place', 'now', True),
    VerbRow('work_shift', 'work', 'ticks?:n', 'can_work', 'task', True, 'reversible', '', 'work_at_station', 'work_shift', 'now', True),
    VerbRow('gather_resource', 'work', 'source:T (entity id), qty?:n', 'resource_reachable', 'task', True, 'reversible', 'gather_material', 'gather', 'gather_food_buffer, gather_resource', 'now', True),
    VerbRow('hunt', 'work', 'target?:T', 'can_hunt', 'task', True, 'reversible', '', 'gather', 'hunt', 'now', False),
    VerbRow('fish', 'work', 'source?:P', 'resource_reachable("fish")', 'task', True, 'reversible', 'fish_work', 'gather', 'fish', 'now', False),
    VerbRow('farm_tend', 'work', 'plot?:P', 'can_farm', 'task', True, 'reversible', 'farm_work', 'gather', 'farm_tend', 'now', False),
    VerbRow('craft', 'work', 'recipe:R, qty?:n', 'recipe_craftable', 'task', True, 'reversible', 'craft_item', 'work_at_station', 'craft', 'now', True),
    VerbRow('repair', 'work', 'target:T', 'can_repair', 'task', False, 'reversible', '', 'repair', 'repair', 'new', False),
    VerbRow('build_structure', 'work', 'kind:I, site?:P', 'can_build', 'task', True, 'reversible', '', 'build', 'build_structure', 'glue', False),
    VerbRow('haul_items', 'work', 'item:I, qty:n, to:P', 'can_haul', 'task', True, 'reversible', '', 'gather', 'haul_items', 'now', False),
    VerbRow('store_item', 'work', 'item:I, qty?:n, container?:T', 'storage_reachable', 'task', True, 'reversible', 'store_item', 'work_at_station', 'store_item', 'now', True),
    VerbRow('fetch_item', 'work', 'item:I, qty?:n, container?:T', 'item_in_storage', 'task', True, 'reversible', 'withdraw_item', 'work_at_station', 'fetch_item', 'now', True),
    VerbRow('offer_trade', 'economy', 'T, give:I, want:I, give_qty?:n, want_qty?:n', 'can_trade', 'instant', True, 'reversible', '', 'trade', 'offer_trade', 'glue', True),
    VerbRow('accept_trade', 'economy', 'offer:id', 'offer_open', 'instant', True, 'reversible', '', 'trade', 'accept_trade', 'glue', True),
    VerbRow('request_item', 'economy', 'T, item:I, qty?:n', 'can_request', 'task', False, 'reversible', '', 'trade, ask_for_help', 'request_item', 'glue', True),
    VerbRow('give_item', 'economy', 'T, item:I, qty?:n', 'can_give', 'task', False, 'reversible', 'deliver_item', 'help, trade', 'give_item', 'now', True),
    VerbRow('buy', 'economy', 'T, item:I, qty:n', 'can_buy', 'instant', True, 'reversible', '', 'trade', 'buy', 'new', False),
    VerbRow('sell', 'economy', 'T, item:I, qty:n', 'can_sell', 'instant', True, 'reversible', '', 'trade', 'sell', 'new', False),
    VerbRow('set_price', 'economy', 'item:I, price:n', 'owns_shop', 'instant', True, 'reversible', '', 'trade', 'set_price', 'new', False),
    VerbRow('commission_item', 'economy', 'T, recipe:R', 'can_commission', 'task', False, 'reversible', '', 'trade', 'commission_item', 'now', True),
    VerbRow('pay_debt', 'economy', 'T, n', 'has_debt', 'instant', True, 'reversible', '', 'trade', 'pay_debt', 'new', False),
    VerbRow('greet', 'social', 'T', 'can_talk', 'task', True, 'reversible', 'talk_to_target', 'socialise', 'greet', 'now', True),
    VerbRow('chat', 'social', 'T?, topic?:str', 'can_talk', 'task', True, 'reversible', '', 'socialise', 'chat', 'now', True),
    VerbRow('ask_for_help', 'social', 'T?', 'can_call_help', 'task', True, 'reversible', 'call_for_help', 'ask_for_help', 'recruit_allies', 'now', True),
    VerbRow('comfort', 'social', 'T', 'can_comfort', 'task', True, 'reversible', 'comfort_target', 'help', 'comfort', 'now', True),
    VerbRow('teach', 'social', 'T, skill:str', 'can_teach', 'task', False, 'reversible', '', 'socialise', 'teach', 'new', False),
    VerbRow('share_news', 'social', 'T, event:id', 'knows_event', 'task', False, 'reversible', '', 'socialise', 'share_news', 'glue', True),
    VerbRow('gossip', 'social', 'T, about:T', 'knows_event', 'task', False, 'reversible', '', 'socialise', 'gossip', 'glue', True),
    VerbRow('court', 'social', 'T', 'can_court', 'task', False, 'reversible', '', 'socialise', 'court', 'glue', False),
    VerbRow('befriend', 'social', 'T', 'can_talk', 'task', False, 'reversible', '', 'socialise', 'befriend', 'glue', False),
    VerbRow('apologise', 'social', 'T, event?:id', 'has_harmed(T)', 'task', False, 'reversible', '', 'socialise', 'apologise', 'glue', False),
    VerbRow('forgive', 'social', 'T', 'has_grudge(T)', 'instant', True, 'reversible', '', 'socialise', 'forgive', 'glue', False),
    VerbRow('follow', 'social', 'T', 'target_reachable', 'task', True, 'reversible', 'follow_target', 'socialise', 'move_to_target, follow', 'now', True),
    VerbRow('invite', 'social', 'T, place:P', 'can_talk', 'task', False, 'reversible', '', 'socialise', 'invite', 'new', False),
    VerbRow('ask_directions', 'social', 'T, place:str', 'can_talk', 'task', False, 'reversible', '', 'socialise', 'ask_directions', 'new', False),
    VerbRow('warn', 'conflict', 'T', 'can_talk', 'task', True, 'reversible', 'warn_target', 'avoid, defend', 'warn', 'now', True),
    VerbRow('threaten', 'conflict', 'T', 'can_talk', 'task', False, 'reversible', '', 'defend', 'threaten', 'glue', False),
    VerbRow('defend', 'conflict', 'T?, place?:P', 'can_defend', 'task', True, 'reversible', '', 'defend', 'guard_place', 'now', False),
    VerbRow('attack', 'conflict', 'T', 'can_attack', 'task', True, 'destructive', 'attack_target', 'attack', 'attack_target_when_close', 'now', True),
    VerbRow('arrest_or_restrain', 'conflict', 'T', 'holds_authority', 'task', False, 'destructive', '', 'defend', 'arrest', 'new', False),
    VerbRow('steal_when_safe', 'conflict', 'T or container:T, item:I, qty?:n', 'can_steal', 'instant', False, 'destructive', '', 'attack', 'steal_from_target_when_safe', 'now', True),
    VerbRow('report_crime', 'conflict', 'T, about:T', 'witnessed_crime', 'task', True, 'reversible', 'report_crime', 'ask_for_help', 'report_crime', 'now', False),
    VerbRow('avoid', 'conflict', 'T', 'target_in_perception', 'task', True, 'reversible', 'retreat_from_target', 'avoid', 'avoid_target', 'now', True),
    VerbRow('retaliate', 'conflict', 'T', 'can_attack', 'task', True, 'destructive', '', 'attack', 'retaliate', 'now', False),
    VerbRow('explore_toward', 'exploration', 'heading?:{N,NE,...} or P', 'can_move', 'task', True, 'reversible', 'move_to_place', 'explore', 'move_to_place', 'now', True),
    VerbRow('scout_region', 'exploration', 'P?', 'can_move', 'task', True, 'reversible', 'scout_area', 'explore', 'observe_target, scout_region', 'now', False),
    VerbRow('mark_place', 'exploration', 'name:str', 'can_move', 'instant', True, 'reversible', '', 'explore', 'mark_place', 'new', False),
    VerbRow('remember_place', 'exploration', 'P', 'perceives(P)', 'instant', True, 'reversible', '', 'explore', 'remember_place', 'new', False),
    VerbRow('lead_group_to', 'exploration', 'P, members:[T]', 'leads_group', 'task', False, 'reversible', '', 'explore', 'lead_group_to', 'glue', False),
    VerbRow('migrate_group', 'exploration', 'P', 'leads_group', 'task', False, 'reversible', '', 'explore', 'migrate_group', 'new', False),
    VerbRow('settle_site', 'exploration', 'P', 'can_build', 'task', False, 'reversible', '', 'build', 'settle_site', 'new', False),
    VerbRow('USE_BRAIN', 'cognitive', 'reason?:str', 'can_think', 'instant', True, 'reversible', '', 'USE_BRAIN', '-', 'now', False),
    VerbRow('REPLAN', 'cognitive', 'reason?:str', 'plan_exists', 'instant', True, 'reversible', '', 'REPLAN', '-', 'now', False),
    VerbRow('PLOT', 'cognitive', 'target?:T', 'has_plot_motive', 'instant', True, 'destructive', '', 'PLOT', 'plan kinds ambush, revenge, theft', 'now', False),
    VerbRow('reflect', 'cognitive', '-', 'can_think', 'task', False, 'reversible', '', 'USE_BRAIN', 'reflect', 'new', False),
    VerbRow('continue_plan_step', 'cognitive', '-', 'plan_active', 'instant', True, 'reversible', '', 'continue_plan_step', '-', 'now', False),
)

# D-005: the old frontier tools are frozen. They are not in the catalog and no tier may name them in a call or a plan; every entry point answers
# ``legacy_frozen`` (runner, plan adapter, Tier 3 gate). Not deleted, not used.
FROZEN_LEGACY = frozenset({"instinct_frontier_expand", "tool_expand_world_edge"})

BY_ID = {row.id: row for row in CATALOG}
S1 = tuple(row.id for row in CATALOG if row.s1)


def counts() -> dict:
    out: dict = {"total": len(CATALOG)}
    for row in CATALOG:
        out[row.status] = out.get(row.status, 0) + 1
    return out
