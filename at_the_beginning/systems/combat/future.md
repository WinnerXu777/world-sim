# Combat Future

Current limitations:
- Combat is still fairly simple and close-range focused
- Weapon handling is not yet deeply integrated with `systems/inventory`
- Threat posture, stance, morale, and surrender are still lightweight

Nuances:
- Combat already feeds resident memory and relationship consequences through higher-level runtime hooks, so changes here ripple into memory, goals, and talk
- Hunting and combat are still partly coupled through shared target logic

Suggested next elaborations:
- Add equipped-weapon-aware reach, damage, and attack timing
- Separate melee, ranged, intimidation, and nonlethal combat paths
- Add formation or ally-response helpers for multi-resident fights
- Feed richer combat outcomes into talk, escalation, and reasoning queues
