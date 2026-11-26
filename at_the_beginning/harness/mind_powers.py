from __future__ import annotations

import math
import os

import torch
from typing import Literal, Optional

from . import effects as fx, instinct_bits
from .registry import power
from .powers import Draft, PowerRefused, _humans, _resolution, _check_amounts, MASK_FIELDS


def register_mind_powers(reg):
    def rows(world, targets):
        return _humans(world, targets if targets is not None else {'of': 'humans'})

    def require(table, fields):
        for field in fields:
            if field not in table.columns:
                raise PowerRefused('no_column', field)

    def result(res, name, effects):
        return Draft(res, effects, {'affected': list(res.ids)},
                     fx.Emit(name, actors=res.ids, visibility='private', payload={'count': len(res.ids)}))

    def adjust(world, targets, value, mode, field, floor):
        try:
            value = float(value) if not isinstance(value, bool) else float('nan')
        except (ValueError, TypeError, OverflowError):
            raise PowerRefused('invalid_amount') from None
        if not math.isfinite(value):
            raise PowerRefused('invalid_amount')
        res = rows(world, targets)
        table = world.table('humans')
        require(table, [field])
        before = [table.get(i, field) for i in res.ids]
        after = [value if mode == 'set' else v + value if mode == 'add' else v * value for v in before]
        if not all(math.isfinite(v) for v in before + after):
            raise PowerRefused('invalid_amount')
        return result(res, field + '_adjusted', [fx.set_('humans', res.ids, field, [max(floor, v) for v in after])])

    @power('age_shift', risk='reversible', registry=reg)
    def age_shift(world, targets: dict, years: float) -> Draft:
        """Shift selected ages, floored at zero."""
        return adjust(world, targets, years, 'add', 'age', 0.0)

    @power('life_exp_modify', risk='reversible', registry=reg)
    def life_exp_modify(world, targets: dict, value: float, mode: Literal['set', 'add', 'multiply'] = 'multiply') -> Draft:
        """Modify selected life expectancies, floored at one."""
        return adjust(world, targets, value, mode, 'life_exp', 1.0)

    def bit_change(world, targets, bit, grant):
        if isinstance(bit, bool) or not isinstance(bit, int) or not 0 <= bit <= instinct_bits.MAX_BIT:
            raise PowerRefused('invalid_bit')
        res = rows(world, targets)
        table = world.table('humans')
        word, shift = divmod(bit, instinct_bits.WORD_BITS)
        field = MASK_FIELDS[word]
        require(table, [field])
        old = [int(table.get(i, field)) for i in res.ids]
        new = [v | (1 << shift) if grant else v & ~(1 << shift) for v in old]
        return result(res, 'instinct_granted' if grant else 'instinct_revoked', [fx.set_('humans', res.ids, field, new)])

    @power('grant_instinct', risk='reversible', registry=reg)
    def grant_instinct(world, targets: dict, bit: int) -> Draft:
        """Grant an acquired instinct bit."""
        return bit_change(world, targets, bit, True)

    @power('revoke_instinct', risk='reversible', registry=reg)
    def revoke_instinct(world, targets: dict, bit: int) -> Draft:
        """Revoke an acquired instinct bit."""
        return bit_change(world, targets, bit, False)

    @power('inherit_instinct', risk='reversible', registry=reg)
    def inherit_instinct(world, targets: Optional[dict] = None) -> Draft:
        """Copy parent instinct bits into selected infants."""
        res = rows(world, targets)
        table = world.table('humans')
        parents = ('parent_instincts', 'parent_instincts_1', 'parent_instincts_2')
        require(table, ['age', *MASK_FIELDS, *parents])
        ids = tuple(i for i in res.ids if table.get(i, 'age') < 1 and any(table.get(i, p) != 0 for p in parents))
        if not ids:
            raise PowerRefused('no_targets')
        res = _resolution(world, res.selector, ids)
        effects = [fx.set_('humans', ids, field, [int(table.get(i, field)) | int(table.get(i, parent)) for i in ids])
                   for field, parent in zip(MASK_FIELDS, parents)]
        return result(res, 'instinct_inherited', effects)

    @power('quarantine', risk='reversible', registry=reg)
    def quarantine(world, targets: Optional[dict] = None) -> Draft:
        """Quarantine selected infected residents."""
        from genesis_config import INFECTION_THRESHOLD, QUARANTINE_COOLDOWN_YRS
        res = rows(world, targets)
        table = world.table('humans')
        require(table, ['infection', 'cooldown', 'stamina', 'threat'])
        ids = tuple(i for i in res.ids if table.get(i, 'infection') >= INFECTION_THRESHOLD)
        if not ids:
            raise PowerRefused('no_targets')
        res = _resolution(world, res.selector, ids)
        return result(res, 'quarantine', [fx.set_('humans', ids, 'cooldown', QUARANTINE_COOLDOWN_YRS),
            fx.set_('humans', ids, 'stamina', 0.0),
            fx.set_('humans', ids, 'threat', [min(100.0, table.get(i, 'threat') + 30.0) for i in ids])])

    @power('migration', risk='reversible', registry=reg)
    def migration(world, targets: dict, target_x: float, target_y: float, force: float = 10.0) -> Draft:
        """Move selected residents one step toward a point in a non-streamed world."""
        if os.environ.get('EDEN_WINDOW') == '1':
            raise PowerRefused('window_unsupported', 'migration needs window ownership reconciliation')
        values = (target_x, target_y, force)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values) or force < 0:
            raise PowerRefused('invalid_amount', 'target and non-negative force must be finite')
        res = rows(world, targets)
        table = world.table('humans')
        require(table, ['x', 'y'])
        positions = torch.tensor([[table.get(i, 'x'), table.get(i, 'y')] for i in res.ids], dtype=torch.float32)
        if not torch.isfinite(positions).all():
            raise PowerRefused('invalid_position')
        target = torch.tensor([[target_x, target_y]], dtype=torch.float32)
        if not torch.isfinite(target).all() or not math.isfinite(float(torch.tensor(force, dtype=torch.float32))):
            raise PowerRefused('invalid_amount')
        direction = target - positions
        push = direction / direction.norm(dim=1, keepdim=True).clamp(min=1e-6) * force
        out = positions + push
        if not torch.isfinite(out).all():
            raise PowerRefused('invalid_amount')
        return result(res, 'migration', [fx.set_('humans', res.ids, 'x', out[:, 0].tolist()),
                                         fx.set_('humans', res.ids, 'y', out[:, 1].tolist())])

    def consume_area(world, center_x, center_y, radius, restore, resource, need, types, cost, event):
        from systems.perception.queries import nearest_geo_entity, agent_radial_mask
        _check_amounts(radius=radius, restore=restore)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (center_x, center_y)):
            raise PowerRefused('invalid_center')
        humans = world.table('humans')
        try:
            entities = world.table('entities')
        except KeyError:
            raise PowerRefused('no_source') from None
        require(humans, ['x', 'y', need])
        require(entities, ['x', 'y', 'type', resource])
        candidates = rows(world, {'of': 'humans'})
        mask = torch.zeros(humans.tensor.shape[0], dtype=torch.bool, device=humans.tensor.device)
        for uid in candidates.ids:
            mask[humans.slot_of(uid)] = True
        affected = agent_radial_mask(humans.tensor, mask, center_x, center_y, radius, str(humans.tensor.device))
        ids = tuple(humans.ids[slot] for slot in torch.where(affected)[0].tolist() if humans.ids[slot] is not None)
        if not ids:
            raise PowerRefused('no_targets')
        res = _resolution(world, candidates.selector, ids)
        slot = nearest_geo_entity(entities.tensor, center_x, center_y, types, radius)
        if slot < 0 or slot >= len(entities.ids) or not entities.is_live_slot(slot) or entities.ids[slot] is None:
            raise PowerRefused('no_source')
        source = entities.ids[slot]
        stock = entities.get(source, resource)
        if not math.isfinite(stock) or stock <= 0:
            raise PowerRefused('no_stock')
        ids = []
        values = []
        for uid in res.ids:
            if stock <= 0:
                break
            value = humans.get(uid, need)
            if not math.isfinite(value):
                raise PowerRefused('invalid_amount')
            ids.append(uid)
            values.append(max(0.0, value - restore))
            stock = max(0.0, stock - cost)
        res = _resolution(world, res.selector, ids)
        import map_geo
        guard = fx.ResourceGuard(int(world.tick), humans.tensor.clone(), tuple(humans.ids), entities.tensor.clone(),
                                 tuple(entities.ids), map_geo.geo_version)
        return result(res, event, [guard, fx.set_('humans', ids, need, values), fx.set_('entities', [source], resource, stock)])

    @power('harvest_food', risk='reversible', registry=reg)
    def harvest_food(world, center_x: float, center_y: float, radius: float = 24.0, hunger_restore: float = 20.0) -> Draft:
        """Feed residents in an area from the nearest food-bearing geometry."""
        import genesis_config as cfg
        from systems.survival.navigation import FOOD_SOURCE_TYPES
        return consume_area(world, center_x, center_y, radius, hunger_restore, 'food', 'hunger', FOOD_SOURCE_TYPES,
                            cfg.EAT_RESOURCE_COST, 'food_harvested')

    @power('draw_water', risk='reversible', registry=reg)
    def draw_water(world, center_x: float, center_y: float, radius: float = 24.0, thirst_restore: float = 35.0) -> Draft:
        """Hydrate residents in an area from the nearest drinkable geometry."""
        import genesis_config as cfg
        from systems.survival.navigation import DRINKABLE_TYPES
        return consume_area(world, center_x, center_y, radius, thirst_restore, 'water', 'thirst', DRINKABLE_TYPES,
                            cfg.DRINK_RESOURCE_COST, 'water_drawn')

    @power('reproduce', risk='reversible', registry=reg)
    def reproduce(world, targets: Optional[dict] = None) -> Draft:
        """Run one mating step for selected residents, with live-engine birth bookkeeping."""
        import genesis_config as cfg
        from instincts_and_tools import _build_human_pairwise
        from systems.social.mating import build_seek_mask, restrict_reproduction_seek
        from . import calendar
        engine = getattr(world, 'engine', None)
        if engine is None or any(not hasattr(engine, name) for name in ('_next_human_uid', '_make_human_id', '_prev_h_mask', '_pending_birth_links_by_slot', 'resident_store', '_pop_count')):
            raise PowerRefused('runtime_unsupported', 'births require the live engine lifecycle')
        res = rows(world, targets)
        table = world.table('humans')
        fields = ['type', 'x', 'y', 'hp', 'strength', 'fertility', 'aggression', 'stamina', 'infection', 'shelter',
                  'sex', 'age', 'life_exp', 'cooldown', 'hunger', 'threat', 'mood', 'critical_health', 'escalation_flag',
                  'carrying', 'skill', 'tribe', 'parent_instincts', 'parent_instincts_1', 'parent_instincts_2', 'thirst', *MASK_FIELDS]
        require(table, fields)
        mask = torch.zeros(table.rows, dtype=torch.bool, device=table.tensor.device)
        for uid in res.ids:
            mask[table.slot_of(uid)] = True
        seek = build_seek_mask(mask, table.tensor)['seek_mask']
        seek = restrict_reproduction_seek(seek, table.tensor)['seek_mask']
        pair = _build_human_pairwise(table.tensor, mask, seek)
        mating = pair['within_mate'] & pair['seek_ready'][:, None] & pair['seek_ready'][None, :] & pair['female'][:, None] & pair['male'][None, :]
        free = [slot for slot in range(table.rows) if not table.is_live_slot(slot) and table.ids[slot] is None and not bool(engine._prev_h_mask[slot])]
        capacity = max(0, min(len(free), cfg.MAX_HUMANS - int(engine._pop_count[0])))
        births = []
        for row in torch.where(mating.any(dim=1))[0].tolist():
            if len(births) >= capacity:
                break
            mother_slot = int(pair['live_idx'][row])
            father_row = int(torch.where(mating[row])[0][0])
            father_slot = int(pair['live_idx'][father_row])
            mother, father = table.ids[mother_slot], table.ids[father_slot]
            stream = world.rng('power.reproduce', mother)
            x, y = world.clamp(table.get(mother, 'x') + stream.uniform(-4, 4), table.get(mother, 'y') + stream.uniform(-4, 4))
            child = {'type': float(cfg.AGENT_TYPE_HUMAN), 'x': x, 'y': y, 'hp': 100.0,
                     'strength': stream.uniform(30, 80), 'fertility': 1.0, 'stamina': 100.0,
                     'sex': 0.0 if stream.random() < 0.5 else 1.0, 'life_exp': stream.uniform(cfg.LIFE_EXP_MIN, cfg.LIFE_EXP_MAX),
                     'mood': 80.0, 'tribe': table.get(mother, 'tribe'),
                     'parent_instincts': table.get(mother, 'acquired_instinct_mask'),
                     'parent_instincts_1': table.get(mother, 'acquired_instinct_mask_1'),
                     'parent_instincts_2': table.get(mother, 'acquired_instinct_mask_2')}
            births.append((mother, father, free[len(births)], child))
        mothers = {birth[0] for birth in births}
        decay = calendar.cooldown_decay_rate()
        cooldowns = [max(0.0, (1.0 if uid in mothers else table.get(uid, 'cooldown')) - decay) for uid in res.ids]
        effects = [fx.BirthBatch(tuple(births), int(world.tick), int(engine._next_human_uid), table.tensor.clone(), tuple(table.ids))]
        effects.append(fx.set_('humans', res.ids, 'cooldown', cooldowns))
        draft = result(res, 'reproduction', effects)
        draft.preview['births'] = [{'mother': b[0], 'father': b[1]} for b in births]
        return draft
