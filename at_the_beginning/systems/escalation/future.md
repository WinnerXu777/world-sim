# Escalation Future

Current limitations:
- Current routing still reflects the earlier urgent-versus-normal design more than the newer simple `react / live / strategize` target
- Reasoning-lane ownership is still split across escalation, goal review, and world runtime
- Some pressure usage remains transitional rather than final

Nuances:
- This module is central to queue cost control, so new logic should stay debuggable and avoid opaque scoring sprawl
- Talk, combat, and manual-control events now create special cases that should keep using explicit tickets instead of pure scalar scoring

Suggested next elaborations:
- Evolve lane outputs toward the final `urgent`, `normal`, and `reasoning` split
- Keep reaction and consequence tickets as first-class outputs
- Add richer visibility into why a resident was routed into a lane
- Fold talk-triggered danger upgrades and reasoning follow-ups into one clearer policy surface
