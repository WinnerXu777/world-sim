"""Live portal smoke over real HTTP on the four-map world: every interior is reachable on foot from the village and the way back works.

Backend and setup: see tools/smoke_common.py. Then: python tools/live_smoke_portal.py
Checks the maps block (4 maps, primary first, sha256 of the served bytes), then for each interior: walk to its door anchor, portal in
(teleport_seq grows, the frame and the committed state agree), walk west inside it (the interior's own wall stops the player), portal
out again. An unknown portal is rejected. The possessed resident is whichever resident stands in the village nearest the smith's door.
"""
import hashlib
import sys
import time

from smoke_common import Smoke

s = Smoke("portal-smoke")
s.new_game()
boot = s.c.get("/bootstrap").json()
maps = boot["maps"]
print("maps:", [(m["map_id"], m["primary"], m["origin"]) for m in maps])
s.check("four maps, primary first", [m["map_id"] for m in maps][0] == "starter_village" and maps[0]["primary"] and len(maps) == 4 and not any(m["primary"] for m in maps[1:]),
        str([m["map_id"] for m in maps]))
s.load_maps(boot)
union = [min(m["rect"][0] for m in s.maps.values()), min(m["rect"][1] for m in s.maps.values()),
         max(m["rect"][2] for m in s.maps.values()), max(m["rect"][3] for m in s.maps.values())]
s.check("union bounds are exactly the union of the placed map rectangles", boot["spatial"]["bounds"] == [float(v) for v in union], f"{boot['spatial']['bounds']} vs {union}")
for m in maps:
    body = s.c.get(m["url"])
    s.check(f"/map_file/{m['map_id']} serves bytes whose sha256 equals the block", body.status_code == 200 and hashlib.sha256(body.content).hexdigest() == m["sha256"])

s.me = s.pick_player()
epoch0 = boot["world_epoch"]
claim = s.claim()
possession0 = claim["possession_epoch"]
print("player:", s.me["name"], "starts in", s.map_at(*s.position()))
teleports = 0
for interior in ("smith_interior", "village_lodge_interior", "west_cottage_interior"):
    # to the village first (if needed), then through the door of this interior
    if s.map_at(*s.position()) != s.primary:
        s.go_to_map(s.primary)
    door = next(p for p in s.maps[s.primary]["portals"] if p["to_map"] == interior)
    s.walk_to(s.anchor("village:talk_square"), 8.0, 25.0)
    reached = s.walk_to(s.anchor(door["from_anchor"]), 12.0, 25.0)
    s.check(f"reached the {interior} door on foot", reached <= 12.0, f"{reached:.1f} from {door['from_anchor']}")
    result = s.command("/control/portal", possessed=True, portal_id=door["id"])
    teleports += 1
    print(interior, "->", {k: result.get(k) for k in ("status", "reason", "to_map", "teleport_seq", "position")})
    s.check(f"portal into {interior} applied", result.get("status") == "applied" and result.get("teleport_seq") == teleports, str(result.get("reason")))
    time.sleep(0.5)
    mine = s.agent(s.me["id"])
    s.check("the frame shows the new position, map and teleport_seq", s.map_at(mine["x"], mine["y"]) == interior and mine.get("teleport_seq") == teleports,
            str((mine["x"], mine["y"], mine.get("teleport_seq"))))
    state = s.c.get("/control/state").json()
    sessions = state.get("sessions") or state.get("controls") or []
    committed = next((x.get("committed_state") for x in sessions if x.get("controller_id") == "smoke"), None)
    s.check("committed_state carries the teleport_seq", bool(committed) and committed.get("teleport_seq") == teleports, str(committed))
    # walk west inside the interior: its own wall must stop the player
    x0 = s.maps[interior]["rect"][0]
    for _ in range(30):
        s.send((-1, 0), True)
        time.sleep(0.1)
    s.send()
    time.sleep(0.2)
    px, py = s.position()
    s.check(f"stopped inside the {interior} rectangle", s.map_at(px, py) == interior and px >= x0, f"x={px:.1f} (rect x0={x0})")
    back = s.go_to_map(s.primary)
    s.check(f"portal out of {interior} lands in the village", back and s.map_at(*s.position()) == s.primary, str(s.position()))
    teleports += 1

s.check("epochs unchanged", s.c.get("/bootstrap").json()["world_epoch"] == epoch0 and
        (s.c.get("/control/state").json().get("sessions") or [{}])[0].get("possession_epoch", possession0) == possession0)
rejected = s.command("/control/portal", possessed=True, portal_id="village:nope")
print("unknown portal:", {k: rejected.get(k) for k in ("status", "reason")})
s.check("an unknown portal is rejected", rejected.get("status") == "rejected" or rejected.get("ok") is False, str(rejected.get("reason")))
sys.exit(s.finish())
