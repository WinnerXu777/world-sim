def export_telemetry_frame(mem_tensor, tick):
    # 1. Filter for living agents only
    alive_mask = mem_tensor[:, COL_IS_ALIVE] == 1
    living_data = mem_tensor[alive_mask]
    
    # 2. Extract only the columns the Arcade needs (X, Y, Hunger, etc.)
    # No need to send internal 'LoRA' or 'Last_Inference' weights to the viewer
    view_data = living_data[:, [COL_X, COL_Y, COL_HUNGER, COL_SEX]]
    
    # 3. Stream out as JSON
    frame = {
        "t": tick,
        "a": view_data.tolist() # Convert only the small slice to Python list
    }
    return json.dumps(frame) + "\n"