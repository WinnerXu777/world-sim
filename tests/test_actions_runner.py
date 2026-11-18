"""The action runner and the S1 verbs on synthetic worlds: effects, queued tasks, the Gate C rejection table (every verb: unknown name, wrong
arguments, wrong type, an id that does not exist, an id that exists but is not offered, a dead actor), D-1 item-creation rule, stale plans, the risk
gate, the rate limit and the mock Tier 3 plan runner. Real-engine behaviour of the verbs on roster residents is in ``test_actions_roster.py``."""
import copy
import sys
import unittest
from pathlib import Path

from driver_pin import pin_anchor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import torch  # noqa: E402

from harness import effects as fx  # noqa: E402
from harness.items import DictItemStore  # noqa: E402
from harness.registry import Registry, action  # noqa: E402
from harness.world import World  # noqa: E402
from systems.actions import (ActionDraft, ActionRunner, AuditLog, RateConfig, RiskConfig, StaticRecordOps, S1, run_plan)  # noqa: E402
from systems.affordance import Anchor, EntityFact, StaticServices  # noqa: E402


def setrow(world, human, **fields):
    t = world.table("humans")
    slot = t.slot_of(human)
    for k, v in fields.items():
        t.tensor[slot, t.col(k)] = float(v)


class Scene:
    """h_a acts: hungry, tired; h_b is 10 away, h_far 200 away, h_dead is dead next to h_a. Storage, a gather node, a forge, anchors."""

    def __init__(self, *, capacity=None, inv=None, roster=False, extra_records=None, contract=None):
        self.world = World.synthetic(seed=1, humans=12, items=DictItemStore(capacity_per_owner=capacity))
        for hid, (x, y) in {"h_a": (10, 10), "h_b": (20, 10), "h_far": (210, 10), "h_dead": (12, 12), "h_smith": (14, 10)}.items():
            self.world.add_row("humans", hid, x=x, y=y, hp=100, hunger=0, stamina=100, mood=50)
        setrow(self.world, "h_dead", hp=0)
        inv = {"h_a": {"rations": 2, "wood_bundle": 2, "iron_ingot": 1}, "h_b": {"rations": 1}, **(inv or {})}
        for owner, items in inv.items():
            for kind, q in items.items():
                self.world.items.add(owner, kind, q)
        self.records = {"h_a": {"occupation": {"kind": "builder"}, "relationships": {}, **({"roster": {"key": "builder"}} if roster else {})},
                        "h_b": {"occupation": {"kind": "gatherer"}, "relationships": {}},
                        "h_smith": {"occupation": {"kind": "smith"}, "relationships": {}}, **(extra_records or {})}
        entities = [EntityFact("e_store", "storage", 15.0, 10.0, True, 16.0), EntityFact("e_store_far", "storage", 150.0, 10.0, True, 16.0),
                    EntityFact("e_tree", "wood_pile", 30.0, 10.0, True, 16.0), EntityFact("e_far_tree", "wood_pile", 200.0, 10.0, True, 16.0),
                    EntityFact("smith:forge", "forge", 16.0, 12.0, True, 16.0)]
        anchors = {"h_a": {"sleep": Anchor("v:bed", "sleep", 12.0, 10.0), "work": Anchor("v:work", "work", 40.0, 10.0)}}
        sites = {"h_a": {"water": Anchor("v:well", "water", 60.0, 10.0), "food": Anchor("v:fire", "food", 50.0, 10.0)}}
        self.services = _SyncedServices(self.world, records=self.records, anchors=anchors, sites=sites, entities=entities, contract=contract,
                                        config={"prices": {"sword": 30}})
        self.ops = StaticRecordOps(self.records)
        self.audit = AuditLog()
        self.runner = ActionRunner(self.world, self.services, record_ops=self.ops, audit=self.audit)
        self.mask_hp = 100
        self.world.events.emit("fire_seen", actors=("h_a",), place=(10.0, 10.0), visibility="private")          # ev_000001, witnessed by h_a only

    def digest(self):
        return (self.world.table("humans").tensor.clone(), copy.deepcopy(self.world.items.__dict__), copy.deepcopy(self.records))

    @staticmethod
    def same(a, b):
        return torch.equal(a[0], b[0]) and a[1] == b[1] and a[2] == b[2]


