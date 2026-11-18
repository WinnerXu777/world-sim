import arcade
import math # Add this import

def execute(game, lx=500, ly=500, radius=200):
    # Convert logical units to screen pixels
    screen_radius = radius * game.SCALE
    center_x = lx * game.SCALE
    center_y = ly * game.SCALE
    
    # We iterate through a copy of the list so we can safely remove items
    for sprite in list(game.food_list) + list(game.water_list):
        # Standard Euclidean distance: sqrt((x2-x1)^2 + (y2-y1)^2)
        dist = math.sqrt((sprite.center_x - center_x)**2 + (sprite.center_y - center_y)**2)
        
        if dist < screen_radius:
            sprite.remove_from_sprite_lists()

    game.sync_to_rag(f"Catastrophe: Resources cleared within {radius} units of {lx}, {ly}")