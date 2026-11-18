"""Commission economy and timing: every tunable number lives in COMMISSION_CONFIG (decision D2)."""
import math

COMMISSION_CONFIG = {
    "recipe_id": "sword",                 # the one recipe commissioned in Stage 1
    "prices": {"sword": 30},              # coin the customer pays, per recipe
    "work_ticks_per_time_unit": 600,      # recipe time_cost 1.5 -> 900 ticks = 45 s at 20 Hz
    "capacity_open_orders": 2,            # open orders one smith will hold
    "forge_wait_ticks": 400,              # how long a broken forge may block work before the order fails (20 s)
    "review_ticks": 40,                   # how often awaiting_materials orders are re-checked
    "waiting_deadline_ticks": 1200,       # awaiting_materials gives up after this
    "wait_for_materials": False,          # Stage 1: refuse instead of waiting
    "cancel_states": ("offered", "accepted", "awaiting_materials", "reserved"),  # decision D6: not once working
    "smith_stock": {"iron_ingot": 4, "wood_bundle": 4},   # roster default stock (D2)
    "smith_personal": {"hammer": 1, "coin": 20},
    "distrust_closeness": -0.2,           # closeness at or below this makes refuse_distrust legal
    "escrow_slots": 32,
    "ready_hold_ticks": 2400,             # a ready, uncollected order keeps the smith at his forge this long (2 min), then he is free again
    "followup_after_ticks": 200,          # a delivered order seen this much later is greeted with followup_delivered (10 s)
}

OPEN_STATES = ("offered", "accepted", "awaiting_materials", "reserved", "working", "ready")
TERMINAL_STATES = ("delivered", "refused", "canceled", "failed")
ALL_STATES = OPEN_STATES + TERMINAL_STATES


def price_for(recipe_id, config=COMMISSION_CONFIG):
    """Coin price of a recipe."""
    return int(config["prices"][recipe_id])


def work_ticks_for(recipe_id, config=COMMISSION_CONFIG):
    """Forging time of a recipe in ticks (its time cost times ``work_ticks_per_time_unit``)."""
    from systems.crafting.resolver import crafting_recipe_def
    return max(1, math.ceil(float(crafting_recipe_def(recipe_id)["time_cost"]) * config["work_ticks_per_time_unit"]))
