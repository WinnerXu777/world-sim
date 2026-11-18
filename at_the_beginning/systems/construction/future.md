# Construction Future

Current limitations:
- Material handling is now inventory-backed for the first resident slice, but
  public/shared construction and deeper builder logistics are still shallow
- Build execution is task-driven for a first narrow slice, but still uses
  engine bridge callbacks instead of a fully standalone construction runtime
- Occupancy and shelter behavior are only partially unified
- Settlement/public construction needs are still scaffold-only and not yet
  coordinated as shared village projects
- Some building intents, such as a real market/shop, still use placeholders
  because the current structure enum does not yet have dedicated types

Nuances:
- Construction already depends on perception and health, so deeper changes should preserve those boundaries instead of re-embedding map logic here
- This module is a good candidate for future task-system integration
- Building needs should prefer reuse, shared access, and repair before emitting
  a new build request
- `construction` should keep ownership of placed structures, while future task
  chains should own execution flow and `inventory` should own material stacks

Suggested next elaborations:
- Expand task-owned construction beyond the current live slice into repair,
  resume, builder-specialized work, and public/shared projects
- Wire `village_well` and `market_anchor` into settlement-level deterministic
  need producers with deduped ownership
- Add true home-to-site hauling loops and later shared/public project logistics
- Add richer structure classes such as storage, workshops, and defensive works
- Unify shelter/occupancy with survival and human-mode interactions
