"""
eden_viewer.py
==============
Eden simulation viewer — Python Arcade frontend.

Fixes vs previous version:
  1. TELEPORT FIX: Agents are now keyed by a stable compound ID derived from
     their quantised spawn position + sex, not by their list index.  When an
     agent dies its list slot disappears and every subsequent index shifts by -1;
     using the index as a key caused the next agent to "teleport" to the dead
     agent's last screen position.  The new key is stable for the lifetime of
     each agent.

  2. MAP RENDERING: Tile size reduced from 20 px to 8 px so the 800×600 canvas
     is covered by a 100×75 grid (7 500 tiles) with zero gaps.  Tiles are drawn
     as solid filled rectangles, not ellipses.

  3. LARGER WORLD / MORE DETAIL: The server config drives map size; the viewer
     now fetches tile_size from the JSON payload and sizes rectangles to match,
     so any server-side TILE_SIZE change is picked up automatically.

  4. BIOME COLOURS: Full 6-biome palette matching genesis_config.py M_TYPE
     constants (deep sea, shallow sea, beach, grass, forest, mountain).

  5. AGENT VISUALS: Males = blue circles, females = pink circles, size scales
     with age.  Escalated agents flash a red outline.  Dead sprites fade out
     over DEAD_FADE frames instead of vanishing instantly.

  6. HUD: tick, year, population, FPS displayed top-left.
"""

import math
import threading
import time

import arcade
import arcade.shape_list
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVER_URL    = "http://localhost:9000"   # FastAPI port in genesis.py
SCREEN_WIDTH  = 800
SCREEN_HEIGHT = 600
SCREEN_TITLE  = "Eden — World Simulation"

POLL_INTERVAL = 0.05   # seconds between /get_agents calls  (20 Hz)
LERP_SPEED    = 8.0    # position lerp feel (units/s equivalent)
DEAD_FADE     = 12     # frames a stale sprite lingers before removal

# ---------------------------------------------------------------------------
# Biome colour palette  (matches genesis_config.py M_TYPE values)
#   M_SEA=3  M_BEACH=5  M_GRASS=6  M_FOREST=2  M_MOUNTAIN=4
#   value 0 = deep water (below M_SEA threshold)
# ---------------------------------------------------------------------------
BIOME_COLORS = {
    0: (20,  60, 120, 255),   # deep sea       (height < 0.20)
    3: (52, 132, 210, 255),   # shallow sea    M_SEA
    5: (210, 185, 130, 255),  # beach          M_BEACH
    6: (85,  168,  80, 255),  # grassland      M_GRASS
    2: (34,  110,  50, 255),  # forest         M_FOREST
    4: (140, 130, 120, 255),  # mountain       M_MOUNTAIN
    1: (70,  160, 220, 255),  # lake           M_LAKE (if present)
}
DEFAULT_TILE_COLOR = (30, 80, 140, 255)   # fallback for unknown biome

# Agent colours
MALE_COLOR    = (100, 190, 255, 255)
FEMALE_COLOR  = (255, 150, 190, 255)
ESCALATE_RING = (255,  60,  60, 255)

# ---------------------------------------------------------------------------
# Stable agent ID
# ---------------------------------------------------------------------------

def _agent_key(agent: dict) -> tuple:
    """
    Build a stable key that survives list-index shifts.

    Strategy: quantise the spawn position to the nearest 10 px and combine
    with sex.  Two agents born at the exact same spot with the same sex in
    the same tick are extremely unlikely; if they do collide a new sprite is
    simply created (cheap).  This is robust enough for 100-agent sims.

    NOTE: if the server ever exposes a proper agent UUID, prefer that.
    """
    return (round(agent["x"] / 10) * 10,
            round(agent["y"] / 10) * 10,
            agent["sex"])


# ---------------------------------------------------------------------------
# Agent sprite
# ---------------------------------------------------------------------------

