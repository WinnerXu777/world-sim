"""Live smith-loop smoke over real HTTP: walk to the smith's house, enter, commission a sword, wait, collect it once.

Backend and setup: see tools/smoke_common.py (four maps, fresh isolated data root). Then: python tools/live_smoke_smith.py
The sword takes about 45 s of real time to forge. The player is whichever non-smith resident stands nearest the smith's door;
Brann's map, anchor, routine and distance are traced when the order is requested, when it becomes ready and at collect.

``--night``: wait in the smithy until the clock (tick mod 2400) is at least 1100 before requesting, so the sword becomes ready in the
night block (1800 to 2399), where Brann's schedule says sleep. This is the case that used to make the collect fail.
``--lag N``: the player waits N seconds after the sword is ready before collecting (a person reads the panel first; default 0).
"""
import sys
import time

from smoke_common import Smoke  # noqa: E402

s = Smoke("smith-smoke")
print("New Game:", s.new_game().get("ok"))
names = sorted(a["name"] for a in s.agents())
s.check("eight roster residents", names == ["Brann", "Elsa", "Iven", "Mara", "Nessa", "Orrin", "Rhea", "Toma"], str(names))
s.check("four maps registered", sorted(s.maps) == ["smith_interior", "starter_village", "village_lodge_interior", "west_cottage_interior"], str(sorted(s.maps)))
s.me = s.pick_player(min_coin=30)  # a sword costs 30
print("player:", s.me["name"], "in", s.map_at(s.me["x"], s.me["y"]))
s.claim()
ok, remaining = s.to_smith()
s.check("walked into the smithy and up to Brann", ok and remaining <= 14.0, f"in_smithy={ok} remaining={remaining:.1f}")
smith = s.agent("smith")
s.check("smith is inside the interior", s.map_at(smith["x"], smith["y"]) == "smith_interior")
s.smith_trace("before request")
state = s.c.get("/commission/state", params={"controller_id": "smoke"}).json()
print("state:", [(ch["id"], ch["enabled"], ch["reason"]) for ch in state["choices"]])
s.check("request choice is enabled", state["choices"][0]["id"] == "request_commission" and state["choices"][0]["enabled"])

if "--night" in sys.argv:
    waited = time.time()
    while s.c.get("/frame").json()["tick"] % 2400 < 1100 and time.time() - waited < 150:
        s.send()
        time.sleep(0.25)
    print("night mode: requesting at tick", s.c.get("/frame").json()["tick"])
    s.smith_trace("before request (night mode)")
result = s.command("/commission/request", possessed=True)
print("request:", result.get("code"), result.get("state"), "|", result.get("line"))
s.check("the smith accepted", result.get("status") == "applied" and result.get("code") == "accepted", str(result))
order_id = result.get("order_id")
t0 = time.time()
order = s.wait_ready(120)
print("ready after %.1f s" % (time.time() - t0), order)
s.check("the sword became ready", order is not None)
ready = s.smith_trace("order ready")
lag = float(sys.argv[sys.argv.index("--lag") + 1]) if "--lag" in sys.argv else 0.0
t_lag = time.time()
while time.time() - t_lag < lag:
    s.send()  # a real client keeps sending input
    time.sleep(0.25)
if lag:
    s.smith_trace(f"after {lag:.0f} s of lag")
# 1. collect from where the player stands: the smith must still be at his forge (a ready order holds him there)
blind = s.command("/commission/collect", possessed=True, order_id=order_id)
print("collect without walking:", {k: blind.get(k) for k in ("status", "state", "reason", "duplicate")})
s.smith_trace("after the collect from where the player stood")
s.check("collect works from where the player stood (the smith waited at the forge)", blind.get("status") == "applied" and blind.get("state") == "delivered",
        str(blind.get("reason")))
collected = blind
if blind.get("state") != "delivered":  # fall back the way a player would: walk up to wherever he went, ask again
    smith = s.agent("smith")
    s.walk_to((smith["x"] + 6.0, smith["y"] + 3.0), 3.0, 10.0)
    s.smith_trace("before the second collect")
    collected = s.command("/commission/collect", possessed=True, order_id=order_id)
    print("collect after walking up:", {k: collected.get(k) for k in ("status", "state", "reason", "duplicate")})
s.check("collected once", collected.get("status") == "applied" and collected.get("state") == "delivered", str(collected.get("reason")))
again = s.command("/commission/collect", possessed=True, order_id=order_id)
s.check("a second collect moves nothing", again.get("status") == "applied" and again.get("duplicate") is True)
state = s.c.get("/commission/state", params={"controller_id": "smoke"}).json()
s.check("order shows delivered", state["orders"][0]["state"] == "delivered", str(state["orders"][0]["state"]))
sys.exit(s.finish())
