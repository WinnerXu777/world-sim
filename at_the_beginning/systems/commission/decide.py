"""The commission decision: legal options from facts, rules scoring, and the transition the outcome selects."""
from systems.decision.contract import DecisionOption, DecisionRequest
from systems.decision.providers import RulesDecisionProvider

from . import lifecycle
from .facts import commission_facts

TOPIC = "commission"

OPTION_DESCRIPTIONS = {
    "accept_commission": "Accept the commission and reserve the materials and payment.",
    "refuse_no_materials": "Refuse: the smithy does not have the iron or wood for this.",
    "refuse_no_forge": "Refuse: the forge is missing or wrecked.",
    "refuse_cannot_afford": "Refuse: the customer cannot pay the price.",
    "refuse_busy": "Refuse: too many open orders already.",
    "refuse_distrust": "Refuse: the smith does not trust this customer.",
}
REFUSAL_REASONS = {"refuse_no_materials": "no_materials", "refuse_no_forge": "no_forge", "refuse_cannot_afford": "cannot_afford",
                   "refuse_busy": "busy", "refuse_distrust": "distrust"}


def legal_options(facts):
    """Option ids that are true given the facts. A refusal can therefore never state a false reason."""
    refusals = []
    if not facts["forge_available"]:
        refusals.append("refuse_no_forge")
    if facts["missing"] or not facts["recipe_known"]:
        refusals.append("refuse_no_materials")
    if not facts["can_afford"]:
        refusals.append("refuse_cannot_afford")
    if facts["open_orders"] >= facts["capacity"]:
        refusals.append("refuse_busy")
    can_accept = not refusals and facts["smith_alive"]
    options = ["accept_commission"] if can_accept else []
    if facts["distrust"]:
        refusals.append("refuse_distrust")
    options += refusals
    return options or ["refuse_busy"]  # unreachable in practice: an order is never created for a dead smith


def build_state(facts):
    return {"closeness": facts["closeness"], "rival": facts["rival"], "traits": facts["traits"], "pressures": facts["pressures"],
            "price": facts["price"], "open_orders": facts["open_orders"], "capacity": facts["capacity"],
            "missing": [m["item_kind"] for m in facts["missing"]], "forge_available": facts["forge_available"]}


BASE_REFUSAL_SCORE = {"refuse_no_forge": 3.0, "refuse_no_materials": 2.5, "refuse_cannot_afford": 2.0, "refuse_busy": 1.5}


def commission_scorer(request):
    """Placeholder weights (1006_smith_loop_design.md 3.3), tuned later from logged runs."""
    state = request.state
    closeness = float(state.get("closeness", 0.0))
    traits = state.get("traits", {})
    pressures = state.get("pressures", {})
    greed = float(traits.get("greed", 0.5))
    discipline = float(traits.get("discipline", 0.5))
    security = float(pressures.get("security", 0.0))
    vengeance = float(pressures.get("vengeance", 0.0))
    scores = {
        "accept_commission": 1.0 + 1.2 * closeness + 0.6 * (greed - 0.5) + 0.4 * (discipline - 0.5) - 0.3 * security,
        "refuse_distrust": 0.4 + 1.0 * vengeance - 0.8 * closeness + (1.0 if state.get("rival") else 0.0),
    }
    scores.update(BASE_REFUSAL_SCORE)
    return scores


def make_rules_provider():
    provider = RulesDecisionProvider()
    provider.register_scorer(TOPIC, commission_scorer)
    return provider


def build_request(ctx, order, facts, options):
    ids = legal_options(facts) if options is None else options
    return DecisionRequest(job_id=f"{order['order_id']}:decide", resident_id=order["smith_id"], world_epoch=ctx.world_epoch,
                           state_revision=order["revision"], tick=ctx.tick, trigger=f"commission_request:{order['order_id']}",
                           question_kind="choice", topic=TOPIC, state=build_state(facts), priority="active",
                           options=tuple(DecisionOption(i, OPTION_DESCRIPTIONS[i], ("commission",)) for i in ids))


def decide_commission(ctx, order, service, env=None):
    """Decide an ``offered`` order. Returns the outcome with a ``code`` the line chooser maps to wording."""
    if order["state"] != "offered":
        return {"ok": False, "reason": "invalid_transition", "state": order["state"], "order_id": order["order_id"]}
    facts = commission_facts(ctx, order, env)
    request = build_request(ctx, order, facts, None)
    result = service.decide(request)
    if not service.apply_if_fresh(request, result, world_epoch=ctx.world_epoch, state_revision=order["revision"]):
        return {"ok": False, "reason": "stale_decision", "state": order["state"], "order_id": order["order_id"]}
    chosen = result.top_option
    outcome = {"order_id": order["order_id"], "decision": chosen, "provider_mode": result.provider_mode,
               "probabilities": result.probabilities}
    if chosen == "accept_commission":
        lifecycle.accept_order(ctx, order)
        reserved = lifecycle.reserve_inputs(ctx, order)
        if reserved.get("state") == "reserved":
            service.log.record_outcome(request.job_id, "accepted", order_id=order["order_id"])
            return {**outcome, "ok": True, "state": "reserved", "code": "accepted"}
        if reserved.get("state") == "awaiting_materials":
            return {**outcome, "ok": True, "state": "awaiting_materials", "code": "accepted_waiting"}
        return {**outcome, "ok": True, "state": order["state"], "code": f"refused_{reserved.get('reason', 'no_materials')}"}
    reason = REFUSAL_REASONS[chosen]
    lifecycle.refuse_order(ctx, order, reason)
    service.log.record_outcome(request.job_id, f"refused_{reason}", order_id=order["order_id"])
    return {**outcome, "ok": True, "state": "refused", "code": f"refused_{reason}"}


def submit_request(ctx, customer_id, smith_id, recipe_id, service, command_id=None, env=None):
    """create_order + decide_commission in one call: what a /commission/request executor runs at drain time."""
    created = lifecycle.create_order(ctx, customer_id, smith_id, recipe_id, command_id, env)
    if not created.get("ok"):
        return {**created, "code": f"refused_{created['reason']}"}
    if created.get("duplicate_open_order") or created.get("duplicate_command"):
        return {**created, "code": "duplicate_open_order"}
    from .orders import get_order
    order = get_order(ctx, created["order_id"])
    return decide_commission(ctx, order, service, env)
