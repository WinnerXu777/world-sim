"""Instantiate an authored map's interactive entities as real tensor entities.

The map file's entity id becomes the backend entity id: it is written into ``engine._entity_uid_by_slot`` before
``Engine._assign_missing_ids`` runs (which only fills empty ids), so it survives save/restore like any other id.
Decorative entities (``interactive: false``) stay in the map file and are never instantiated. Storage kinds become
``M_STORAGE_CASE`` containers; every other kind becomes the inert ``M_MAP_OBJECT`` (no geometry in ``MAP_GEO``, so
schedule navigation, shelter and occupancy queries never see it). Walls are not created here: they reach the
movement contract through ``map_contract`` and are not tensor entities.

With ``EDEN_MAP_RESOURCES=1`` (G-005, default off) entities whose kind carries a resource, or that declare resource keys, become real
resource rows instead (well, farm, resource node, shelter) with a ``MAP_GEO`` circle, and storage entities receive their declared
``stock``; see ``systems/map/resources.py``. ``upgrade_authored_entities`` brings rows of an older save up to the same shape.
"""
try:
    import genesis_config as cfg
    import instincts_and_tools as iat
    import map_geo
    from systems.map import resources
    from systems.movement.map_contract import STORAGE_ENTITY_KINDS, placed_group
    from harness.numerics import spaces_enabled
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import instincts_and_tools as iat
    from at_the_beginning import map_geo
    from at_the_beginning.systems.map import resources
    from at_the_beginning.systems.movement.map_contract import STORAGE_ENTITY_KINDS, placed_group
    from at_the_beginning.harness.numerics import spaces_enabled

STORAGE_RADIUS = 4.0  # MAP_GEO circle for map storage containers (the engine's own starter case uses 14)
OBJECT_SCALE = 2.0


def entity_type_for_kind(kind):
    return cfg.M_STORAGE_CASE if kind in STORAGE_ENTITY_KINDS else cfg.M_MAP_OBJECT


def instantiate_authored_entities(engine, map_name):
    """Create the map group's interactive entities. Idempotent: ids already present are skipped.

    The first storage entity of the primary map becomes the starter container (seeded like the engine's own
    starter case, and recorded in ``_starter_storage_case_entity_id`` so the engine does not spawn another).
    Returns the list of entity ids created by this call.
    """
    created = []
    present = {uid for uid in engine._entity_uid_by_slot if uid}
    use_resources = resources.enabled()
    with_spaces = spaces_enabled()
    for index, entry in enumerate(placed_group(map_name)):
        for entity in entry["entities"]:
            if not entity["interactive"] or entity["id"] in present:
                continue
            spec = resources.spec_for(entity) if use_resources else None
            m_type = spec["m_type"] if spec else entity_type_for_kind(entity["kind"])
            is_storage = m_type == cfg.M_STORAGE_CASE
            x, y = entity["position"]
            col_vals = dict(spec["col_vals"]) if spec else {cfg.S_DURABILITY: 100.0, cfg.S_BUILD_PROGRESS: 100.0}
            if with_spaces:                                   # EDEN_SPACES: the space is the map's index in its placed group
                col_vals[cfg.M_SPACE] = float(index)
            slot = iat.entity_born(engine.state.m_tensor, engine._entity_count_ref, x, y, m_type, hp=100.0,
                                   scale=spec["scale"] if spec else (STORAGE_RADIUS if is_storage else OBJECT_SCALE),
                                   register_geo=False, device=engine.state.device, col_vals=col_vals)
            if slot == -1:
                raise RuntimeError(f"entity capacity reached while instantiating {entity['id']!r}")
            engine._entity_uid_by_slot[slot] = entity["id"]
            present.add(entity["id"])
            created.append(entity["id"])
            if spec:
                map_geo.register_entity(slot, "circle", x, y, float(spec["scale"]), device=engine.state.device)
            if is_storage:
                map_geo.register_entity(slot, "circle", x, y, STORAGE_RADIUS, device=engine.state.device)
                starter = index == 0 and engine._starter_storage_case_entity_id is None
                engine._ensure_map_container(entity["id"], seed_contents=starter)
                if starter:
                    engine._starter_storage_case_entity_id = entity["id"]
                if use_resources:
                    seed_stock(engine, entity)
    if created:
        engine._force_map_refresh = True
    return created


def seed_stock(engine, entity):
    """Add the declared ``stock`` of a storage entity to its container, once per world (marker in ``_inventory_seeded_containers``)."""
    stock = resources.stock_of(entity)
    marker = f"stock:{entity['id']}"
    if not stock or marker in engine._inventory_seeded_containers:
        return False
    from systems.inventory.ops import add_item
    container = engine._storage_case_inventory_record(entity["id"])
    for item, quantity in sorted(stock.items()):
        add_item(container, item, int(quantity))
    engine._inventory_seeded_containers.add(marker)
    return True


def upgrade_authored_entities(engine, map_name):
    """Bring rows created as inert ``M_MAP_OBJECT`` (an older save, or created with the flag off) up to their resource shape.
    Idempotent: a row whose type already is the target type is left alone. Returns the ids upgraded. No-op with the flag off."""
    if not resources.enabled():
        return []
    upgraded = []
    slot_of = {uid: slot for slot, uid in enumerate(engine._entity_uid_by_slot) if uid}
    m = engine.state.m_tensor
    for entry in placed_group(map_name):
        for entity in entry["entities"]:
            slot = slot_of.get(entity["id"])
            spec = resources.spec_for(entity) if entity["interactive"] else None
            if slot is not None and spec and int(m[slot, cfg.M_TYPE]) == int(cfg.M_MAP_OBJECT):
                x, y = entity["position"]
                m[slot, cfg.M_TYPE] = float(spec["m_type"])
                m[slot, cfg.SCALE] = float(spec["scale"])
                for col, value in spec["col_vals"].items():
                    m[slot, int(col)] = float(value)
                map_geo.register_entity(slot, "circle", x, y, float(spec["scale"]), device=engine.state.device)
                upgraded.append(entity["id"])
            elif slot is not None and entity["kind"] in STORAGE_ENTITY_KINDS:
                seed_stock(engine, entity)
    if upgraded:
        engine._force_map_refresh = True
    return upgraded
