import random
import aiosqlite

class AgentSkills:
    def __init__(self, db_conn: aiosqlite.Connection):
        self.db = db_conn

    async def spawn_new_agent(self, name, x, y, current_tick, parents=None):
        """The 'Genesis' and 'Birth' skill."""
        lifespan_ticks = int(random.gauss(50, 15))
        lifespan_ticks = max(10, min(100, lifespan_ticks))
        
        p_a = parents[0] if parents else None
        p_b = parents[1] if parents else None

        await self.db.execute('''
            INSERT INTO agents (name, x, y, birth_tick, anticipated_age, parent_a, parent_b)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, x, y, current_tick, lifespan_ticks, p_a, p_b))
        await self.db.commit()
        return f"Agent {name} added to the world."

    async def update_lifecycles(self, current_tick):
        """The 'Grim Reaper' skill that runs every heartbeat."""
        await self.db.execute('''
            UPDATE agents 
            SET is_alive = 0, health = 0.0 
            WHERE is_alive = 1 
            AND (? - birth_tick) >= anticipated_age
        ''', (current_tick,))
        await self.db.commit()