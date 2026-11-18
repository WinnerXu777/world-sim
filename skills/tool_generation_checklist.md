# Tool Generation Checklist

Use this before generating a new tool or instinct with a smaller open-source model.

## Pick The Domain

Choose one primary home first:

- `systems.health`
- `systems.nature`
- `systems.combat`
- `systems.construction`
- `systems.interaction`
- `systems.inventory` when it exists

If a tool spans multiple domains, still choose one main domain and compose helpers from there.


## Preferred Import Path

Prefer importing from a domain `ops` module when it exists:

- `systems.health.ops`
- `systems.nature.ops`
- `systems.construction.ops`
- `systems.movement.ops`
- `systems.perception.ops`
- `systems.combat.ops`
- `systems.social.ops`

These are the curated helper surfaces for generated code.

Notes:

- `systems.map` already has usable public domain helpers, but its chunking/create API is still evolving.
- `systems.interaction` is still scaffold-level and should not be treated as a stable generation target yet.


## Writing Rule

Prefer:

1. build a mask or target set
2. call one or two reusable helpers
3. return a small semantic result

Avoid:

1. raw tensor column writes
2. large custom loops when a helper exists
3. copying chunks from `instincts_and_tools.py`


## If You Get Stuck

If the needed helper does not exist:

1. add a small helper to the right `ops` layer
2. then compose it from the generated tool

Do not skip directly to large inline tensor logic unless there is no safe alternative.


## Good Smells

- helper names are simple and predictable
- the tool body is short
- the tool mostly composes existing helpers
- return payload is minimal
- imports are domain-local


## Bad Smells

- magic numeric tensor columns in generated code
- imports from multiple giant compatibility files
- repeated clamp logic copied inline
- hand-written kill/heal/damage logic that already exists in `ops`
- frontend/input details mixed into backend tool logic
