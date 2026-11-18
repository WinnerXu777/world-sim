"""Live smoke against a running authored-map backend (see 1006_live_smoke_report.md): bootstrap, map files, residents, walls.

Backend and setup: see tools/smoke_common.py (four maps, fresh isolated data root; this script creates a New Game there, so never
point it at a world you want to keep). Then: python tools/live_smoke_authored.py
"""
import hashlib
import json
import sys
import time
from pathlib import Path

from smoke_common import Smoke

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
from systems.movement.spatial import is_standable_point  # noqa: E402

s = Smoke("authored-smoke")
c = s.c
boot0 = c.get("/bootstrap")
print("GET /bootstrap (before New Game):", boot0.status_code, "keys", sorted(boot0.json()))
print("maps present before world exists:", "maps" in boot0.json(), "| map_name", boot0.json()["world"]["map_name"])
print("GET /session:", c.get("/session").json())
r = c.post("/session/new", json={"name": "smoke-test"}, headers=s.H)
print("POST /session/new:", r.status_code, json.dumps(r.json())[:200])
s.check("New Game ok", r.status_code == 200 and r.json().get("ok"))

boot = c.get("/bootstrap").json()
s.load_maps(boot)
s.world_epoch = boot["world_epoch"]
blocks = boot["maps"]
s.check("bootstrap has a maps block with the four placed maps, primary first",
        [b["map_id"] for b in blocks] == ["starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior"], str([b["map_id"] for b in blocks]))
expected_keys = ["map_id", "format_version", "revision", "sha256", "size_bytes", "url", "map_kind", "units_per_tile",
                 "tile_size_px", "size_tiles", "actor_radius", "origin", "primary"]
for block in blocks:
    s.check(f"{block['map_id']}: exactly the 13 spec keys in order, int revision", list(block) == expected_keys and type(block["revision"]) is int, str(list(block)))
    disk = (ROOT / "world_data" / "maps2d" / f"{block['map_id']}.json").read_bytes()
    resp = c.get(block["url"])
    s.check(f"{block['map_id']}: /map_file bytes equal the file on disk, sha256 and ETag match, size_bytes right",
            resp.content == disk and hashlib.sha256(resp.content).hexdigest() == block["sha256"]
            and resp.headers.get("etag") == f'"{block["sha256"]}"' and block["size_bytes"] == len(disk))
    r304 = c.get(block["url"], headers={"If-None-Match": f'"{block["sha256"]}"'})
    s.check(f"{block['map_id']}: If-None-Match gives 304 with an empty body", r304.status_code == 304 and r304.content == b"")
s.check("unknown map is 404", c.get("/map_file/nope").status_code == 404)
s.check("map_name is starter_village", boot["world"]["map_name"] == "starter_village")
spatial = boot["spatial"]
print("spatial (without boxes):", {k: v for k, v in spatial.items() if k != "boxes"}, "| boxes:", len(spatial["boxes"]))
village = blocks[0]
s.check("spatial carries the primary map_id/revision/units_per_tile", (spatial.get("map_id"), spatial.get("map_revision"), spatial.get("units_per_tile")) ==
        ("starter_village", village["revision"], 8.0), str((spatial.get("map_id"), spatial.get("map_revision"))))
union = [min(m["rect"][0] for m in s.maps.values()), min(m["rect"][1] for m in s.maps.values()),
         max(m["rect"][2] for m in s.maps.values()), max(m["rect"][3] for m in s.maps.values())]
s.check("actor_radius 2.4 and bounds are the union of the placed maps", spatial["actor_radius"] == 2.4 and spatial["bounds"] == [float(v) for v in union], f"{spatial['bounds']} vs {union}")

agents = s.agents()
print("agents:", [(a.get("name"), a.get("roster_key"), round(a["x"], 1), round(a["y"], 1), s.map_at(a["x"], a["y"])) for a in agents])
s.check("eight roster residents", len(agents) == 8, str(len(agents)))
standable = [is_standable_point((a["x"], a["y"]), spatial) for a in agents]
s.check("every resident spawned standable under the live contract", all(standable), str(standable))
village_agents = [a for a in agents if s.map_at(a["x"], a["y"]) == s.primary]
sx, sy = s.anchor("village:spawn")
nearest = min(max(abs(a["x"] - sx), abs(a["y"] - sy)) for a in village_agents)
s.check("the village residents start around the real spawn anchor", nearest < 12.0 and len(village_agents) >= 6, f"nearest offset {nearest:.2f}, {len(village_agents)} in the village")

# the wall probe: stand south of the well (x inside the well wall, y below it), walk north, stop at the contract boundary
s.me = s.pick_player("village:use_well")
print("claiming:", s.me["name"], "in", s.map_at(s.me["x"], s.me["y"]))
claim = s.claim()
s.check("claim ok", claim.get("ok"))
if s.map_at(*s.position()) != s.primary:
    s.go_to_map(s.primary)
well_wall_x = 188.0   # the well wall is [180,132]-[196,140]
reached = s.walk_to((well_wall_x, 160.0), 1.5, 25.0, sprint=False)
s.check("walked to the spot south of the well", reached <= 2.5, f"{reached:.1f}")
time.sleep(0.3)
baseline = s.position()
for _ in range(60):
    s.send((0, -1), False)
    time.sleep(0.1)
time.sleep(0.3)
me = s.agent(s.me["id"])
print("after walking north for 6 s: position", (me["x"], me["y"]))
s.check("player stopped at the contract boundary y = 142.4 (well wall 140 + radius 2.4)", abs(me["y"] - 142.4) < 0.11 and abs(me["x"] - baseline[0]) < 0.6, str((me["x"], me["y"])))
s.check("player did not enter the wall", me["y"] > 140.0)
for _ in range(15):
    s.send((1, 0), False)
    time.sleep(0.1)
time.sleep(0.3)
me2 = s.agent(s.me["id"])
s.check("tangential movement along the boundary works (x grew, y stayed at the boundary)", me2["x"] > me["x"] + 5 and abs(me2["y"] - 142.4) < 0.11, str((me2["x"], me2["y"])))
status = c.get("/status").json()
print("status keys:", sorted(status), "| tick", status.get("tick"))
s.release()
sys.exit(s.finish())
