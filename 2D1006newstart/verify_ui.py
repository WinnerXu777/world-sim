"""Exercise actual window callbacks and capture their OpenGL result."""
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import arcade
import main

root = Path(__file__).resolve().parent
scratch = root / 'tests/.tmp/ui-smoke'
assert scratch.resolve().is_relative_to(root)
scratch.mkdir(parents=True, exist_ok=True)
args = Namespace(capture=str(root/'screenshots/ui-smoke.png'), backend=None, scene='village')
window = main.EdenWindow(args)
try:
    start = window.world.player_x
    window.on_key_press(arcade.key.D, 0)
    for _ in range(12):
        window.on_update(0.04)
    window.on_key_release(arcade.key.D, 0)
    assert window.world.player_x > start + 50, 'movement callback did not move'
    window.on_key_press(arcade.key.ESCAPE, 0)
    paused_x = window.world.player_x
    window.on_key_press(arcade.key.D, 0)
    window.on_update(0.04)
    window.on_key_release(arcade.key.D, 0)
    assert window.world.player_x == paused_x, 'pause did not stop movement'
    window.on_key_press(arcade.key.ESCAPE, 0)
    with patch.object(main, 'ROOT', scratch):
        window.on_key_press(arcade.key.F5, 0)
        saved_x = window.world.player_x
        window.world.player_x += 20
        window.on_key_press(arcade.key.F9, 0)
        assert window.world.player_x == saved_x, 'load did not restore position'
    mira = next(e for e in window.world.entities if e.id == 'mira')
    window.world.player_x, window.world.player_y = mira.x, mira.y-55
    window._place_player()
    window.on_key_press(arcade.key.E, 0)
    assert window.dialog and window.world.quest_started, 'dialogue did not start'
    window.on_draw()
    arcade.get_image().save(root/'screenshots/dialogue.png')
    window.on_key_press(arcade.key.E, 0)
    assert not window.dialog, 'dialogue did not close'
    window.on_key_press(arcade.key.H, 0)
    window.on_draw()
    arcade.get_image().save(root/'screenshots/help.png')
    window.on_key_press(arcade.key.H, 0)
    old_zoom = window.zoom
    window.on_mouse_scroll(100, 100, 0, 1)
    assert window.zoom > old_zoom
    window.on_resize(1400, 900)
    print('UI smoke passed: movement, pause, save/load, dialogue, help, zoom, resize')
finally:
    window.close()
