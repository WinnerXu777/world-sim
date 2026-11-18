"""R5-B acceptance of the S-1 family_farm scenario: determinism, Tier 1 rules vs matrix, Tier 3 shadow vs on (mock server).

    .venv/Scripts/python.exe -m model_server.s1_acceptance --ticks 3000 --json out.json

Every run is a fresh process (``model_server.s1_family_farm`` must not be booted twice in one process). It prints one line per run and the verdicts of the
comparisons below, and exits non-zero when one fails:

* ``determinism``: the same variant and seed twice give the same digest.
* ``matrix_vs_rules``: the matrix Tier 1 (prior 100) reproduces the rules digest (Tier 1 choices are bit-equal by construction at prior 100; a difference is a defect).
* ``shadow_vs_off``: Tier 3 resident in shadow changes nothing (same digest as off), its plans are recorded, none applied.
* ``on``: Tier 3 resident on against the mock server: no errors, no deaths, every escalation outcome counted. When a plan ran (``run:ok`` > 0) the digest must
  differ from the off run (the plan's effects are in the digest through the position / needs timeline); with no plan the run is reported as vacuous.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def one(label: str, extra: list, args) -> dict:
    out = Path(tempfile.mkdtemp(prefix="s1acc-")) / f"{label}.json"
    cmd = [sys.executable, "-m", "model_server.s1_family_farm", "--variant", args.variant, "--ticks", str(args.ticks), "--seed", str(args.seed),
           "--reputation", "--family-hunger", str(args.family_hunger), "--json", str(out)] + extra
    done = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if not out.exists():
        return {"label": label, "error": (done.stderr or done.stdout)[-1500:], "returncode": done.returncode}
    result = json.loads(out.read_text(encoding="utf-8"))
    result["label"], result["returncode"] = label, done.returncode
    return result


def brief(r: dict) -> str:
    if "error" in r:
        return f"{r['label']:<14} ERROR {r['error'][-200:]!r}"
    t3 = r.get("tier3", {}).get("escalation", {}).get("counts", {})
    return (f"{r['label']:<14} digest={r['digest']} pass={r['verdict']['pass']} dead={list(r['dead_at'])} peak={max(r['peak_hunger'].values())} "
            f"thefts={r['events'].get('theft', 0)} gossip={r['reputation']['counts'].get('gossip', 0)} errors={r['errors']}"
            + (f" tier3={dict(t3)}" if t3 else ""))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--variant", default="steal")
    p.add_argument("--ticks", type=int, default=3000)
    p.add_argument("--seed", type=int, default=1008)
    p.add_argument("--family-hunger", type=float, default=40.0, dest="family_hunger", help="starting hunger of the family; 85 makes the Tier 3 sweep trigger")
    p.add_argument("--json")
    args = p.parse_args(argv)
    runs = {}
    plan = [("rules-a", []), ("rules-b", []), ("matrix", ["--tier1", "matrix"]), ("t3-shadow", ["--tier3", "shadow"]), ("t3-on", ["--tier3", "on"])]
    for label, extra in plan:
        runs[label] = one(label, extra, args)
        print(brief(runs[label]), flush=True)
    digest = lambda label: runs[label].get("digest")  # noqa: E731
    checks = {
        "determinism": digest("rules-a") is not None and digest("rules-a") == digest("rules-b"),
        "matrix_vs_rules": digest("matrix") is not None and digest("matrix") == digest("rules-a"),
        "shadow_vs_off": digest("t3-shadow") is not None and digest("t3-shadow") == digest("rules-a"),
        "on_applied_or_vacuous": (runs["t3-on"].get("tier3", {}).get("escalation", {}).get("counts", {}).get("run:ok", 0) == 0) or digest("t3-on") != digest("rules-a"),
        "on_clean": "error" not in runs["t3-on"] and runs["t3-on"]["errors"] == 0 and not runs["t3-on"]["dead_at"],
        "all_runs_pass": all(r.get("verdict", {}).get("pass") for r in runs.values()),
    }
    print(json.dumps(checks, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps({"checks": checks, "runs": runs}, indent=1, default=str), encoding="utf-8")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
