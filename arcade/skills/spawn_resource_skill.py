import arcade
import random # Add this import

def execute(game, type="food", lx=500, ly=500, count=1):
    for _ in range(count):
        # Use standard random.randint
        off_x = 0 if count == 1 else random.randint(-20, 20)
        off_y = 0 if count == 1 else random.randint(-20, 20)
        
        color = arcade.color.APPLE_GREEN if type == "food" else arcade.color.AZURE
        size = 10 if type == "food" else 30
        
        sprite = arcade.SpriteSolidColor(size, size, color)
        sprite.center_x = (lx + off_x) * game.SCALE
        sprite.center_y = (ly + off_y) * game.SCALE
        
        if type == "food":
            game.food_list.append(sprite)
        else:
            game.water_list.append(sprite)
            
    game.sync_to_rag(f"Divine Intervention: {count} {type} spawned at {lx}, {ly}")