import torch
import aiosqlite
# The "Differential Logic" Pattern
# 1. Initialize the Live and Snapshot tensors
mem_tensor = initialize_mem_tensor()
last_saved_tensor = mem_tensor.clone() # The 'Shadow' copy

async def sync_to_db(db, mem_tensor, last_saved_tensor):
    # 2. Find which rows have changed in ANY important column
    # (e.g., check columns 1 to 5: Alive, X, Y, Hunger, etc.)
    # .any(dim=1) returns True if ANY column in that row is different
    diff_mask = torch.abs(mem_tensor[:, 1:6] - last_saved_tensor[:, 1:6]) > 1e-5
    dirty_indices = torch.where(diff_mask.any(dim=1))[0]

    if len(dirty_indices) == 0:
        return # Nothing to do!

    # 3. Batch update only the 'Dirty' rows
    for idx in dirty_indices:
        agent_row = mem_tensor[idx]
        await db.execute(
            "UPDATE agents SET x=?, y=?, hunger=? WHERE id=?",
            (agent_row[2].item(), agent_row[3].item(), agent_row[4].item(), agent_row[0].item())
        )
    
    await db.commit()

    # 4. Update the Snapshot so the next check is fresh
    last_saved_tensor[dirty_indices] = mem_tensor[dirty_indices].clone()
    
    
    
# Create a list of tuples for all dirty agents
update_data = [
    (row[2].item(), row[3].item(), row[4].item(), row[0].item())
    for row in mem_tensor[dirty_indices]
]

# One command to update them all
await db.executemany(
    "UPDATE agents SET x=?, y=?, hunger=? WHERE id=?", 
    update_data
)