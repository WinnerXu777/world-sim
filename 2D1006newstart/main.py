"""Eden 2D: a native desktop starting point, not a browser or Godot project."""
from __future__ import annotations
import argparse
from functools import lru_cache
import math
from pathlib import Path
import random
import sys

import arcade
from PIL import Image
from assets import Assets
from backend import EdenObserver
from world import World, Entity, TILE, COLS, ROWS, WIDTH, HEIGHT

ROOT = Path(__file__).resolve().parent
CREAM = (232, 227, 201)
MUTED = (156, 173, 157)
GOLD = (223, 182, 103)
GREEN = (130, 175, 112)
DARK = (22, 32, 29)


@lru_cache(maxsize=768)
def text_object(text, x, y, size, color, bold, width):
    return arcade.Text(text, x, y, color, size, font_name='Segoe UI', bold=bold,
                       width=width or None, multiline=bool(width))


def label(text, x, y, size=12, color=CREAM, bold=False, width=0):
    text_object(str(text), x, y, size, color, bold, width).draw()


def box(x, y, w, h, color):
    arcade.draw_lbwh_rectangle_filled(x, y, w, h, color)


class EdenWindow(arcade.Window):
    def __init__(self, args):
        super().__init__(1400, 900, 'Eden | 2D1006newstart', resizable=True,
                         antialiasing=False, vsync=True, visible=not args.capture,
                         center_window=True)
        self.set_minimum_size(1280, 900)
        self.args = args
        self.assets = Assets()
        self.world = World()
        if args.scene == 'coast':
            self.world.player_x, self.world.player_y = 39*TILE, 19*TILE
        self.keys = set()
        self.zoom = 1.05
        self.paused = False
        self.help_open = False
        self.dialog = False
        self.moving = False
        self.frame_time = 0
        self.capture_age = 0
        self.backend = EdenObserver(args.backend) if args.backend else None
        self.observer_error = None
        self.observer_tick = None
        self.observer_count = 0
        self.remote_entities = []
        self.remote_actors = []
        self.world_camera = arcade.Camera2D(window=self)
        self.ui_camera = arcade.Camera2D(window=self)
        self.ground = arcade.SpriteList()
        self.water = []
        self.sand = []
        self.decor = arcade.SpriteList()
        self.objects = arcade.SpriteList()
        self.player = arcade.Sprite(self.assets.actor('elven_adventurer'), scale=0.72)
        self._build_world()
        self.on_resize(self.width, self.height)

    def _build_world(self):
        self.ground.clear()
        self.water.clear()
        self.sand.clear()
        self.decor.clear()
        self.objects.clear()
        for row in range(ROWS):
            for col in range(COLS):
                kind = self.world.tile(col, row)
                x, y = (col+0.5)*TILE, -(row+0.5)*TILE
                if kind == 'water':
                    self.water.append((x, y))
                    self.ground.append(arcade.Sprite(self.assets.textures['water'], center_x=x, center_y=y))
                elif kind == 'sand':
                    self.sand.append((x, y))
                    self.ground.append(arcade.Sprite(self.assets.textures['sand'], center_x=x, center_y=y))
                else:
                    tile = arcade.Sprite(self.assets.textures['paving_stone' if kind == 'path' else 'grass'],
                                         center_x=x, center_y=y)
                    self.ground.append(tile)
        minimap = Image.new('RGB', (COLS, ROWS))
        palette = {'water': (45, 90, 101), 'sand': (165, 151, 108),
                   'path': (135, 134, 109), 'grass': (57, 85, 49)}
        for row in range(ROWS):
            for col in range(COLS):
                minimap.putpixel((col, row), palette[self.world.tile(col, row)])
        self.minimap_texture = arcade.Texture(minimap.convert('RGBA'), hash='eden-minimap')
        rng = random.Random(1006)
        for i in range(160):
            x, y = rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT)
            if self.world.tile(int(x/TILE), int(y/TILE)) == 'grass':
                # Tiny game-native flowers break up the repeating ground pattern.
                self.decor.append(arcade.SpriteSolidColor(3, 3, center_x=x, center_y=-y,
                    color=rng.choice([(176, 157, 76), (110, 138, 61), (206, 196, 148)])))
        self.entity_sprites = {}
        for entity in self.world.entities:
            if entity.kind == 'resident':
                sprite = arcade.Sprite(self.assets.actor('dungeon_stalker'), scale=0.72)
            else:
                texture = self.assets.textures[entity.kind]
                target_height = {'oak': 185, 'pine': 205, 'boulders': 73, 'berry_bush': 66,
                                 'campfire': 84, 'well': 145, 'cottage': 288, 'cottage_blue': 288}.get(entity.kind, texture.height)
                sprite = arcade.Sprite(texture, scale=target_height/texture.height)
            sprite.center_x = entity.x
            sprite.bottom = -entity.y
            self.entity_sprites[entity.id] = sprite
            self.objects.append(sprite)
        self.objects.append(self.player)
        self._place_player()

    def _place_player(self):
        self.player.center_x = self.world.player_x
        self.player.bottom = -self.world.player_y - 4
        self.objects.sort(key=lambda sprite: sprite.bottom, reverse=True)

    def on_resize(self, width, height):
        super().on_resize(width, height)
        if not hasattr(self, 'world_camera'):
            return
        self.panel_width = 300
        self.game_width = max(300, width-self.panel_width)
        self.world_camera.viewport = arcade.LBWH(0, 82, self.game_width, max(100, height-146))
        self.world_camera.scissor = self.world_camera.viewport
        self.world_camera.projection = arcade.LBWH(-self.game_width/2, -(height-146)/2, self.game_width, height-146)
        self.ui_camera.viewport = arcade.LBWH(0, 0, width, height)
        self.ui_camera.projection = arcade.LBWH(-width/2, -height/2, width, height)
        self.ui_camera.position = (width/2, height/2)
        self.world_camera.zoom = self.zoom

    def _camera(self):
        self.world_camera.zoom = self.zoom
        self.world_camera.position = (self.world.player_x, -self.world.player_y+105)

    def on_draw(self):
        self.clear(DARK)
        self._camera()
        self.world_camera.use()
        self.ground.draw(pixelated=True)
        camera_x, camera_y = self.world_camera.position
        view_w = self.game_width/self.zoom + 80
        view_h = self.height/self.zoom + 80
        for x, y in self.sand:
            if abs(x-camera_x) < view_w/2 and abs(y-camera_y) < view_h/2:
                box(x-20, y-16, 14, 2, (203, 184, 130, 80))
        for x, y in self.water:
            if abs(x-camera_x) < view_w/2 and abs(y-camera_y) < view_h/2:
                offset = 5 * math.sin(self.frame_time*0.7 + x*0.02 + y*0.01)
                box(x-12+offset, y+7, 16, 2, (109, 181, 181, 90))
        self.decor.draw(pixelated=True)
        if self.backend:
            self._draw_remote()
        else:
            # Small contact shadows, drawn before all upright sprites.
            for entity in self.world.entities:
                if abs(entity.x-camera_x) < view_w/2 and abs(-entity.y-camera_y) < view_h/2:
                    arcade.draw_ellipse_filled(entity.x, -entity.y+3, 38, 12, (24, 41, 20, 85))
            self.objects.draw(pixelated=True)
            nearest = self.world.nearest()
            if nearest and not self.paused:
                arcade.draw_ellipse_outline(nearest.x, -nearest.y, 54, 17, GOLD, border_width=2)
        self.ui_camera.use()
        self._draw_ui()

    def _draw_ui(self):
        h, gw = self.height, self.game_width
        box(0, h-64, gw, 64, (20, 31, 28))
        box(0, h-65, gw, 1, (71, 89, 67))
        label('E D E N', 26, h-38, 23, CREAM, True)
        label('THE FIRST SETTLEMENT', 163, h-34, 10, MUTED)
        mode = 'EDEN OBSERVER' if self.backend else 'LOCAL PLAYABLE PROTOTYPE'
        label(mode, gw-263, h-34, 10, GOLD)
        box(0, 0, gw, 82, (20, 31, 28))
        box(0, 81, gw, 1, (71, 89, 67))
        nearest = self.world.nearest() if not self.backend else None
        if self.backend:
            hint = 'Read-only live world. WASD pans the camera.'
        elif nearest:
            hint = f'[ E ]  {nearest.label}'
        else:
            hint = 'Explore the village. Press E near a person or resource.'
        label(hint, 26, 51, 13, GOLD)
        label('WASD / arrows  Move     Shift  Run     E  Interact     B  Eat     F5 / F9  Save / load     H  Help',
              26, 22, 11, MUTED)

        px = gw+23
        box(gw, 0, 300, h, (27, 39, 35))
        box(gw, 0, 1, h, (81, 98, 75))
        label('FIELD NOTES', px, h-40, 12, GOLD, True)
        label('First evening in Eden', px, h-71, 19, CREAM)
        label('A village, a fire, a beginning.', px, h-97, 11, MUTED)
        label('YOU', px, h-143, 10, GOLD, True)
        if self.backend:
            label(f'Tick: {self.observer_tick or 0}', px, h-172, 14)
            label(f'Visible actors: {len(self.remote_actors)}', px, h-197, 12, MUTED)
            label('Observer mode preserves backend state.', px, h-224, 11, MUTED, width=251)
        else:
            label('Traveller', px, h-171, 16)
            self._bar(px, h-200, 'Health', self.world.health, GREEN)
            self._bar(px, h-242, 'Hunger', self.world.hunger, GOLD)
        box(px, h-277, 252, 1, (62, 81, 65))
        label('INVENTORY', px, h-307, 10, GOLD, True)
        for index, (name, count) in enumerate(self.world.inventory.items()):
            y = h-341-index*29
            label(name.title(), px, y, 13, MUTED)
            label(str(count), px+220, y, 14, CREAM, True)
        label('FIRST TASK', px, h-455, 10, GOLD, True)
        if self.backend:
            quest = 'Watching the authoritative Eden simulation. Local gathering and saving are disabled.'
        elif self.world.quest_done:
            quest = 'Complete! The campfire is ready. Keep exploring, gathering, and building your stock.'
        else:
            quest = 'Speak to Mira near the fire. Gather 3 wood and 2 stone, then press E at the campfire.'
        label(quest, px, h-484, 12, CREAM, width=248)
        if not self.backend and not self.world.quest_done:
            label(f'Wood {min(3,self.world.inventory["wood"])}/3   Stone {min(2,self.world.inventory["stone"])}/2',
                  px, h-563, 12, GOLD)
        self._minimap(px, 133, 252, 160)
        label('RECENT EVENT', px, 106, 9, GOLD, True)
        message = self.observer_error or 'Connected to Eden.' if self.backend else self.world.events[-1]
        label(message[:145], px, 77, 11, MUTED, width=248)
        if self.dialog and not self.backend:
            dw = min(650, gw-60)
            box((gw-dw)/2, 111, dw, 120, (20, 31, 28, 245))
            label('MIRA', (gw-dw)/2+22, 203, 11, GOLD, True)
            label(self.world.events[-1], (gw-dw)/2+22, 172, 14, CREAM, width=dw-44)
            label('E / Enter to close', (gw-dw)/2+22, 128, 10, MUTED)
        if self.paused or self.help_open:
            box(0, 82, gw, h-146, (13, 22, 19, 205))
            cx = gw/2-210
            label('Paused' if self.paused else 'Your first steps', cx, h/2+125, 30, CREAM, True)
            controls = ['WASD or arrow keys: walk', 'Shift: run  |  E: interact', 'B: eat one berry',
                        'F5: save  |  F9: load', 'Mouse wheel or +/-: zoom', 'F12: screenshot',
                        'Escape: pause / resume  |  H: help']
            for i, line in enumerate(controls):
                label(line, cx, h/2+73-i*27, 14, MUTED)

    def _bar(self, x, y, name, value, color):
        label(name, x, y+5, 11, MUTED)
        label(str(round(value)), x+222, y+5, 11, CREAM)
        box(x, y-11, 252, 5, (16, 26, 23))
        box(x, y-11, 252*value/100, 5, color)

    def _minimap(self, x, y, w, h):
        label('THE VILLAGE', x, y+h+13, 9, GOLD, True)
        box(x, y, w, h, (17, 29, 24))
        arcade.draw_texture_rect(self.minimap_texture, arcade.LBWH(x, y, w, h), pixelated=True)
        for entity in self.world.entities:
            if entity.kind.startswith('cottage'):
                box(x+entity.x/WIDTH*w-5, y+h-entity.y/HEIGHT*h, 10, 7, GOLD)
        arcade.draw_circle_filled(x+self.world.player_x/WIDTH*w, y+h-self.world.player_y/HEIGHT*h, 3, CREAM)

    def _sync_backend(self):
        snapshot, self.observer_error = self.backend.read()
        if snapshot is None:
            return
        bootstrap, frame = snapshot['bootstrap'], snapshot['frame']
        self.observer_tick = frame.get('tick', 0)
        info = bootstrap.get('world', {})
        width, height = max(1, info.get('width', WIDTH)), max(1, info.get('height', HEIGHT))
        sx, sy = WIDTH/width, HEIGHT/height
        def position(item):
            return float(item.get('x', 0))*sx, float(item.get('y', 0))*sy
        self.remote_entities = [(item, position(item)) for item in bootstrap.get('map', {}).get('entities', [])]
        self.remote_actors = [(item, position(item)) for item in frame.get('humans', []) + frame.get('animals', [])]
        if self.observer_count == 0 and self.remote_actors:
            self.world.player_x, self.world.player_y = self.remote_actors[0][1]
        self.observer_count += 1

    def _draw_remote(self):
        mapping = {'forest': 'oak', 'mountain': 'boulders', 'house': 'cottage', 'village': 'cottage',
                   'farm': 'berry_bush', 'well': 'well', 'storage_case': 'crate'}
        visible = []
        cx, cy = self.world_camera.position
        for item, (x, y) in self.remote_entities:
            name = mapping.get(item.get('typeLabel') or item.get('type'))
            if name and abs(x-cx) < self.game_width/self.zoom and abs(-y-cy) < self.height/self.zoom:
                visible.append((y, x, name, False))
        for item, (x, y) in self.remote_actors:
            if abs(x-cx) < self.game_width/self.zoom and abs(-y-cy) < self.height/self.zoom:
                visible.append((y, x, 'elven_adventurer', True))
        for y, x, name, actor in sorted(visible):
            if actor:
                texture, height = self.assets.actor(name), 88
            else:
                texture = self.assets.textures[name]
                height = {'oak': 150, 'cottage': 240, 'well': 120}.get(name, 70)
            width = height*texture.width/texture.height
            arcade.draw_texture_rect(texture, arcade.LBWH(x-width/2, -y, width, height), pixelated=True)

    def on_update(self, dt):
        self.capture_age += dt
        self.frame_time += dt
        if not self.paused and not self.help_open and not self.dialog:
            dx = int(bool(self.keys & {arcade.key.D, arcade.key.RIGHT})) - int(bool(self.keys & {arcade.key.A, arcade.key.LEFT}))
            dy = int(bool(self.keys & {arcade.key.S, arcade.key.DOWN})) - int(bool(self.keys & {arcade.key.W, arcade.key.UP}))
            if self.backend:
                self.world.player_x = max(0, min(WIDTH, self.world.player_x + dx*300*dt))
                self.world.player_y = max(0, min(HEIGHT, self.world.player_y + dy*300*dt))
            else:
                self.moving = self.world.move(dx, dy, dt, bool(self.keys & {arcade.key.LSHIFT, arcade.key.RSHIFT}))
                self.world.update(dt)
                step = [0, 1, 2, 1][int(self.frame_time*7)%4] if self.moving else 1
                self.player.texture = self.assets.actor('elven_adventurer', self.world.facing, step)
                self._place_player()
        if self.backend and int(self.frame_time*5) != getattr(self, '_poll_mark', -1):
            self._poll_mark = int(self.frame_time*5)
            self._sync_backend()
        if self.args.capture and self.capture_age > (3 if self.backend else 0.7):
            self.on_draw()
            path = Path(self.args.capture).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            arcade.get_image().save(path)
            print(f'Captured {path}')
            self.close()

    def on_key_press(self, symbol, modifiers):
        self.keys.add(symbol)
        if symbol == arcade.key.ESCAPE:
            if self.dialog:
                self.dialog = False
            else:
                self.paused = not self.paused
        elif symbol == arcade.key.H:
            self.help_open = not self.help_open
        elif symbol in (arcade.key.E, arcade.key.ENTER) and not self.backend and not self.paused and not self.help_open:
            if self.dialog:
                self.dialog = False
            else:
                self.world.interact()
                self.dialog = self.world.talking
                self.world.talking = False
        elif symbol == arcade.key.B and not self.backend and not self.paused:
            self.world.eat()
        elif symbol == arcade.key.F5 and not self.backend:
            try:
                self.world.save(ROOT / 'saves/world.json')
                self.world.say('Local world saved. Press F9 to continue it.')
            except OSError as exc:
                self.world.say(f'Save failed: {exc}')
        elif symbol == arcade.key.F9 and not self.backend:
            try:
                self.world = World.load(ROOT / 'saves/world.json')
                self.dialog = False
                self._build_world()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.world.say(f'Cannot load save: {exc}')
        elif symbol == arcade.key.F12:
            self.on_draw()
            path = ROOT / 'screenshots/latest.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            arcade.get_image().save(path)
            self.world.say('Screenshot saved to screenshots/latest.png')
        elif symbol in (arcade.key.EQUAL, arcade.key.PLUS):
            self.zoom = min(2.2, self.zoom+0.15)
        elif symbol == arcade.key.MINUS:
            self.zoom = max(0.65, self.zoom-0.15)

    def on_key_release(self, symbol, modifiers):
        self.keys.discard(symbol)

    def on_deactivate(self):
        self.keys.clear()

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        self.zoom = max(0.65, min(2.2, self.zoom+scroll_y*0.1))

    def on_close(self):
        if self.backend:
            self.backend.close()
        super().on_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', help='Optional read-only Eden URL, e.g. http://127.0.0.1:8002')
    parser.add_argument('--capture', help='Render one real GPU frame to this PNG and exit')
    parser.add_argument('--scene', choices=['village', 'coast'], default='village', help='Starting camera area')
    args = parser.parse_args()
    EdenWindow(args)
    arcade.run()


if __name__ == '__main__':
    main()
