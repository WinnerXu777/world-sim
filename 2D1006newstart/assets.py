"""Asset import, animation frames, and game-native building assembly."""
from pathlib import Path
import json
import arcade
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ASSET_ROOT = ROOT.parent / 'myassets'
NATURE = ['oak', 'pine', 'boulders', 'berry_bush', 'campfire', 'well']


class Assets:
    def __init__(self):
        self.textures = {}
        manifest = json.loads((ASSET_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        for key in ['grass', 'paving_stone', 'barrel', 'crate', 'cart', 'tree_small', 'planter', 'fence']:
            self.textures[key] = arcade.load_texture(ASSET_ROOT / manifest['assets'][key]['path'])
        approved = json.loads((ASSET_ROOT / 'generated/approved.json').read_text(encoding='utf-8'))
        for key, entry in approved['accepted'].items():
            with Image.open(ASSET_ROOT / 'generated' / entry['path']) as source:
                tile = source.convert('RGBA').resize(tuple(entry['render_size']), Image.Resampling.NEAREST)
                self.textures[key] = arcade.Texture(tile, hash='eden-local-' + key)
        with Image.open(ASSET_ROOT / 'generated/nature_survival_atlas.png') as source:
            width, height = source.size
            for index, name in enumerate(NATURE):
                col, row = index % 3, index // 3
                im = source.crop((col*width//3, row*height//2, (col+1)*width//3, (row+1)*height//2)).convert('RGBA')
                # Ignore faint alpha padding when measuring; keep alpha on the retained pixels.
                bbox = im.getchannel('A').point(lambda p: 255 if p > 24 else 0).getbbox()
                if bbox is None:
                    raise ValueError(f'Empty generated sprite: {name}')
                self.textures[name] = arcade.Texture(im.crop(bbox), hash='eden-nature-' + name)
        self.character = {}
        for name in ['elven_adventurer', 'dungeon_stalker']:
            with Image.open(ASSET_ROOT / manifest['assets'][name]['path']) as source:
                for row, direction in enumerate(['south', 'west', 'east', 'north']):
                    self.character[name, direction] = [
                        arcade.Texture(source.crop((col*128, row*128, (col+1)*128, (row+1)*128)),
                                       hash=f'eden-{name}-{direction}-{col}') for col in range(3)]
        for color in ['brown', 'blue']:
            # Buildings are assembled from existing tile pieces, like a tilemap.
            house = Image.new('RGBA', (240, 336))
            ImageDraw.Draw(house).polygon([(120, 108), (24, 237), (216, 237)], fill=(190, 161, 124, 255))
            with Image.open(ASSET_ROOT / 'buildings/wall_plaster.png') as wall:
                for x in (0, 96, 192):
                    house.alpha_composite(wall.convert('RGBA'), (x, 224))
            with Image.open(ASSET_ROOT / f'props/gable_{color}.png') as roof:
                house.alpha_composite(roof.convert('RGBA'), (0, 0))
            with Image.open(ASSET_ROOT / 'props/door_arch.png') as door:
                house.alpha_composite(door.convert('RGBA'), (96, 224))
            with Image.open(ASSET_ROOT / 'props/window_square.png') as window:
                house.alpha_composite(window.convert('RGBA'), (24, 215))
                house.alpha_composite(window.convert('RGBA'), (168, 215))
            self.textures['cottage' if color == 'brown' else 'cottage_blue'] = arcade.Texture(house, hash='eden-house-' + color)

    def actor(self, name, direction='south', step=1):
        return self.character[name, direction][step]
