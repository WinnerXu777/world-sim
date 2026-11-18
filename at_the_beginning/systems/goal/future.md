# Goal Future

Current limitations:
- Goal review is still partly deterministic and not yet fully owned by the world-model reasoning lane
- Success, failure, decay, and conflict resolution are still conservative
- Goal ontology is intentionally bounded and still small

Nuances:
- Goals already feed escalation, human prompts, and plot execution, so schema churn here has broad runtime impact
- Goals should stay structured even as they become more varied

Suggested next elaborations:
- Move richer goal review into the reasoning queue
- Add stronger success and failure conditions, cooldowns, and replacement logic
- Expand economic, criminal, social, and territorial goal kinds
- Tie plan generation more tightly to active goal transitions
