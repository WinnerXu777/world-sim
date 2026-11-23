from __future__ import annotations

import math
from typing import Literal, Optional

from . import effects as fx, instinct_bits
from .registry import power
from .powers import Draft, PowerRefused, _humans, _resolution, MASK_FIELDS


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
