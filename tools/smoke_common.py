"""Shared client for the live smoke tools (4-map world: village + smithy + lodge + west cottage).

Backend (fresh isolated data root, never a world you want to keep), all four maps placed:
  EDEN_PROFILE=gameplay EDEN_PORT=8013 EDEN_MAP=starter_village \\
  EDEN_MAP_FILES="world_data/maps2d/starter_village.json;world_data/maps2d/smith_interior.json;world_data/maps2d/village_lodge_interior.json;world_data/maps2d/west_cottage_interior.json" \\
  EDEN_MAP_ORIGINS='{"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}' \\
  EDEN_DATA_ROOT=.runtime/<guid> python at_the_beginning/map_test.py
EDEN_SMOKE_PORT overrides the port (default 8013).

Nothing here assumes where a resident is: the maps (rectangles, anchors, portals) come from /bootstrap and /map_file, the player is
picked by position, and ``go_to_map`` walks to the right portal from wherever the player stands (village or any interior).
"""
import json
import math
import os
import time
import uuid

import httpx

BASE = f"http://127.0.0.1:{os.environ.get('EDEN_SMOKE_PORT', '8013')}"


class Smoke:
    def __init__(self, name, timeout=30):
        self.name = name
        self.results = []
        self.c = httpx.Client(base_url=BASE, timeout=timeout)
        self.H = {"X-Eden-Session": self.c.get("/bootstrap").json()["session_capability"]}
        self.claim_body = {}
        self.me = None
        self.seq = 0
        self.world_epoch = None
        self.maps = {}      # map_id -> {rect, origin, anchors {id: (x, y)}, portals [...]}
        self.primary = None

    # reporting ------------------------------------------------------------
    def check(self, label, ok, detail=""):
        self.results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)
        return bool(ok)

    def finish(self):
        print(f"\n{sum(self.results)}/{len(self.results)} checks passed", flush=True)
        return 0 if all(self.results) else 1

    # world ------------------------------------------------------------------
    def new_game(self):
        reply = self.c.post("/session/new", json={"name": self.name}, headers=self.H).json()
        boot = self.c.get("/bootstrap").json()
        self.world_epoch = boot["world_epoch"]
        self.load_maps(boot)
        return reply

    def load_maps(self, boot):
        self.maps = {}
        for block in boot["maps"]:
            ox, oy = block["origin"]
            upt, (w, h) = block["units_per_tile"], block["size_tiles"]
            data = json.loads(self.c.get(block["url"]).content)
            self.maps[block["map_id"]] = {
                "rect": (ox, oy, ox + w * upt, oy + h * upt), "origin": (ox, oy), "primary": block["primary"],
                "anchors": {a["id"]: (a["position"][0] + ox, a["position"][1] + oy) for a in data["anchors"]},
                "portals": data.get("portals", [])}
            if block["primary"]:
                self.primary = block["map_id"]
        return self.maps

    def map_at(self, x, y):
        for map_id, info in self.maps.items():
            x0, y0, x1, y1 = info["rect"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                return map_id
        return None

    def anchor(self, anchor_id):
        for info in self.maps.values():
            if anchor_id in info["anchors"]:
                return info["anchors"][anchor_id]
        raise KeyError(anchor_id)

    def portal(self, portal_id):
        for map_id, info in self.maps.items():
            for portal in info["portals"]:
                if portal["id"] == portal_id:
                    return map_id, portal
        raise KeyError(portal_id)

    # residents -----------------------------------------------------------------
    def agents(self):
        return self.c.get("/frame").json()["agents"]

    def agent(self, key):
        return next(a for a in self.agents() if a["id"] == key or a["name"] == key or a.get("roster_key") == key)

    def inspect(self, key):
        return self.c.get(f"/god/inspect/{self.agent(key)['id']}").json()

    def coin(self, agent):
        reply = self.c.get(f"/inventory/owner/human/{agent['id']}").json()
        return int((reply.get("inventory") or {}).get("currency", 0))

    def pick_player(self, goal_anchor="village:door_smith", min_coin=0):
        """The non-smith resident to possess: one with at least ``min_coin`` coin, preferring those standing in the primary map,
        the nearest to ``goal_anchor`` (never a fixed name; a resident may be indoors or too poor to commission)."""
        gx, gy = self.anchor(goal_anchor)
        pool = [a for a in self.agents() if a.get("roster_key") != "smith" and self.coin(a) >= min_coin]
        outside = [a for a in pool if self.map_at(a["x"], a["y"]) == self.primary]
        return min(outside or pool, key=lambda a: math.hypot(a["x"] - gx, a["y"] - gy))

    # possession -----------------------------------------------------------------
    def claim(self, target=None):
        target = target or self.me
        reply = self.c.post("/control/claim", json={"controller_id": "smoke", "target_kind": "human", "target_id": target["id"]}, headers=self.H).json()
        self.claim_body = reply
        self.world_epoch = reply.get("world_epoch", self.world_epoch)
        self.me = target
        return reply

    def release(self):
        return self.c.post("/control/release", json={"controller_id": "smoke"}, headers=self.H).json()

    def send(self, move=(0, 0), sprint=False):
        self.seq += 1
        env = {k: self.claim_body[k] for k in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
        self.c.post("/control/input", json={**env, "controller_id": "smoke", "seq": self.seq, "move": {"x": move[0], "y": move[1]},
                                            "buttons": {"sprint": sprint}}, headers=self.H)

    def position(self):
        a = self.agent(self.me["id"])
        return a["x"], a["y"]

    def walk_to(self, goal, tolerance=3.0, seconds=20.0, sprint=True):
        """Steer straight at ``goal`` (the backend slides along walls). Returns the remaining distance."""
        start = time.time()
        while time.time() - start < seconds:
            x, y = self.position()
            dx, dy = goal[0] - x, goal[1] - y
            dist = math.hypot(dx, dy)
            if dist <= tolerance:
                break
            self.send((dx / dist, dy / dist), sprint)
            time.sleep(0.08)
        self.send()
        time.sleep(0.2)
        x, y = self.position()
        return math.hypot(goal[0] - x, goal[1] - y)

    # commands ---------------------------------------------------------------------
    def command(self, path, possessed=False, **body):
        payload = {"protocol_version": 1, "world_epoch": self.world_epoch, "controller_id": "smoke", "command_id": str(uuid.uuid4()), **body}
        if possessed:
            payload["possession_epoch"] = self.claim_body["possession_epoch"]
        response = self.c.post(path, json=payload, headers=self.H)
        if response.status_code == 400:
            return response.json()
        result = {}
        for _ in range(80):
            time.sleep(0.1)
            if possessed:
                self.send()  # possession is released after 5 s without input
            result = self.c.get(f"/commands/{payload['command_id']}").json()
            if result.get("status") != "received":
                return result
        return result

    def take_portal(self, portal_id):
        map_id, portal = self.portal(portal_id)
        x, y = self.anchor(portal["from_anchor"])
        self.walk_to((x, y + 4.0), 5.0, 25.0)
        return self.command("/control/portal", possessed=True, portal_id=portal_id)

    def go_to_map(self, target_map, via=None, attempts=4):
        """Walk and portal until the player stands in ``target_map`` (interiors lead out to the village first)."""
        for _ in range(attempts):
            here = self.map_at(*self.position())
            if here == target_map:
                return True
            if here == self.primary:  # village -> the portal that leads to the target
                found = [(m, p) for m, info in self.maps.items() for p in info["portals"] if m == self.primary and p["to_map"] == target_map]
                if not found:
                    return False
                if via:
                    self.walk_to(self.anchor(via), 6.0, 25.0)
                self.take_portal(found[0][1]["id"])
            else:  # inside another interior: out through its portal to the village
                found = [p for p in self.maps[here]["portals"] if p["to_map"] == self.primary] if here else []
                if not found:
                    return False
                self.take_portal(found[0]["id"])
        return self.map_at(*self.position()) == target_map

    def to_smith(self):
        """From wherever the player is: into the smithy and next to Brann. Returns (ok, distance to Brann)."""
        if self.map_at(*self.position()) == self.primary:
            self.walk_to(self.anchor("village:talk_square"), 8.0, 25.0)  # open ground first, then the door
        ok = self.go_to_map("smith_interior", via="village:approach_smith")
        smith = self.agent("smith")
        remaining = self.walk_to((smith["x"] + 8.0, smith["y"] + 4.0), 4.0, 15.0)
        return ok, remaining

    # smith diagnostics ----------------------------------------------------------------
    def smith_trace(self, label):
        view = self.inspect("smith")
        player = self.position()
        sx, sy = view["position"]
        line = {"label": label, "tick": view.get("tick"), "smith_map": view["map_id"], "smith_pos": [round(sx, 1), round(sy, 1)],
                "routine": view["routine"], "goal_anchor": view["goal_anchor"], "at_anchor": view["at_anchor"],
                "player_map": self.map_at(*player), "player_pos": [round(player[0], 1), round(player[1], 1)],
                "distance": round(math.hypot(player[0] - sx, player[1] - sy), 1),
                "orders": [(o.get("order_id"), o.get("state")) for o in view.get("commission_orders", [])]}
        print("TRACE", json.dumps(line), flush=True)
        return line

    def wait_ready(self, seconds=120):
        t0 = time.time()
        while time.time() - t0 < seconds:
            self.send()
            state = self.c.get("/commission/state", params={"controller_id": "smoke"}).json()
            if state.get("orders") and state["orders"][-1]["state"] == "ready":
                return state["orders"][-1]
            time.sleep(0.25)
        return None
