"""Work-order lifecycle on plain dicts (no engine): every transition, duplicates, rollback, conservation, persistence."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.commission import (COMMISSION_CONFIG, CommissionContext, accept_order, advance_work, cancel_order, commission_facts,
                                complete_work, create_order, decide_commission, deliver_order, fail_order, get_order,
                                legal_options, make_rules_provider, open_orders, refuse_order, reserve_inputs, review_orders,
                                start_work, submit_request)
from systems.commission.escrow import escrow_contents, escrow_record, human_inventory
from systems.decision import DecisionService
from systems.inventory.currency import inventory_balance
from systems.inventory.ops import add_item
from systems.inventory.queries import total_quantity

SMITH, CUSTOMER = "h_smith", "h_player"
WORK = COMMISSION_CONFIG["prices"]["sword"]


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, order, state):
        self.events.append((order["order_id"], state))


def make_ctx(iron=4, wood=4, coin=100, customer_capacity=12, tick=0, **config):
    state = {}
    recorder = Recorder()
    ctx = CommissionContext(state=state, tick=tick, world_epoch="E1", sink=recorder, config={**COMMISSION_CONFIG, **config})
    smith = human_inventory(ctx, SMITH)
    smith["capacity_slots"], smith["capacity_weight"] = 20, None
    add_item(smith, "hammer", 1)
    if iron:
        add_item(smith, "iron_ingot", iron)
    if wood:
        add_item(smith, "wood_bundle", wood)
    customer = human_inventory(ctx, CUSTOMER)
    customer["capacity_slots"], customer["capacity_weight"] = customer_capacity, 28.0
    if coin:
        add_item(customer, "coin", coin)
    return ctx, recorder


def world_totals(ctx):
    """Sum of every kind across every inventory in the state: the conservation check."""
    totals = {}
    for record in ctx.state["inventories"].values():
        for item in record["items"]:
            totals[item["kind"]] = totals.get(item["kind"], 0) + item["quantity"]
    return totals


def new_reserved(ctx):
    order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c1")["order_id"])
    accept_order(ctx, order)
    assert reserve_inputs(ctx, order)["state"] == "reserved"
    return order


def run_to_ready(ctx, order):
    start_work(ctx, order)
    for _ in range(order["work_ticks"]):
        result = advance_work(ctx, order)
    return result


class CreateTests(unittest.TestCase):
    def test_create_opens_an_offered_order_with_a_persisted_counter(self):
        ctx, rec = make_ctx()
        result = create_order(ctx, CUSTOMER, SMITH, "sword", "c1")
        order = get_order(ctx, result["order_id"])
        self.assertEqual((result["ok"], order["state"], order["order_id"], order["price"], order["work_ticks"]), (True, "offered", "o_000001", 30, 900))
        self.assertEqual(ctx.state["work_orders"]["next_order_uid"], 2)
        self.assertEqual(rec.events, [("o_000001", "offered")])

    def test_duplicate_open_order_and_duplicate_command_return_the_same_order(self):
        ctx, _ = make_ctx()
        first = create_order(ctx, CUSTOMER, SMITH, "sword", "c1")
        again = create_order(ctx, CUSTOMER, SMITH, "sword", "c2")
        self.assertEqual((again["order_id"], again["duplicate_open_order"]), (first["order_id"], True))
        self.assertEqual(len(ctx.state["work_orders"]["orders"]), 1)
        refused = get_order(ctx, first["order_id"])
        refuse_order(ctx, refused, "busy")
        reused = create_order(ctx, CUSTOMER, SMITH, "sword", "c1")  # same command id after the order closed
        self.assertEqual((reused["order_id"], reused["duplicate_command"]), (first["order_id"], True))
        self.assertEqual(len(ctx.state["work_orders"]["orders"]), 1)
        fresh = create_order(ctx, CUSTOMER, SMITH, "sword", "c9")  # a genuinely new request opens a new order
        self.assertEqual(fresh["order_id"], "o_000002")

    def test_invalid_requests(self):
        ctx, _ = make_ctx()
        self.assertEqual(create_order(ctx, CUSTOMER, SMITH, "pie")["reason"], "unknown_recipe")
        self.assertEqual(create_order(ctx, SMITH, SMITH, "sword")["reason"], "cannot_commission_yourself")
        self.assertEqual(create_order(ctx, CUSTOMER, SMITH, "sword", env={"smith_alive": False})["reason"], "smith_unavailable")
        self.assertEqual(ctx.state.get("work_orders", {}).get("orders", {}), {})

    def test_the_order_counter_survives_a_json_round_trip(self):
        ctx, _ = make_ctx()
        create_order(ctx, CUSTOMER, SMITH, "sword", "c1")
        restored = CommissionContext(state=json.loads(json.dumps(ctx.state)), world_epoch="E2")
        create_order(restored, CUSTOMER, SMITH, "sword", "c2", env={})  # the first is still open -> duplicate, not a new id
        self.assertEqual(len(restored.state["work_orders"]["orders"]), 1)
        refuse_order(restored, get_order(restored, "o_000001"), "busy")
        self.assertEqual(create_order(restored, CUSTOMER, SMITH, "sword", "c3")["order_id"], "o_000002")


class ReserveTests(unittest.TestCase):
    def test_reserve_moves_materials_and_price_into_escrow(self):
        ctx, rec = make_ctx()
        order = new_reserved(ctx)
        self.assertEqual(escrow_contents(ctx, order), {"iron_ingot": 2, "wood_bundle": 1, "coin": 30})
        self.assertEqual(total_quantity(human_inventory(ctx, SMITH), "iron_ingot"), 2)
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 70)
        self.assertEqual((order["state"], order["revision"]), ("reserved", 3))
        self.assertEqual([s for _, s in rec.events], ["offered", "accepted", "reserved"])

    def test_shortfall_refuses_with_nothing_moved(self):
        for kwargs, reason in (({"iron": 1}, "no_materials"), ({"wood": 0}, "no_materials"), ({"coin": 29}, "cannot_afford")):
            with self.subTest(reason=reason):
                ctx, _ = make_ctx(**kwargs)
                before = world_totals(ctx)
                order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
                accept_order(ctx, order)
                result = reserve_inputs(ctx, order)
                self.assertEqual((result["ok"], result["reason"], order["state"]), (False, reason, "refused"))
                self.assertEqual(world_totals(ctx), before)
                self.assertNotIn(f"work_order:{order['order_id']}", ctx.state["inventories"])

    def test_partial_failure_rolls_everything_back(self):
        ctx, _ = make_ctx()
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        accept_order(ctx, order)
        escrow_record(ctx, order)["capacity_slots"] = 2  # iron and wood fit, the coin stack does not
        before = copy.deepcopy(ctx.state["inventories"])
        result = reserve_inputs(ctx, order)
        self.assertFalse(result["ok"])
        after = ctx.state["inventories"]
        self.assertEqual(world_totals(ctx), {k: v for k, v in world_totals(ctx).items()})
        self.assertEqual({k: [i["quantity"] for i in v["items"]] for k, v in after.items() if not k.startswith("work_order")},
                         {k: [i["quantity"] for i in v["items"]] for k, v in before.items() if not k.startswith("work_order")})

    def test_double_reserve_is_an_invalid_transition_and_moves_nothing(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        before = world_totals(ctx)
        again = reserve_inputs(ctx, order)
        self.assertEqual((again["ok"], again["reason"]), (False, "invalid_transition"))
        self.assertEqual(world_totals(ctx), before)
        self.assertEqual(escrow_contents(ctx, order)["iron_ingot"], 2)

    def test_waiting_policy_and_review(self):
        ctx, rec = make_ctx(iron=0, wait_for_materials=True)
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        accept_order(ctx, order)
        result = reserve_inputs(ctx, order)
        self.assertEqual((result["ok"], order["state"], order["blocked_reason"]), (False, "awaiting_materials", "no_materials"))
        self.assertEqual(escrow_contents(ctx, order), {})
        ctx.tick = 40
        self.assertEqual(review_orders(ctx), [])
        add_item(human_inventory(ctx, SMITH), "iron_ingot", 2)  # iron arrives (e.g. god power)
        ctx.tick = 80
        self.assertEqual(review_orders(ctx), [order["order_id"]])
        self.assertEqual(order["state"], "reserved")
        self.assertEqual(escrow_contents(ctx, order)["iron_ingot"], 2)

    def test_waiting_order_fails_after_its_deadline_with_nothing_held(self):
        ctx, rec = make_ctx(iron=0, wait_for_materials=True)
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        accept_order(ctx, order)
        reserve_inputs(ctx, order)
        ctx.tick = order["deadline_tick"]
        self.assertEqual(review_orders(ctx), [order["order_id"]])
        self.assertEqual((order["state"], order["failure_reason"]), ("failed", "no_materials"))
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 100)

    def test_stock_removed_while_waiting_is_a_clean_failure(self):
        ctx, _ = make_ctx(wait_for_materials=True)
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        accept_order(ctx, order)
        smith = human_inventory(ctx, SMITH)
        smith["items"] = [i for i in smith["items"] if i["kind"] != "iron_ingot"]  # removed between accept and reserve
        reserve_inputs(ctx, order)
        self.assertEqual(order["state"], "awaiting_materials")
        ctx.tick = order["deadline_tick"] + 1
        review_orders(ctx)
        self.assertEqual(order["state"], "failed")
        self.assertEqual(world_totals(ctx)["coin"], 100)


class WorkTests(unittest.TestCase):
    def test_full_happy_path_conserves_everything_and_creates_one_sword(self):
        ctx, rec = make_ctx()
        start = world_totals(ctx)
        order = new_reserved(ctx)
        result = run_to_ready(ctx, order)
        self.assertEqual((result["state"], order["state"], order["consumed"], order["progress_ticks"]), ("ready", "ready", True, 900))
        self.assertEqual(escrow_contents(ctx, order), {"sword": 1, "coin": 30})
        delivered = deliver_order(ctx, order, CUSTOMER)
        self.assertEqual((delivered["ok"], order["state"], order["settled"]), (True, "delivered", True))
        end = world_totals(ctx)
        self.assertEqual(end["sword"], 1)
        self.assertEqual((end["iron_ingot"], end["wood_bundle"]), (start["iron_ingot"] - 2, start["wood_bundle"] - 1))
        self.assertEqual(end["coin"], start["coin"])  # coin only moved, customer -> smith
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 70)
        self.assertEqual(inventory_balance(human_inventory(ctx, SMITH)), 30)
        self.assertEqual(total_quantity(human_inventory(ctx, CUSTOMER), "sword"), 1)
        self.assertEqual(escrow_contents(ctx, order), {})
        self.assertEqual([s for _, s in rec.events], ["offered", "accepted", "reserved", "working", "ready", "delivered"])

    def test_progress_only_at_the_station_and_is_counted_in_ticks(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        for _ in range(10):
            advance_work(ctx, order)
        away = advance_work(ctx, order, {"smith_at_work": False})
        self.assertEqual((away["progressed"], away["blocked"], order["progress_ticks"]), (False, "smith_away", 10))
        for _ in range(5):
            advance_work(ctx, order, {"smith_at_work": False})
        self.assertEqual(order["progress_ticks"], 10)
        advance_work(ctx, order)
        self.assertEqual(order["progress_ticks"], 11)

    def test_start_work_requires_reserved_and_advance_requires_working(self):
        ctx, _ = make_ctx()
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        self.assertEqual(start_work(ctx, order)["reason"], "invalid_transition")
        self.assertEqual(advance_work(ctx, order)["reason"], "invalid_transition")
        self.assertEqual(complete_work(ctx, order)["reason"], "invalid_transition")

    def test_complete_before_the_work_is_done_is_refused(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        self.assertEqual(complete_work(ctx, order)["reason"], "work_incomplete")
        self.assertEqual(order["state"], "working")

    def test_complete_rolls_back_when_the_output_does_not_fit(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        order["progress_ticks"] = order["work_ticks"]
        start_work(ctx, order)
        record = escrow_record(ctx, order)
        record["capacity_slots"] = 2  # coin stack + iron stack: no room for the sword once the iron is consumed? it frees slots
        record["capacity_weight"] = 0.1
        before = copy.deepcopy(record)
        result = complete_work(ctx, order)
        self.assertEqual((result["ok"], result["reason"], order["state"], order["consumed"]), (False, "capacity", "working", False))
        self.assertEqual(record["items"], before["items"])

    def test_forge_blocked_sets_the_reason_once_then_fails_after_the_wait(self):
        ctx, rec = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        for _ in range(10):
            advance_work(ctx, order)
        ctx.tick = 100
        first = advance_work(ctx, order, {"forge_available": False})
        revision = order["revision"]
        ctx.tick = 150
        second = advance_work(ctx, order, {"forge_available": False})
        self.assertEqual((first["blocked"], second["blocked"], order["blocked_reason"]), ("forge_unavailable",) * 3)
        self.assertEqual(order["revision"], revision)  # set once
        self.assertEqual(order["progress_ticks"], 10)  # paused
        ctx.tick = 100 + COMMISSION_CONFIG["forge_wait_ticks"]
        failed = advance_work(ctx, order, {"forge_available": False})
        self.assertEqual((failed["state"], order["failure_reason"]), ("failed", "forge_unavailable"))
        self.assertEqual(world_totals(ctx)["iron_ingot"], 4)  # materials returned
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 100)  # full refund
        self.assertEqual([s for _, s in rec.events].count("failed"), 1)
        self.assertEqual(advance_work(ctx, order)["reason"], "invalid_transition")  # nothing happens twice

    def test_forge_recovering_resumes_work(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        advance_work(ctx, order, {"forge_available": False})
        self.assertEqual(order["blocked_reason"], "forge_unavailable")
        advance_work(ctx, order)
        self.assertEqual((order["blocked_reason"], order["progress_ticks"]), ("", 1))

    def test_smith_dying_fails_the_order_and_refunds(self):
        ctx, rec = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        result = advance_work(ctx, order, {"smith_alive": False})
        self.assertEqual((result["state"], order["failure_reason"]), ("failed", "smith_unavailable"))
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 100)
        self.assertEqual(total_quantity(human_inventory(ctx, SMITH), "iron_ingot"), 4)


class DeliverTests(unittest.TestCase):
    def ready(self, **kwargs):
        ctx, rec = make_ctx(**kwargs)
        order = new_reserved(ctx)
        run_to_ready(ctx, order)
        return ctx, rec, order

    def test_second_collect_returns_the_stored_receipt_and_moves_nothing(self):
        ctx, rec, order = self.ready()
        first = deliver_order(ctx, order, CUSTOMER)
        before = world_totals(ctx)
        second = deliver_order(ctx, order, CUSTOMER)
        self.assertEqual((second["ok"], second["status"], second["duplicate"]), (True, "already_delivered", True))
        self.assertEqual(second["receipt"], first["receipt"])
        self.assertEqual(world_totals(ctx), before)
        self.assertEqual([s for _, s in rec.events].count("delivered"), 1)

    def test_only_the_customer_collects(self):
        ctx, _, order = self.ready()
        self.assertEqual(deliver_order(ctx, order, "h_other")["reason"], "not_your_order")
        self.assertEqual(order["state"], "ready")

    def test_a_full_pack_keeps_the_order_ready_and_says_why(self):
        ctx, _, order = self.ready(customer_capacity=1)
        result = deliver_order(ctx, order, CUSTOMER)  # the customer's single slot is taken by the remaining coin
        self.assertEqual((result["ok"], result["reason"], order["state"], order["blocked_reason"]), (False, "customer_inventory_full", "ready", "customer_inventory_full"))
        human_inventory(ctx, CUSTOMER)["capacity_slots"] = 5
        self.assertTrue(deliver_order(ctx, order, CUSTOMER)["ok"])
        self.assertEqual(order["blocked_reason"], "")

    def test_interaction_and_liveness_gates(self):
        ctx, _, order = self.ready()
        self.assertEqual(deliver_order(ctx, order, CUSTOMER, {"interaction": {"ok": False, "reason": "blocked"}})["reason"], "blocked")
        self.assertEqual(deliver_order(ctx, order, CUSTOMER, {"interaction": {"ok": False, "reason": ""}})["reason"], "out_of_range")
        self.assertEqual(deliver_order(ctx, order, CUSTOMER, {"customer_alive": False})["reason"], "customer_unavailable")
        self.assertEqual(order["state"], "ready")
        self.assertEqual(escrow_contents(ctx, order), {"sword": 1, "coin": 30})

    def test_cannot_deliver_before_ready(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        self.assertEqual(deliver_order(ctx, order, CUSTOMER)["reason"], "invalid_transition")

    def test_failing_a_ready_order_keeps_the_sword_with_the_smith_and_pays_him_when_the_customer_is_gone(self):
        ctx, _, order = self.ready()
        fail_order(ctx, order, "customer_gone")
        self.assertEqual((total_quantity(human_inventory(ctx, SMITH), "sword"), inventory_balance(human_inventory(ctx, SMITH))), (1, 30))
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 70)
        self.assertEqual(escrow_contents(ctx, order), {})


class CancelTests(unittest.TestCase):
    def test_cancel_in_reserved_refunds_everything_once(self):
        ctx, rec = make_ctx()
        start = world_totals(ctx)
        order = new_reserved(ctx)
        result = cancel_order(ctx, order, "player")
        self.assertEqual((result["ok"], order["state"]), (True, "canceled"))
        self.assertEqual(world_totals(ctx), start)
        self.assertEqual(inventory_balance(human_inventory(ctx, CUSTOMER)), 100)
        self.assertEqual(total_quantity(human_inventory(ctx, SMITH), "iron_ingot"), 4)
        again = cancel_order(ctx, order, "player")
        self.assertEqual(again["reason"], "invalid_transition")
        self.assertEqual(world_totals(ctx), start)
        self.assertEqual([s for _, s in rec.events].count("canceled"), 1)

    def test_cancel_not_allowed_once_working_or_ready_or_delivered(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        start_work(ctx, order)
        self.assertEqual(cancel_order(ctx, order, "player")["reason"], "invalid_transition")
        for _ in range(order["work_ticks"]):
            advance_work(ctx, order)
        self.assertEqual(cancel_order(ctx, order, "player")["reason"], "invalid_transition")
        deliver_order(ctx, order, CUSTOMER)
        self.assertEqual(cancel_order(ctx, order, "player")["reason"], "invalid_transition")
        self.assertEqual(world_totals(ctx)["sword"], 1)

    def test_terminal_orders_cannot_fail_or_be_refused(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        cancel_order(ctx, order, "player")
        self.assertEqual(fail_order(ctx, order, "x")["reason"], "invalid_transition")
        self.assertEqual(refuse_order(ctx, order, "x")["reason"], "invalid_transition")
        self.assertEqual(accept_order(ctx, order)["reason"], "invalid_transition")


class ConsequenceTests(unittest.TestCase):
    def test_every_state_is_committed_once_even_if_a_transition_is_replayed(self):
        ctx, rec = make_ctx()
        order = new_reserved(ctx)
        from systems.commission.lifecycle import commit_consequences
        self.assertFalse(commit_consequences(ctx, order, "reserved"))
        self.assertEqual([s for _, s in rec.events].count("reserved"), 1)
        self.assertEqual(sorted(order["committed"]), ["accepted", "offered", "reserved"])

    def test_a_broken_sink_does_not_undo_the_transition(self):
        ctx, _ = make_ctx()

        def boom(order, state):
            raise RuntimeError("memory store down")
        ctx.sink = boom
        with self.assertLogs("eden.commission", level="ERROR"):
            order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        self.assertEqual(order["state"], "offered")
        self.assertIn("offered", order["committed"])


class DecisionTests(unittest.TestCase):
    def service(self):
        return DecisionService(make_rules_provider())

    def test_accept_path_reserves(self):
        ctx, _ = make_ctx()
        result = submit_request(ctx, CUSTOMER, SMITH, "sword", self.service(), "c1")
        self.assertEqual((result["ok"], result["state"], result["code"], result["decision"]), (True, "reserved", "accepted", "accept_commission"))
        self.assertEqual(escrow_contents(ctx, get_order(ctx, result["order_id"]))["coin"], 30)

    def test_refusals_state_only_true_reasons(self):
        cases = {"no_iron": ({"iron": 0}, {}, "refused_no_materials"), "broke": ({"coin": 5}, {}, "refused_cannot_afford"),
                 "no_forge": ({}, {"forge_available": False}, "refused_no_forge")}
        for label, (kwargs, env, code) in cases.items():
            with self.subTest(label):
                ctx, _ = make_ctx(**kwargs)
                before = world_totals(ctx)
                result = submit_request(ctx, CUSTOMER, SMITH, "sword", self.service(), "c1", env)
                self.assertEqual((result["state"], result["code"]), ("refused", code))
                self.assertEqual(world_totals(ctx), before)
                self.assertEqual(escrow_record_count(ctx), 0)

    def test_busy_when_open_orders_reach_capacity(self):
        ctx, _ = make_ctx(capacity_open_orders=1, iron=8, wood=8)
        other = "h_other"
        add_item(human_inventory(ctx, other), "coin", 50)
        first = submit_request(ctx, other, SMITH, "sword", self.service(), "c0")
        self.assertEqual(first["state"], "reserved")
        second = submit_request(ctx, CUSTOMER, SMITH, "sword", self.service(), "c1")
        self.assertEqual((second["state"], second["code"]), ("refused", "refused_busy"))

    def test_legal_options_follow_the_facts(self):
        ctx, _ = make_ctx(iron=0)
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        facts = commission_facts(ctx, order, {"forge_available": False})
        self.assertEqual(legal_options(facts), ["refuse_no_forge", "refuse_no_materials"])
        ctx2, _ = make_ctx()
        order2 = get_order(ctx2, create_order(ctx2, CUSTOMER, SMITH, "sword", "c")["order_id"])
        self.assertEqual(legal_options(commission_facts(ctx2, order2)), ["accept_commission"])
        self.assertEqual(legal_options(commission_facts(ctx2, order2, {"closeness": -0.5})), ["accept_commission", "refuse_distrust"])

    def test_personality_and_relationship_change_the_outcome(self):
        outcomes = set()
        for closeness, rival in ((0.8, False), (-0.2, False), (-0.5, False), (-0.2, True)):
            ctx, _ = make_ctx()
            result = submit_request(ctx, CUSTOMER, SMITH, "sword", self.service(), "c", {"closeness": closeness, "rival": rival})
            outcomes.add((closeness, rival, result["code"]))
        self.assertEqual(outcomes, {(0.8, False, "accepted"), (-0.2, False, "accepted"), (-0.5, False, "refused_distrust"),
                                    (-0.2, True, "refused_distrust")})

    def test_decisions_are_deterministic(self):
        results = []
        for _ in range(2):
            ctx, _ = make_ctx()
            results.append(submit_request(ctx, CUSTOMER, SMITH, "sword", self.service(), "c", {"closeness": -0.5})["probabilities"])
        self.assertEqual(results[0], results[1])

    def test_duplicate_requests_do_not_double_escrow(self):
        ctx, _ = make_ctx(iron=8, wood=8)
        service = self.service()
        first = submit_request(ctx, CUSTOMER, SMITH, "sword", service, "c1")
        second = submit_request(ctx, CUSTOMER, SMITH, "sword", service, "c2")
        self.assertEqual((second["code"], second["order_id"]), ("duplicate_open_order", first["order_id"]))
        self.assertEqual(escrow_contents(ctx, get_order(ctx, first["order_id"]))["iron_ingot"], 2)
        self.assertEqual(len(open_orders(ctx)), 1)

    def test_stale_decision_changes_nothing(self):
        ctx, _ = make_ctx()
        order = get_order(ctx, create_order(ctx, CUSTOMER, SMITH, "sword", "c")["order_id"])
        service = self.service()
        ctx.world_epoch = "E1"
        original = service.apply_if_fresh
        service.apply_if_fresh = lambda *a, **k: original(*a, **{**k, "world_epoch": "E2"})  # the world moved on
        result = decide_commission(ctx, order, service)
        self.assertEqual((result["ok"], result["reason"], order["state"]), (False, "stale_decision", "offered"))
        self.assertEqual(escrow_record_count(ctx), 0)


def escrow_record_count(ctx):
    return len([k for k in ctx.state["inventories"] if k.startswith("work_order:")])


class PersistenceTests(unittest.TestCase):
    def test_state_round_trips_through_json_at_every_stage(self):
        for stage in ("reserved", "working", "ready", "delivered"):
            with self.subTest(stage=stage):
                ctx, _ = make_ctx()
                order = new_reserved(ctx)
                if stage != "reserved":
                    start_work(ctx, order)
                    for _ in range(300 if stage == "working" else order["work_ticks"]):
                        advance_work(ctx, order)
                if stage == "delivered":
                    deliver_order(ctx, order, CUSTOMER)
                before = world_totals(ctx)
                restored = CommissionContext(state=json.loads(json.dumps(ctx.state)), world_epoch="E2", sink=Recorder(), tick=ctx.tick)
                same = get_order(restored, order["order_id"])
                self.assertEqual(world_totals(restored), before)
                self.assertEqual(same["state"], stage)
                self.assertEqual(same["progress_ticks"], order["progress_ticks"])
                self.assertEqual(sorted(same["committed"]), sorted(order["committed"]))
                if stage == "working":
                    for _ in range(same["work_ticks"] - same["progress_ticks"]):
                        advance_work(restored, same)
                    self.assertEqual(same["state"], "ready")
                    self.assertEqual(world_totals(restored)["sword"], 1)
                if stage in ("working", "ready"):
                    self.assertTrue(deliver_order(restored, same, CUSTOMER)["ok"] if same["state"] == "ready" else True)
                    self.assertEqual(world_totals(restored)["sword"], 1)
                    self.assertEqual(deliver_order(restored, same, CUSTOMER)["status"], "already_delivered")
                if stage == "delivered":
                    self.assertEqual(deliver_order(restored, same, CUSTOMER)["status"], "already_delivered")
                    self.assertEqual(world_totals(restored), before)


if __name__ == "__main__":
    unittest.main()
