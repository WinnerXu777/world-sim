"""Tier 3 plan ops for the S1 verbs and ``run_plan``, a mock Tier 3 plan runner.

A plan is a list of steps ``{"op": <verb id>, "args": {...}}``. ``run_plan`` sends each step through the action runner (so a step is
schema-checked, grounded, legality-checked, rate/risk-gated, applied and audited exactly like any other call) and stops at the first
rejection. These ops are *not* in ``systems/planning``'s ``PLAN_OP_DEFS`` (its validator accepts only catalog ops), so the planning system cannot run them
yet; until that integration they run here only (1008_actions.md section 9).
"""
from __future__ import annotations

from . import catalog

PLAN_OPS = {row.id: row.id for row in catalog.CATALOG if row.s1}


def run_plan(runner, actor: str, steps, *, proposer: str = "tier3", confidence=None, dry_run: bool = False) -> dict:
    """Run ``steps`` in order for ``actor``; returns ``{"ok", "completed", "failed_at", "code", "results"}`` and never raises."""
    if not isinstance(steps, (list, tuple)):
        return {"ok": False, "completed": 0, "failed_at": None, "code": "invalid_plan", "results": []}
    results = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            results.append(runner.run(actor, "", step if isinstance(step, dict) else {}, proposer=proposer, confidence=confidence))
            return {"ok": False, "completed": index, "failed_at": index, "code": "invalid_plan_step", "results": results}
        op = step["op"]
        if op in catalog.BY_ID and op not in PLAN_OPS:
            result = runner.run(actor, op, step.get("args"), proposer=proposer, confidence=confidence, dry_run=True)
            result.ok, result.code = False, "not_a_plan_op"
        else:
            result = runner.run(actor, op, step.get("args"), proposer=proposer, confidence=confidence, dry_run=dry_run)
        results.append(result)
        if not result.ok:
            return {"ok": False, "completed": index, "failed_at": index, "code": result.code, "results": results}
    return {"ok": True, "completed": len(results), "failed_at": None, "code": "ok", "results": results}
