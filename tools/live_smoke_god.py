"""Live god-mode smoke over real HTTP: powers refuse an embodied player, the iron gift loop, heal / weather / pause, Continue.

Backend and setup: see tools/smoke_common.py (four maps, fresh isolated data root). Then: python tools/live_smoke_god.py
Takes about two minutes: the smith has 4 iron, each sword needs 2 and 45 s of forging, so two real orders run before he is out of iron.
The possessed resident is the funded non-smith resident nearest the smith's door; after every release and re-claim the player is
walked back to Brann from wherever the resident ended up (a released resident returns to his own schedule, possibly indoors).
"""
import sys
import time

from smoke_common import Smoke

s = Smoke("god-smoke")
first_save = s.new_game()["active_save_id"]
s.me = s.pick_player(min_coin=30)
smith_id = s.agent("smith")["id"]
print("player:", s.me["name"], "| smith:", smith_id)


def possess_and_walk_to_smith():
    s.claim()
    s.send()
    ok, remaining = s.to_smith()
    return ok and remaining <= 14.0


s.check("possessed a resident and walked up to Brann", possess_and_walk_to_smith())

# 1. embodied players cannot use god powers
denied = s.command("/god/heal", possessed=True, target_id=s.me["id"])
s.check("god powers refuse an embodied controller", denied.get("reason") == "release_possession_first", str(denied.get("reason")))

# 2. use up the smith's iron with two real orders
for number in (1, 2):
    s.release()  # a sword costs 30 coin and the player may hold less: the god tops the purse up between orders
    topup = s.command("/god/spawn_resource", resource="coin", quantity=100, target_kind="resident", target_id=s.me["id"])
    s.check(f"coin top-up {number}", topup.get("status") == "applied", str(topup.get("reason")))
    s.check(f"order {number}: back next to Brann", possess_and_walk_to_smith())
    result = s.command("/commission/request", possessed=True)
    s.check(f"order {number} accepted", result.get("code") == "accepted", str(result.get("code")))
    order = s.wait_ready()
    s.check(f"order {number} ready", order is not None)
    s.smith_trace(f"order {number} ready")
    smith = s.agent(smith_id)
    s.walk_to((smith["x"] + 6.0, smith["y"] + 3.0), 3.0, 10.0)
    collected = s.command("/commission/collect", possessed=True, order_id=order["order_id"] if order else "")
    s.smith_trace(f"order {number} collect")
    s.check(f"order {number} collected", collected.get("state") == "delivered", str(collected.get("reason")))

# 3. no iron left: refused for the true reason
refused = s.command("/commission/request", possessed=True)
print("third request:", refused.get("code"), "|", refused.get("line"))
s.check("refused for want of iron", refused.get("code") == "refused_no_materials" and refused.get("accepted") is False)

# 4. release, the god gives iron
s.check("released", s.release().get("ok"))
gift = s.command("/god/spawn_resource", resource="iron_ingot", quantity=2, target_kind="resident", target_id=smith_id)
print("gift:", {k: gift.get(k) for k in ("status", "god_event_id", "witnesses", "reason")})
s.check("iron spawned into the smith", gift.get("status") == "applied" and gift.get("witnesses", 0) >= 1)
view = s.c.get(f"/god/inspect/{smith_id}").json()
print("inspect:", view["explanation"])
s.check("the smith remembers the gift", any(e["kind"] == "divine_gift" for e in view["recent_events"]))

# 5. possess again, ask again
s.check("back next to Brann for the third order", possess_and_walk_to_smith())
again = s.command("/commission/request", possessed=True)
s.check("the smith accepts now", again.get("code") == "accepted" and again.get("accepted") is True, str(again.get("code")))
state = s.c.get("/commission/state", params={"controller_id": "smoke"}).json()
print("greeting:", state.get("greeting"))
s.check("the smith greets with the delivered sword he remembers", (state.get("greeting") or {}).get("code") == "followup_delivered")
third_order = again.get("order_id")

# 6. heal, weather, pause (after releasing again)
s.release()
others = {a["name"]: a for a in s.agents()}
target = next(a for a in others.values() if a["id"] not in (smith_id, s.me["id"]))
heal = s.command("/god/heal", target_id=target["id"])
s.check("heal at full health is a no-op", heal.get("status") == "applied" and heal.get("healed") == 0.0)
dead = s.command("/god/heal", target_id="h_999999")
s.check("healing an unknown resident is rejected", dead.get("reason") == "unknown_resident")
weather = s.command("/god/weather", weather="rain")
s.check("weather set", weather.get("status") == "applied" and weather.get("changed") is True)
time.sleep(0.5)
s.check("weather visible in /status", s.c.get("/status").json()["god"]["weather"] == "rain")
s.check("weather visible in /frame", s.c.get("/frame").json()["nature"]["weather"] == "rain")
paused = s.command("/god/time", action="pause")
s.check("paused", paused.get("paused") is True)
tick = s.c.get("/frame").json()["tick"]
time.sleep(1.5)
s.check("simulation time is frozen while paused", s.c.get("/frame").json()["tick"] == tick)
spawn = s.command("/god/spawn_resource", resource="coin", quantity=5, target_kind="container", target_id="village:supply_crate")
s.check("commands still apply while paused", spawn.get("status") == "applied")
resumed = s.command("/god/time", action="resume")
time.sleep(1.0)
s.check("resumed", resumed.get("paused") is False and s.c.get("/frame").json()["tick"] > tick)

# 7. Continue: the gift is still remembered, the open order and its id survive, ids do not repeat
s.c.post("/session/new", json={"name": "other"}, headers=s.H)
cont = s.c.post("/session/continue", json={"save_id": first_save}, headers=s.H)
s.check("Continue ok", cont.status_code == 200, f"{cont.status_code} {cont.text[:200] if cont.status_code != 200 else ''}")
boot = s.c.get("/bootstrap").json()
s.world_epoch = boot["world_epoch"]
view = s.c.get(f"/god/inspect/{s.agent('smith')['id']}").json()
s.check("after Continue the smith still remembers the gift", any(e["kind"] == "divine_gift" for e in view["recent_events"]), view.get("explanation", ""))
orders = [o["order_id"] for o in view.get("commission_orders", [])]
print("smith orders after Continue:", orders, "| third order was", third_order)
s.check("after Continue the order ids are intact (the third order is still known)", third_order in orders or third_order is None, str(orders))
sys.exit(s.finish())