class _SyncedServices(StaticServices):
    """StaticServices whose inventories are read from the world's item store, so a second call sees the first call's effects."""

    def __init__(self, world, **kw):
        super().__init__(**kw)
        self.world = world

    def inventory(self, owner):
        return {k: self.world.items.quantity(owner, k) for k in self.world.items.items() if self.world.items.quantity(owner, k) > 0}


class VerbEffectTests(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)

    def test_eat_from_the_pack_is_atomic_and_conserves_items(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        total_before = {k: s.world.items.total(k) for k in s.world.items.items()}
        revision = s.world.revision
        r = s.runner.run("h_a", "eat", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.world.items.quantity("h_a", "rations"), 1)
        self.assertEqual(s.world.items.total("rations"), total_before["rations"] - 1)       # destroyed by declared consumption
        self.assertAlmostEqual(s.world.table("humans").get("h_a", "hunger"), 60.0)          # EAT_HUNGER_RESTORE = 20
        self.assertAlmostEqual(s.world.table("humans").get("h_a", "mood"), 50.25)
        self.assertGreater(s.world.revision, revision)
        self.assertTrue(r.report.ok)
        self.assertEqual([e.type for e in r.report.events], ["ate"])
        self.assertFalse(s.world.effects.allow_item_creation)                                  # restored after the apply
        self.assertEqual(s.audit.last["code"], "ok")
        self.assertTrue(s.audit.last["applied"])

    def test_eat_never_goes_below_zero_hunger(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=5)
        self.assertTrue(s.runner.run("h_a", "eat", {}).ok)
        self.assertEqual(s.world.table("humans").get("h_a", "hunger"), 0.0)

    def test_eat_at_a_site_queues_the_food_task(self):
        s = Scene(inv={"h_a": {}})
        for kind in ("rations", "wood_bundle", "iron_ingot"):
            s.world.items.remove("h_a", kind, 5)
        setrow(s.world, "h_a", hunger=80)
        r = s.runner.run("h_a", "eat", {"place": "v:fire"})
        self.assertTrue(r.ok, r.code)
        task = s.records["h_a"]["tasks"][0]
        self.assertEqual((task["task_kind"], task["target_kind"], task["target_id"]), ("eat_food", "resource", "food"))
        self.assertEqual(r.ops[0]["ok"], True)

    def test_dry_run_changes_nothing(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        before = s.digest()
        r = s.runner.run("h_a", "eat", {}, dry_run=True)
        self.assertTrue(r.ok)
        self.assertTrue(Scene.same(before, s.digest()))
        self.assertEqual(s.audit.last["dry_run"], True)
        self.assertEqual(s.audit.last["applied"], False)

    def test_give_item_moves_items_updates_relationships_and_emits(self):
        s = Scene()
        r = s.runner.run("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 2})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((s.world.items.quantity("h_a", "rations"), s.world.items.quantity("h_b", "rations")), (0, 3))
        self.assertEqual(s.world.items.total("rations"), 3)                                      # nothing created or destroyed
        self.assertAlmostEqual(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.03)
        self.assertAlmostEqual(s.records["h_b"]["relationships"]["h_a"]["closeness"], 0.06)
        self.assertEqual([e.type for e in r.report.events], ["gave_item"])

    def test_store_and_fetch_move_items_between_pack_and_container(self):
        s = Scene()
        self.assertTrue(s.runner.run("h_a", "store_item", {"item": "wood_bundle", "qty": 2, "container": "e_store"}).ok)
        self.assertEqual((s.world.items.quantity("h_a", "wood_bundle"), s.world.items.quantity("e_store", "wood_bundle")), (0, 2))
        r = s.runner.run("h_a", "fetch_item", {"item": "wood_bundle", "qty": 1, "container": "e_store"})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((s.world.items.quantity("h_a", "wood_bundle"), s.world.items.quantity("e_store", "wood_bundle")), (1, 1))
        self.assertEqual(s.runner.run("h_a", "fetch_item", {"item": "wood_bundle", "qty": 3, "container": "e_store"}).code, "illegal:no_item")

    def test_craft_consumes_ingredients_and_creates_the_output_in_one_apply(self):
        s = Scene(inv={"h_smith": {"iron_ingot": 2, "wood_bundle": 1, "hammer": 1}})
        before = {k: s.world.items.total(k) for k in ("iron_ingot", "wood_bundle", "sword", "hammer")}
        r = s.runner.run("h_smith", "craft", {"recipe": "sword"})
        self.assertTrue(r.ok, r.code)
        after = {k: s.world.items.total(k) for k in before}
        self.assertEqual((after["iron_ingot"], after["wood_bundle"], after["sword"], after["hammer"]),
                         (before["iron_ingot"] - 2, before["wood_bundle"] - 1, 1, before["hammer"]))
        self.assertEqual(s.world.items.quantity("h_smith", "sword"), 1)
        self.assertEqual(r.report.created, {"sword": 1})
        self.assertEqual(r.report.destroyed, {"iron_ingot": 2, "wood_bundle": 1})

    def test_task_verbs_queue_the_expected_legacy_task(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=0, stamina=30)
        cases = [("rest", {}, "sleep"), ("sleep", {}, "seek_shelter"), ("go_to_work", {}, "move_to_place"), ("gather_resource", {"source": "e_tree"}, "gather_material"),
                 ("greet", {"target": "h_b"}, "talk_to_target"), ("chat", {"target": "h_b", "topic": "weather"}, "talk_to_target"),
                 ("follow", {"target": "h_b"}, "follow_target"), ("work_shift", None, "build_work")]
        for verb, args, kind in cases:
            if args is None:                                  # work_shift needs the actor at the work anchor
                setrow(s.world, "h_a", x=40, y=10)
                args = {}
            before = len(s.records["h_a"].get("tasks", []))
            r = s.runner.run("h_a", verb, args)
            self.assertTrue(r.ok, (verb, r.code, r.detail))
            self.assertEqual(s.records["h_a"]["tasks"][before]["task_kind"], kind, verb)
        gather = [t for t in s.records["h_a"]["tasks"] if t["task_kind"] == "gather_material"][0]
        self.assertEqual((gather["target_id"], gather["requested_quantity"]), ("wood_bundle", 1))
        self.assertAlmostEqual(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.05)           # greet 0.02 + chat 0.03

    def test_roster_resident_gets_the_routine_route_for_movement_verbs(self):
        s = Scene(roster=True)
        setrow(s.world, "h_a", stamina=30)
        for verb, routine in (("sleep", "sleep"), ("go_to_work", "work_site"), ("flee_to", "return_home")):
            r = s.runner.run("h_a", verb, {})
            self.assertTrue(r.ok, (verb, r.code, r.detail))
            self.assertEqual(s.records["h_a"]["schedule_state"]["current_routine"]["kind"], routine, verb)
        self.assertNotIn("tasks", s.records["h_a"])

    def test_roster_resident_is_refused_the_verbs_whose_task_would_stay_active_forever(self):
        s = Scene(roster=True)
        for kind in ("rations", "wood_bundle", "iron_ingot"):
            s.world.items.remove("h_a", kind, 5)
        setrow(s.world, "h_a", hunger=80, x=40, y=10)
        s.services._anchors["h_a"]["work"] = Anchor("v:work", "work", 40.0, 10.0)
        cases = [("eat", {"place": "v:fire"}), ("work_shift", {}), ("gather_resource", {"source": "e_tree"}), ("follow", {"target": "h_b"})]
        for verb, args in cases:
            r = s.runner.run("h_a", verb, args)
            self.assertEqual(r.code, "illegal:roster_driven", (verb, r.code, r.detail))
        self.assertNotIn("tasks", s.records["h_a"])
        r = s.runner.run("h_a", "greet", {"target": "h_b"})                # greet still nudges the relationship, without a task
        self.assertTrue(r.ok, r.code)
        self.assertNotIn("tasks", s.records["h_a"])
        self.assertAlmostEqual(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.02)

    def test_non_roster_flee_queues_flee_target(self):
        s = Scene()
        r = s.runner.run("h_a", "flee_to", {})
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.records["h_a"]["tasks"][0]["task_kind"], "flee_target")
        self.assertEqual(s.records["h_a"]["tasks"][0]["priority"], 0.97)

    def test_smith_has_no_work_task_so_work_shift_is_refused(self):
        s = Scene()
        setrow(s.world, "h_smith", x=40, y=10)
        s.services._anchors["h_smith"] = {"work": Anchor("v:forge", "work", 40.0, 10.0)}
        r = s.runner.run("h_smith", "work_shift", {})
        self.assertEqual(r.code, "refused:no_work_task")
        self.assertNotIn("tasks", s.records["h_smith"])

    def test_commission_item_goes_to_the_record_op(self):
        s = Scene()
        r = s.runner.run("h_a", "commission_item", {"target": "h_smith", "recipe": "sword"})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(r.ops[0]["kind"], "commission_request")
        self.assertFalse(r.ops[0]["ok"])                      # the static record ops cannot place an order: reported, not raised
        self.assertEqual(r.ops[0]["reason"], "unsupported_op")


class RequestItemTests(unittest.TestCase):
    def test_a_holder_gives_through_the_same_runner(self):
        s = Scene()
        r = s.runner.run("h_a", "request_item", {"target": "h_b", "item": "rations", "qty": 1})
        self.assertTrue(r.ok, r.code)
        self.assertEqual((r.ops[0]["answer"], r.ops[0]["gave"]), ("give", True))
        self.assertEqual((s.world.items.quantity("h_a", "rations"), s.world.items.quantity("h_b", "rations")), (3, 0))
        verbs = [(e["actor"], e["verb"], e["proposer"]) for e in s.audit.entries]
        self.assertEqual(verbs, [("h_b", "give_item", "rules:request_response"), ("h_a", "request_item", "rules")])

    def test_refusals(self):
        s = Scene()
        self.assertEqual(s.runner.run("h_a", "request_item", {"target": "h_b", "item": "iron_ingot"}).ops[0]["answer"], "refuse_no_item")
        s.records["h_b"]["relationships"]["h_a"] = {"closeness": -0.5, "tags": []}
        self.assertEqual(s.runner.run("h_a", "request_item", {"target": "h_b", "item": "rations"}).ops[0]["answer"], "refuse_distrust")
        s.records["h_b"]["relationships"]["h_a"] = {"closeness": 0.0, "tags": ["rival"]}
        self.assertEqual(s.runner.run("h_a", "request_item", {"target": "h_b", "item": "rations"}).ops[0]["answer"], "refuse_distrust")
        s.records["h_b"]["relationships"]["h_a"] = {}
        setrow(s.world, "h_b", hp=0)
        self.assertEqual(s.runner.run("h_a", "request_item", {"target": "h_b", "item": "rations"}).code, "illegal:target_dead")

    def test_the_request_itself_never_reads_the_targets_pack(self):
        s = Scene()
        a = s.runner.plan("h_a", "request_item", {"target": "h_b", "item": "iron_ingot"})
        s.world.items.remove("h_b", "rations", 1)
        b = s.runner.plan("h_a", "request_item", {"target": "h_b", "item": "iron_ingot"})
        self.assertEqual((a.ok, b.ok), (True, True))                  # legality is identical whether or not the target holds anything


class GateCTests(unittest.TestCase):
    """Rejected, logged once, nothing changed - for every S1 verb."""

    # (verb, wrong type args, args with an id that does not exist, expected ungrounded code, args that exist but are not offered)
    CASES = {
        "eat": ({"item": 5}, {"item": "unobtainium"}, "ungrounded_item", {"item": "fish_catch"}),
        "drink": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "rest": ({"until": "hp"}, None, None, {}),
        "sleep": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "flee_to": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "go_to_work": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "work_shift": ({"hours": 3}, None, None, {}),
        "gather_resource": ({"source": 5}, {"source": "e_nope"}, "ungrounded_target", {"source": "e_store"}),
        "craft": ({"recipe": 5}, {"recipe": "nonsense"}, "ungrounded_recipe", {"recipe": "sword"}),
        "store_item": ({"qty": "x"}, {"item": "wood_bundle", "container": "e_nope"}, "ungrounded_target", {"item": "wood_bundle", "container": "e_store_far"}),
        "fetch_item": ({"qty": "x"}, {"item": "wood_bundle", "container": "e_nope"}, "ungrounded_target", {"item": "wood_bundle", "container": "e_store_far"}),
        "request_item": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "give_item": ({"target": 5}, {"target": "h_nope", "item": "rations"}, "ungrounded_target", {"target": "h_far", "item": "rations"}),
        "commission_item": ({"recipe": 5}, {"target": "h_smith", "recipe": "nonsense"}, "ungrounded_recipe", {"target": "h_b", "recipe": "sword"}),
        "greet": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "chat": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "follow": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        # batch 1 (1008_actions.md 10.10)
        "seek_shelter": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "hide": ({"place": 3}, {"place": "nowhere"}, "ungrounded_place", {"place": "v:well"}),
        "attack": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "avoid": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "warn": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "ask_for_help": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "comfort": ({"target": 5}, {"target": "h_nope"}, "ungrounded_target", {"target": "h_far"}),
        "explore_toward": ({"heading": 5}, None, None, {"heading": "up"}),
        # batch 2 (1008_actions.md 10.14)
        "offer_trade": ({"target": 5}, {"target": "h_nope", "give": "rations", "want": "wood_bundle"}, "ungrounded_target",
                        {"target": "h_far", "give": "rations", "want": "wood_bundle"}),
        "accept_trade": ({"offer": 5}, None, None, {"offer": "offer_00099"}),
        "steal_when_safe": ({"qty": "x"}, {"target": "h_nope", "item": "rations"}, "ungrounded_target", {"target": "h_far", "item": "rations"}),
        "share_news": ({"target": 5}, {"target": "h_nope", "event": "ev_000001"}, "ungrounded_target", {"target": "h_far", "event": "ev_000001"}),
        "gossip": ({"target": 5}, {"target": "h_b", "about": "h_nope"}, "ungrounded_target", {"target": "h_far", "about": "h_b"}),
    }

    def run_rejected(self, scene, actor, verb, args, code, *, prefix=False):
        before, count = scene.digest(), scene.audit.total
        r = scene.runner.run(actor, verb, args)
        self.assertFalse(r.ok, (verb, args))
        if prefix:
            self.assertTrue(r.code.startswith(code), (verb, args, r.code))
        else:
            self.assertEqual(r.code, code, (verb, args, r.detail))
        self.assertEqual(scene.audit.total, count + 1, f"{verb}: exactly one audit entry")
        self.assertEqual(scene.audit.last["code"], r.code)
        self.assertFalse(scene.audit.last["ok"])
        self.assertTrue(Scene.same(before, scene.digest()), f"{verb} {args}: a rejected call changed the world")
        return r

    def test_the_table_covers_every_s1_verb(self):
        self.assertEqual(sorted(self.CASES), sorted(S1))

    def test_nonexistent_and_unimplemented_verbs(self):
        s = Scene()
        for name in ("teleport", "", "EAT", "eat ", "hunt", "repair", "defend"):
            r = self.run_rejected(s, "h_a", name, {}, "unknown_action" if name in ("teleport", "", "EAT", "eat ") else "not_implemented")
            self.assertIn(r.code, ("unknown_action", "not_implemented"))
        self.run_rejected(s, "h_a", None, {}, "unknown_action")
        self.run_rejected(s, "h_a", "eat", ["not", "a", "dict"], "invalid_arguments")

    def test_unknown_actor(self):
        s = Scene()
        self.run_rejected(s, "h_nope", "eat", {}, "unknown_actor")
        self.run_rejected(s, 7, "eat", {}, "unknown_actor")

    def test_wrong_argument_names_and_types_are_invalid_arguments(self):
        s = Scene()
        for verb, (wrong, *_rest) in self.CASES.items():
            self.run_rejected(s, "h_a", verb, wrong, "invalid_arguments")
            self.run_rejected(s, "h_a", verb, {"definitely_not_a_parameter": 1}, "invalid_arguments")

    def test_ids_that_do_not_exist_are_ungrounded(self):
        s = Scene()
        for verb, (_wrong, missing, code, _unoffered) in self.CASES.items():
            if missing is not None:
                self.run_rejected(s, "h_a", verb, missing, code)

    def test_ids_that_exist_but_are_not_offered_are_illegal(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        for verb, (_wrong, _missing, _code, unoffered) in self.CASES.items():
            if verb == "eat":
                unoffered = {"item": "fish_catch"}                         # exists, hungry, but not held
            if verb == "craft":
                unoffered = {"recipe": "sword"}                            # a builder is not a smith
            self.run_rejected(s, "h_a", verb, unoffered, "illegal:", prefix=True)

    def test_a_dead_actor_can_do_nothing(self):
        s = Scene()
        for verb in S1:
            self.run_rejected(s, "h_dead", verb, {}, "illegal:dead")

    def test_quantity_must_be_a_positive_integer(self):
        s = Scene()
        for bad in (0, -1):
            self.run_rejected(s, "h_a", "give_item", {"target": "h_b", "item": "rations", "qty": bad}, "illegal:invalid_params")
        for bad in (1.5, "2", True, None):
            self.run_rejected(s, "h_a", "give_item", {"target": "h_b", "item": "rations", "qty": bad}, "invalid_arguments")

    def test_unreachable_target_is_rejected_and_logged(self):
        walled = {"actor_radius": 2.4, "bounds": [0.0, 0.0, 300.0, 100.0], "boxes": [{"id": "w", "min": [4, 0], "max": [6, 100], "height": 2.4}]}
        s = Scene(contract=walled)
        setrow(s.world, "h_a", x=2, y=10)
        setrow(s.world, "h_b", x=8, y=10)
        self.run_rejected(s, "h_a", "give_item", {"target": "h_b", "item": "rations"}, "illegal:blocked")
        r = self.run_rejected(s, "h_a", "greet", {"target": "h_b"}, "illegal:", prefix=True)
        self.assertIn(r.code, ("illegal:blocked", "illegal:unreachable"))

    def test_the_audit_ring_and_jsonl_sink(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            sink = Path(folder) / "audit" / "actions.jsonl"
            s = Scene()
            s.audit = AuditLog(maxlen=3, sink=str(sink))
            s.runner.audit = s.audit
            for _ in range(5):
                s.runner.run("h_a", "teleport", {})
            self.assertEqual((len(s.audit.entries), s.audit.total), (3, 5))
            lines = sink.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 5)
            self.assertEqual(json.loads(lines[0])["code"], "unknown_action")


class RunnerPolicyTests(unittest.TestCase):
    def test_item_creation_must_be_declared(self):
        reg = Registry()

        @action("conjure", registry=reg)
        def conjure(world, ctx) -> ActionDraft:
            return ActionDraft([fx.Transfer("gold", 5, None, ctx.actor)], None, [], {})

        @action("honest", registry=reg)
        def honest(world, ctx) -> ActionDraft:
            return ActionDraft([fx.Transfer("rations", 1, ctx.actor, None)], None, [], {}, consumes=(("rations", 1),))

        @action("liar", registry=reg)
        def liar(world, ctx) -> ActionDraft:
            return ActionDraft([fx.Transfer("rations", 2, ctx.actor, None)], None, [], {}, consumes=(("rations", 1),))

        import systems.affordance.predicates as pred
        for name in ("conjure", "honest", "liar"):
            pred.VERBS[name] = pred.VerbDef(name, "alive", lambda S, **kw: pred.yes(), lambda S: [{}])
        try:
            s = Scene()
            s.runner.registry = reg
            self.assertEqual(s.runner.run("h_a", "conjure", {}).code, "undeclared_item_creation")
            self.assertEqual(s.world.items.quantity("h_a", "gold"), 0)
            self.assertEqual(s.runner.run("h_a", "liar", {}).code, "undeclared_item_creation")
            self.assertEqual(s.world.items.quantity("h_a", "rations"), 2)
            self.assertTrue(s.runner.run("h_a", "honest", {}).ok)
            self.assertEqual(s.world.items.quantity("h_a", "rations"), 1)
            self.assertFalse(s.world.effects.allow_item_creation)
        finally:
            for name in ("conjure", "honest", "liar"):
                pred.VERBS.pop(name, None)

    def test_the_permit_is_per_apply_and_caps_the_sum_over_the_draft(self):
        """H-Q1: the runner passes an ItemPermit (summed per item) and never touches ``allow_item_creation``; two Transfers that each match the
        declaration but together exceed it are refused by the harness (``consume_over_cap``) and nothing changes."""
        reg = Registry()

        @action("twice", registry=reg)
        def twice(world, ctx) -> ActionDraft:
            take = fx.Transfer("rations", 1, ctx.actor, None)
            return ActionDraft([take, take], None, [], {}, consumes=(("rations", 1),))

        @action("honest", registry=reg)
        def honest(world, ctx) -> ActionDraft:
            return ActionDraft([fx.Transfer("rations", 1, ctx.actor, None)], None, [], {}, consumes=(("rations", 1),))

        import systems.affordance.predicates as pred
        for name in ("twice", "honest"):
            pred.VERBS[name] = pred.VerbDef(name, "alive", lambda S, **kw: pred.yes(), lambda S: [{}])
        try:
            s = Scene()
            s.runner.registry = reg
            seen = []
            real_apply = s.world.apply

            def spy(effects, **kw):
                seen.append((kw.get("items"), s.world.effects.allow_item_creation))
                return real_apply(effects, **kw)
            s.world.apply = spy
            before = s.digest()
            r = s.runner.run("h_a", "twice", {})
            self.assertEqual(r.code, "apply_failed")
            self.assertIn("consume_over_cap", [skip[1] for skip in r.detail["skipped"]])
            self.assertTrue(Scene.same(before, s.digest()))
            self.assertTrue(s.runner.run("h_a", "honest", {}).ok)
            self.assertEqual(seen[0][0].as_dict(), {"consume": {"rations": 1}, "produce": {}})
            self.assertEqual({flag for _, flag in seen}, {False})                   # the global switch is never used
        finally:
            for name in ("twice", "honest"):
                pred.VERBS.pop(name, None)

    def test_a_failed_apply_restores_the_creation_flag_and_changes_nothing(self):
        reg = Registry()

        @action("overdraw", registry=reg)
        def overdraw(world, ctx) -> ActionDraft:
            return ActionDraft([fx.Transfer("rations", 50, ctx.actor, None)], None, [], {}, consumes=(("rations", 50),))

        import systems.affordance.predicates as pred
        pred.VERBS["overdraw"] = pred.VerbDef("overdraw", "alive", lambda S, **kw: pred.yes(), lambda S: [{}])
        try:
            s = Scene()
            s.runner.registry = reg
            before = s.digest()
            r = s.runner.run("h_a", "overdraw", {})
            self.assertEqual(r.code, "apply_failed")
            self.assertTrue(Scene.same(before, s.digest()))
            self.assertFalse(s.world.effects.allow_item_creation)
        finally:
            pred.VERBS.pop("overdraw", None)

    def test_a_stale_plan_is_judged_again_at_apply_time(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        planned = s.runner.plan("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 2})
        self.assertTrue(planned.ok)
        s.world.items.remove("h_a", "rations", 2)                       # the ration is gone ...
        s.world.bump_revision()                                         # ... and the world moved on
        applied = s.runner.apply(planned)
        self.assertFalse(applied.ok)
        self.assertEqual(applied.code, "illegal:no_item")
        self.assertTrue(applied.detail["replanned"])
        self.assertEqual(s.world.items.quantity("h_b", "rations"), 1)

    def test_a_current_plan_applies_without_replanning(self):
        s = Scene()
        planned = s.runner.plan("h_a", "give_item", {"target": "h_b", "item": "rations"})
        applied = s.runner.apply(planned)
        self.assertTrue(applied.ok)
        self.assertNotIn("replanned", applied.detail)

    def test_destructive_verbs_need_rules_or_confidence(self):
        reg = Registry()

        @action("smite", risk="destructive", registry=reg)
        def smite(world, ctx) -> ActionDraft:
            return ActionDraft([], None, [], {})

        import systems.affordance.predicates as pred
        pred.VERBS["smite"] = pred.VerbDef("smite", "alive", lambda S, **kw: pred.yes(), lambda S: [{}])
        try:
            s = Scene()
            s.runner.registry, s.runner.risk = reg, RiskConfig(min_confidence=0.6)
            self.assertEqual(s.runner.run("h_a", "smite", {}, proposer="tier2", confidence=0.4).code, "risk_gated")
            self.assertEqual(s.runner.run("h_a", "smite", {}, proposer="tier2").code, "risk_gated")
            self.assertTrue(s.runner.run("h_a", "smite", {}, proposer="tier2", confidence=0.8).ok)
            self.assertTrue(s.runner.run("h_a", "smite", {}, proposer="rules").ok)
        finally:
            pred.VERBS.pop("smite", None)

    def test_rate_limit_per_actor(self):
        s = Scene()
        s.runner.rate = RateConfig(window_ticks=20, max_calls=3)
        for _ in range(3):
            self.assertTrue(s.runner.run("h_a", "greet", {"target": "h_b"}).ok)
        r = s.runner.run("h_a", "greet", {"target": "h_b"})
        self.assertEqual(r.code, "rate_limited")
        self.assertTrue(s.runner.run("h_b", "greet", {"target": "h_a"}).ok)            # another actor is unaffected
        s.world.clock.advance(25)
        self.assertTrue(s.runner.run("h_a", "greet", {"target": "h_b"}).ok)              # the window moved on


class PlanRunnerTests(unittest.TestCase):
    def test_a_plan_runs_each_step_through_the_runner(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        plan = [{"op": "eat", "args": {}}, {"op": "give_item", "args": {"target": "h_b", "item": "rations", "qty": 1}},
                {"op": "store_item", "args": {"item": "wood_bundle", "qty": 1, "container": "e_store"}}]
        out = run_plan(s.runner, "h_a", plan)
        self.assertTrue(out["ok"], out["code"])
        self.assertEqual((out["completed"], len(out["results"])), (3, 3))
        self.assertEqual([e["verb"] for e in s.audit.entries], ["eat", "give_item", "store_item"])
        self.assertTrue(all(e["proposer"] == "tier3" for e in s.audit.entries))

    def test_a_plan_stops_at_the_first_rejection(self):
        s = Scene()
        plan = [{"op": "greet", "args": {"target": "h_b"}}, {"op": "give_item", "args": {"target": "h_far", "item": "rations"}},
                {"op": "greet", "args": {"target": "h_b"}}]
        out = run_plan(s.runner, "h_a", plan)
        self.assertEqual((out["ok"], out["completed"], out["failed_at"], out["code"]), (False, 1, 1, "illegal:no_target"))      # 200 units away: beyond perception
        self.assertEqual(len(s.audit.entries), 2)

    def test_bad_plans_are_rejected_not_raised(self):
        s = Scene()
        for plan in ("eat", None, 3, [{"args": {}}], [{"op": 3}], ["eat"], [{"op": "teleport"}], [{"op": "attack", "args": {"target": "h_b"}}]):
            out = run_plan(s.runner, "h_a", plan)
            self.assertFalse(out["ok"], plan)
        self.assertEqual(run_plan(s.runner, "h_a", [{"op": "teleport"}])["code"], "unknown_action")
        self.assertEqual(run_plan(s.runner, "h_a", [{"op": "defend", "args": {}}])["code"], "not_a_plan_op")
        self.assertEqual(run_plan(s.runner, "h_a", "eat")["code"], "invalid_plan")

    def test_dry_run_plan_changes_nothing(self):
        s = Scene()
        setrow(s.world, "h_a", hunger=80)
        before = s.digest()
        out = run_plan(s.runner, "h_a", [{"op": "eat", "args": {}}], dry_run=True)
        self.assertTrue(out["ok"])
        self.assertTrue(Scene.same(before, s.digest()))


if __name__ == "__main__":
    unittest.main()
