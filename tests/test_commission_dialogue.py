"""Scripted dialogue: choice enablement from facts, outcome-driven deterministic lines, the read model."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_commission_orders import CUSTOMER, SMITH, make_ctx, new_reserved, run_to_ready
from systems.commission import (build_choices, cancel_order, choose_line, commission_state, deliver_order, get_order, make_rules_provider,
                                submit_request)
from systems.commission.escrow import human_inventory
from systems.commission.lines import LINES, known_codes
from systems.decision import DecisionService
from systems.inventory.ops import add_item


def service():
    return DecisionService(make_rules_provider())


class LineTests(unittest.TestCase):
    def test_lines_are_deterministic_per_resident_and_order(self):
        for code in known_codes("smith"):
            first = choose_line("smith", code, "h_smith", "o_000001")
            self.assertEqual(first, choose_line("smith", code, "h_smith", "o_000001"))
            self.assertIn(first, LINES["smith"][code])
        variants = {choose_line("smith", "accepted", "h_smith", f"o_{n:06d}") for n in range(60)}
        self.assertEqual(variants, set(LINES["smith"]["accepted"]))  # all variants reachable, selected by order id

    def test_refusal_lines_state_the_true_reason(self):
        for code, words in (("refused_no_materials", ("iron", "stock")), ("refused_no_forge", ("forge",)),
                            ("refused_cannot_afford", ("coin", "pay", "afford")), ("refused_busy", ("hands", "orders", "later")),
                            ("refused_distrust", ("not", "another"))):
            for n in range(5):
                line = choose_line("smith", code, "h_smith", f"o_{n:06d}").lower()
                self.assertTrue(any(w in line for w in words), (code, line))

    def test_unknown_codes_fall_back_to_a_generic_line_never_to_a_wrong_one(self):
        self.assertEqual(choose_line("smith", "refused_something_new"), "No.")
        self.assertEqual(choose_line("baker", "accepted"), "Agreed.")
        self.assertEqual(choose_line("smith", "totally_unknown"), "")

    def test_failure_lines_mention_the_refund_or_the_cause(self):
        for code in ("failed_forge_unavailable", "failed_no_materials", "failed_smith_unavailable", "canceled"):
            self.assertIn("returned", choose_line("smith", code, "h", "o").lower())


class ChoiceTests(unittest.TestCase):
    def by_id(self, choices, cid):
        return next((c for c in choices if c["id"] == cid), None)

    def test_request_choice_enablement(self):
        ctx, _ = make_ctx()
        choice = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword"), "request_commission")
        self.assertEqual((choice["enabled"], choice["reason"], choice["label"]), (True, "", "Commission a sword (30 coin)"))
        far = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword", {"interaction": {"ok": False, "reason": "out_of_range"}}), "request_commission")
        self.assertEqual((far["enabled"], far["reason"]), (False, "out_of_range"))
        blocked = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword", {"interaction": {"ok": False, "reason": "blocked"}}), "request_commission")
        self.assertEqual(blocked["reason"], "blocked")
        broke_ctx, _ = make_ctx(coin=10)
        broke = self.by_id(build_choices(broke_ctx, CUSTOMER, SMITH, "sword"), "request_commission")
        self.assertEqual((broke["enabled"], broke["reason"]), (False, "no_funds"))

    def test_open_order_disables_a_second_request_and_offers_cancel(self):
        ctx, _ = make_ctx()
        submit_request(ctx, CUSTOMER, SMITH, "sword", service(), "c1")
        choices = build_choices(ctx, CUSTOMER, SMITH, "sword")
        self.assertEqual(self.by_id(choices, "request_commission")["reason"], "duplicate_open_order")
        self.assertTrue(self.by_id(choices, "cancel_commission")["enabled"])
        self.assertIsNone(self.by_id(choices, "collect_commission"))

    def test_cancel_is_shown_disabled_once_work_has_started(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        from systems.commission import start_work
        start_work(ctx, order)
        cancel = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword"), "cancel_commission")
        self.assertEqual((cancel["enabled"], cancel["reason"]), (False, "work_started"))

    def test_collect_appears_when_ready_and_reports_a_full_pack(self):
        ctx, _ = make_ctx(customer_capacity=1)
        order = new_reserved(ctx)
        run_to_ready(ctx, order)
        collect = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword"), "collect_commission")
        self.assertEqual((collect["enabled"], collect["order_id"]), (True, order["order_id"]))
        deliver_order(ctx, order, CUSTOMER)  # fails: pack full
        collect = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword"), "collect_commission")
        self.assertEqual(collect["reason"], "customer_inventory_full")
        far = self.by_id(build_choices(ctx, CUSTOMER, SMITH, "sword", {"interaction": {"ok": False, "reason": "out_of_range"}}), "collect_commission")
        self.assertFalse(far["enabled"])

    def test_other_customers_orders_are_not_shown_as_yours(self):
        ctx, _ = make_ctx(iron=8, wood=8)
        add_item(human_inventory(ctx, "h_other"), "coin", 50)
        submit_request(ctx, "h_other", SMITH, "sword", service(), "c0")
        choices = build_choices(ctx, CUSTOMER, SMITH, "sword")
        self.assertEqual([c["id"] for c in choices], ["request_commission"])
        self.assertTrue(choices[0]["enabled"])


class ReadModelTests(unittest.TestCase):
    def test_state_shape_and_line_follow_the_latest_outcome(self):
        ctx, _ = make_ctx()
        empty = commission_state(ctx, CUSTOMER, SMITH, "Brann")
        self.assertEqual((empty["npc"], empty["orders"], empty["line"]), ({"id": SMITH, "name": "Brann", "role": "smith"}, [], None))
        submit_request(ctx, CUSTOMER, SMITH, "sword", service(), "c1")
        state = commission_state(ctx, CUSTOMER, SMITH, "Brann")
        order = state["orders"][0]
        self.assertEqual((order["state"], order["recipe"], order["price"], order["progress"]), ("reserved", "sword", 30, 0.0))
        self.assertEqual(state["line"]["code"], "accepted")
        self.assertIn(state["line"]["text"], LINES["smith"]["accepted"])

    def test_refusal_state_reports_the_true_reason_line(self):
        ctx, _ = make_ctx(iron=0)
        submit_request(ctx, CUSTOMER, SMITH, "sword", service(), "c1")
        state = commission_state(ctx, CUSTOMER, SMITH, "Brann")
        self.assertEqual((state["orders"][0]["state"], state["orders"][0]["refusal_reason"], state["line"]["code"]),
                         ("refused", "no_materials", "refused_no_materials"))
        self.assertIn(state["line"]["text"], LINES["smith"]["refused_no_materials"])

    def test_ready_blocked_failed_and_canceled_lines(self):
        ctx, _ = make_ctx(customer_capacity=1)
        order = new_reserved(ctx)
        run_to_ready(ctx, order)
        self.assertEqual(commission_state(ctx, CUSTOMER, SMITH)["line"]["code"], "ready")
        deliver_order(ctx, order, CUSTOMER)
        self.assertEqual(commission_state(ctx, CUSTOMER, SMITH)["line"]["code"], "blocked_customer_inventory_full")
        ctx2, _ = make_ctx()
        order2 = new_reserved(ctx2)
        cancel_order(ctx2, order2, "player")
        self.assertEqual(commission_state(ctx2, CUSTOMER, SMITH)["line"]["code"], "canceled")

    def test_progress_is_a_fraction_of_the_work_ticks(self):
        ctx, _ = make_ctx()
        order = new_reserved(ctx)
        from systems.commission import advance_work, start_work
        start_work(ctx, order)
        for _ in range(450):
            advance_work(ctx, order)
        self.assertEqual(commission_state(ctx, CUSTOMER, SMITH)["orders"][0]["progress"], 0.5)


if __name__ == "__main__":
    unittest.main()
