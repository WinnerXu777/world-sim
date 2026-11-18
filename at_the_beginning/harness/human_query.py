"""1008 scaling (design: ``1008_spatial_index_gap.md``): the human-to-human resolvers (mate, help, support, attack target) looked at every human with
scalar tensor reads for every resident every tick, which is quadratic and was 70 percent of a 515 ms tick at 100 residents.

``humans_within`` answers "which human rows could be within ``radius`` of (x, y)" with a few vector operations and returns them in ascending slot order, the
order the old loops walked. It is a pre-filter only: it returns a SUPERSET of the rows that pass ``math.hypot(dx, dy) <= radius`` (the margin below is far
larger than the rounding difference between the vector and scalar arithmetic; NaN positions are kept because ``NaN > radius`` is False in the old test), and
each resolver then runs its original per-row body, in the same order, on those rows only. Same candidates, same tie-breaks, same floats: the answer cannot
differ, which the randomized oracle tests (``tests/test_harness_human_query.py``) check against the old implementations kept in the test.
"""
from __future__ import annotations

import math

import torch

_REL_MARGIN = 1e-9
_COLUMNS: dict = {}


def _columns(device, cols) -> torch.Tensor:
    key = (str(device), cols)
    found = _COLUMNS.get(key)
    if found is None:
        found = _COLUMNS[key] = torch.tensor(list(cols), dtype=torch.long, device=device)
    return found


def humans_within(h_tensor: torch.Tensor, x: float, y: float, radius: float, *, type_col: int, x_col: int, y_col: int, human_type: int,
                  extra_cols: tuple = (), keep=None) -> list:
    """Ascending slots of live humans whose position may lie within ``radius`` of (x, y) (a superset of the exact result; see the module docstring).

    ``keep(rows)`` is an optional further vector filter over the float64 rows ``[type, x, y, *extra_cols]`` that the caller's loop would apply anyway
    (the old loop's ``continue`` tests, written so that a NaN value passes exactly where it passed before: ``~(a < b)``, never ``a >= b``). It must only
    drop rows the old loop dropped; the callers' oracle tests pin the boundary values."""
    rows = h_tensor.index_select(1, _columns(h_tensor.device, (type_col, x_col, y_col) + tuple(extra_cols))).double().cpu()
    human = rows[:, 0] == float(human_type)
    if keep is not None:
        human = human & keep(rows)
    try:
        qx, qy, qr = float(x), float(y), float(radius)
    except (TypeError, ValueError):
        return torch.nonzero(human).flatten().tolist()
    if not (math.isfinite(qx) and math.isfinite(qy) and math.isfinite(qr)):
        return torch.nonzero(human).flatten().tolist()            # keep the old loop's NaN/inf semantics: let it decide on every human
    d2 = (rows[:, 1] - qx) ** 2 + (rows[:, 2] - qy) ** 2
    limit = (max(qr, 0.0) * (1.0 + _REL_MARGIN) + _REL_MARGIN) ** 2
    return torch.nonzero(human & ~(d2 > limit)).flatten().tolist()  # ~(d2 > limit): a NaN position passes, as it passes ``distance > radius`` in the old loops


_ANIMAL_TYPES: dict = {}


def animal_mask(m_types: torch.Tensor, animal_types) -> torch.Tensor:
    """``m_types == t`` OR-ed over ``animal_types`` as one ``isin`` (the old loop made one tensor op per type, 40 of them, on every ``_current_masks`` call)."""
    key = (str(m_types.device), m_types.dtype, tuple(sorted(animal_types)))
    wanted = _ANIMAL_TYPES.get(key)
    if wanted is None:
        wanted = _ANIMAL_TYPES[key] = torch.tensor(sorted(animal_types), dtype=m_types.dtype, device=m_types.device)
    return torch.isin(m_types, wanted)


# -- the old loops' own ``continue`` tests, as vector filters over ``humans_within(extra_cols=..., keep=...)`` ---------------------------------------
# Written as negations of the old "skip when" conditions so a NaN passes exactly where it passed before (``NaN < x`` is False).
try:
    import genesis_config as _cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as _cfg

HELP_COLS = (_cfg.HP, _cfg.THREAT)
SUPPORT_COLS = (_cfg.HP, _cfg.THREAT)
ATTACK_COLS = (_cfg.HP,)
MATE_COLS = (_cfg.H_SEX, _cfg.H_AGE, _cfg.H_COOLDOWN, _cfg.HUNGER, _cfg.THIRST, _cfg.THREAT, _cfg.HP, _cfg.H_STAMINA)


def keep_help(rows):
    """Old: ``if hp >= 78.0 and threat < 42.0: continue`` (rows: type, x, y, hp, threat)."""
    return ~((rows[:, 3] >= 78.0) & (rows[:, 4] < 42.0))


def keep_support(rows):
    """Old: ``hp <= 0`` skips; later ``hp < 45.0 or threat > 68.0`` skips."""
    return ~(rows[:, 3] <= 0.0) & ~(rows[:, 3] < 45.0) & ~(rows[:, 4] > 68.0)


def keep_attack(rows):
    """Old: ``if hp <= 0.0: continue`` (rows: type, x, y, hp)."""
    return ~(rows[:, 3] <= 0.0)


def keep_mate(seeker_sex: float):
    """Old: other not ``_slot_ready_for_mating`` skips, and an equal sex skips (rows: type, x, y, sex, age, cooldown, hunger, thirst, threat, hp, stamina)."""
    def keep(rows):
        return (~(rows[:, 3] == float(seeker_sex)) & ~(rows[:, 4] < float(_cfg.MATURE_AGE)) & ~(rows[:, 5] > 0.0)
                & ~(rows[:, 6] > float(_cfg.SAFE_REPRO_HUNGER_MAX)) & ~(rows[:, 7] > float(_cfg.SAFE_REPRO_THIRST_MAX))
                & ~(rows[:, 8] > float(_cfg.SAFE_REPRO_THREAT_MAX)) & ~(rows[:, 9] < float(_cfg.SAFE_REPRO_HP_MIN))
                & ~(rows[:, 10] < float(_cfg.SAFE_REPRO_STAMINA_MIN)))
    return keep
