"""Shadow comparison of decision providers on the same requests (Gate B: Tier 1 vs rules vs mock Clef).

``compare(requests, {"rules": p1, "matrix": p2, "mock_clef": p3})`` runs every provider on every request (a provider that raises
counts as an error, not a disagreement) and returns per-provider top-option counts plus pairwise argmax agreement. ``write_jsonl``
appends one record per request in the decision-log style so the comparison can be replayed or audited.
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from .contract import summarize, validate_probabilities


def compare(requests, providers: dict) -> dict:
    tops = {name: [] for name in providers}
    errors = {name: 0 for name in providers}
    records = []
    for request in requests:
        record = {"type": "shadow_compare", "job_id": request.job_id, "resident_id": request.resident_id, "trigger": request.trigger,
                  "topic": request.topic, "answers": {}}
        for name, provider in providers.items():
            try:
                probabilities = validate_probabilities(request.options, provider.decide(request))
                top, top_p, margin = summarize(request.options, probabilities)
                record["answers"][name] = {"top": top, "top_p": round(top_p, 6), "margin": round(margin, 6)}
                tops[name].append(top)
            except Exception as exc:  # noqa: BLE001 - a failing provider is a result of the comparison
                errors[name] += 1
                record["answers"][name] = {"error": f"{type(exc).__name__}: {exc}"}
                tops[name].append(None)
        records.append(record)
    agreement = {}
    for a, b in combinations(providers, 2):
        pairs = [(x, y) for x, y in zip(tops[a], tops[b]) if x is not None and y is not None]
        agreement[f"{a}~{b}"] = {"compared": len(pairs), "agree": sum(x == y for x, y in pairs),
                                 "rate": round(sum(x == y for x, y in pairs) / len(pairs), 4) if pairs else None}
    return {"requests": len(records), "errors": errors, "agreement": agreement, "records": records}


def write_jsonl(report: dict, path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in report["records"]:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return len(report["records"])