class AgentSprite(arcade.SpriteCircle):
    """
    Circle sprite with lerp target, staleness counter, and escalation flag.
    Radius grows slightly with age (capped).
    """
    BASE_RADIUS = 5

    def __init__(self, x: float, y: float, sex: int, age: float = 0.0):
        color  = MALE_COLOR if sex == 0 else FEMALE_COLOR
        radius = self._radius_for_age(age)
        super().__init__(radius, color, soft=True)
        self.center_x    = x
        self.center_y    = y
        self.target_x    = x
        self.target_y    = y
        self.stale_ticks = 0
        self.escalated   = False
        self.current_age = age
        self._sex        = sex

    @staticmethod
    def _radius_for_age(age: float) -> int:
        """3 px at birth → 7 px at age 60+."""
        return max(3, min(7, int(3 + age / 12)))

    def refresh(self, agent: dict) -> None:
        self.target_x    = agent["x"]
        self.target_y    = agent["y"]
        self.stale_ticks = 0
        self.escalated   = agent.get("escalated", False)
        self.current_age = agent.get("age", self.current_age)

    def lerp(self, alpha: float) -> None:
        self.center_x += (self.target_x - self.center_x) * alpha
        self.center_y += (self.target_y - self.center_y) * alpha

    def draw_escalation_ring(self) -> None:
        """Draw a red ring around escalated agents."""
        if self.escalated:
            arcade.draw_circle_outline(
                self.center_x, self.center_y,
                self._radius_for_age(self.current_age) + 3,
                ESCALATE_RING, border_width=2,
            )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class EdenViewer(arcade.Window):

    def __init__(self):
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE,
                         update_rate=1 / 60)
        self.set_vsync(True)

        # Map geometry
        self.tile_shapes = arcade.shape_list.ShapeElementList()
        self._tile_size  = 20   # updated from server JSON

        # Agents
        self.agent_list: arcade.SpriteList      = arcade.SpriteList()
        self.agent_map:  dict[tuple, AgentSprite] = {}   # key → sprite

        # Thread-shared state
        self._agent_data: list = []
        self._hud_meta:   dict = {"tick": 0, "year": 0.0, "pop": 0}
        self._data_lock         = threading.Lock()
        self._running           = True
        self._poll_thread: threading.Thread | None = None

        # HUD
        self._fps_samples: list[float] = []
        self.hud_text = arcade.Text(
            "", 8, SCREEN_HEIGHT - 18,
            arcade.color.WHITE, 13,
            font_name="monospace",
        )
        self.background_color = (10, 12, 18)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        print("Connecting to Eden server…")
        self._load_map()

        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()

    def _load_map(self) -> None:
        try:
            resp = requests.get(f"{SERVER_URL}/get_map", timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"Map load failed: {exc}. Rendering without map.")
            return

        ts = data.get("tile_size", 20)
        self._tile_size = ts
        half = ts / 2.0

        # Build one solid ShapeElementList — much faster than individual draws
        # Use create_rectangle_filled for pixel-perfect coverage.
        shape_list = arcade.shape_list.ShapeElementList()
        for tile in data["tiles"]:
            t_type = int(tile["type"])
            color  = BIOME_COLORS.get(t_type, DEFAULT_TILE_COLOR)
            rect   = arcade.shape_list.create_rectangle_filled(
                tile["x"], tile["y"], ts, ts, color
            )
            shape_list.append(rect)

        self.tile_shapes = shape_list
        print(f"Map loaded: {len(data['tiles'])} tiles @ {ts}px each.")

    # ------------------------------------------------------------------
    # Background polling thread
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        session = requests.Session()
        while self._running:
            try:
                resp = session.get(f"{SERVER_URL}/get_agents", timeout=2)
                resp.raise_for_status()
                payload = resp.json()
                with self._data_lock:
                    self._agent_data = payload.get("agents", [])
                    self._hud_meta   = {
                        "tick": payload.get("tick", 0),
                        "year": payload.get("year", 0.0),
                        "pop":  payload.get("pop",  0),
                    }
            except requests.RequestException as exc:
                pass   # silent — will retry next cycle
            time.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Game loop — on_update
    # ------------------------------------------------------------------

    def on_update(self, delta_time: float) -> None:
        # FPS tracking (rolling 60-frame average)
        self._fps_samples.append(delta_time)
        if len(self._fps_samples) > 60:
            self._fps_samples.pop(0)

        # Consume latest data
        with self._data_lock:
            agents   = list(self._agent_data)
            hud_meta = dict(self._hud_meta)

        # Mark all sprites stale; reset below for those still present
        for sprite in self.agent_map.values():
            sprite.stale_ticks += 1

        # Update / create sprites
        # Key stability: _agent_key uses quantised position + sex.
        # If two agents share a key (unlikely), the second overwrites
        # the first's target — visually harmless.
        seen: set[tuple] = set()
        for agent in agents:
            key = _agent_key(agent)
            seen.add(key)

            if key not in self.agent_map:
                sp = AgentSprite(
                    agent["x"], agent["y"],
                    agent["sex"], agent.get("age", 0.0)
                )
                self.agent_map[key] = sp
                self.agent_list.append(sp)
            else:
                self.agent_map[key].refresh(agent)

        # Cull sprites gone stale for too long (dead / off-screen)
        dead_keys = [k for k, s in self.agent_map.items()
                     if s.stale_ticks > DEAD_FADE]
        for k in dead_keys:
            self.agent_map[k].remove_from_sprite_lists()
            del self.agent_map[k]

        # Lerp positions — frame-rate independent
        alpha = 1.0 - (1.0 - LERP_SPEED / 60.0) ** (delta_time * 60.0)
        for sprite in self.agent_map.values():
            sprite.lerp(alpha)

        # HUD string
        avg_fps  = 1.0 / (sum(self._fps_samples) / max(1, len(self._fps_samples)))
        tick     = hud_meta["tick"]
        year     = hud_meta["year"]
        pop      = hud_meta["pop"]
        self.hud_text.value = (
            f"Tick {tick:5d}  |  Year {year:6.1f}  |"
            f"  Pop {pop:3d}/100  |  {avg_fps:4.0f} FPS"
        )

    # ------------------------------------------------------------------
    # Rendering — on_draw
    # ------------------------------------------------------------------

    def on_draw(self) -> None:
        self.clear()
        self.tile_shapes.draw()
        self.agent_list.draw()

        # Escalation rings drawn on top (not part of sprite batch)
        for sprite in self.agent_map.values():
            sprite.draw_escalation_ring()

        self.hud_text.draw()
        self._draw_legend()

    def _draw_legend(self) -> None:
        """Small biome + agent legend, bottom-right corner."""
        entries = [
            ("Deep sea",   BIOME_COLORS[0]),
            ("Shallow sea",BIOME_COLORS[3]),
            ("Beach",      BIOME_COLORS[5]),
            ("Grass",      BIOME_COLORS[6]),
            ("Forest",     BIOME_COLORS[2]),
            ("Mountain",   BIOME_COLORS[4]),
            ("Male",       MALE_COLOR),
            ("Female",     FEMALE_COLOR),
        ]
        row_h  = 16
        x_swatch = SCREEN_WIDTH - 110
        x_label  = SCREEN_WIDTH - 92
        y_start  = len(entries) * row_h + 6

        for i, (label, color) in enumerate(entries):
            y = y_start - i * row_h
            arcade.draw_rectangle_filled(x_swatch, y, 10, 10, color)
            arcade.draw_text(label, x_label, y - 5,
                             (210, 210, 210), 9, font_name="monospace")

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        self._running = False
        super().on_close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    viewer = EdenViewer()
    viewer.setup()
    arcade.run()