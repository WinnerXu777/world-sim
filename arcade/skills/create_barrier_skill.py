import arcade

def execute(game, orientation="vertical", position=500, thickness=40):
    """
    orientation: 'vertical' or 'horizontal'
    position: The logical coordinate (0-1000) where the line is drawn
    """
    for i in range(0, 1000, 40):
        wall = arcade.SpriteSolidColor(thickness, 40, arcade.color.DARK_SLATE_GRAY)
        
        if orientation == "vertical":
            wall.center_x = position * game.SCALE
            wall.center_y = i * game.SCALE
        else:
            wall.center_x = i * game.SCALE
            wall.center_y = position * game.SCALE
            
        game.barrier_list.append(wall) # Assuming you add a barrier_list
    
    game.sync_to_rag(f"Geography Change: A {orientation} barrier was erected at {position}")