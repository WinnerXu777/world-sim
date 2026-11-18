"""Owned, atomic-lock runner for R6.3 checks; no source cleanup or commits."""
from pathlib import Path
import argparse
import json
import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=("baseline", "off", "after", "after_final", "goldens", "tests", "fixed_after", "fixed_off", "fixed_goldens", "fixed_tests"))
    args = p.parse_args()
    case = args.phase.removeprefix("fixed_")
    lock = ROOT / ".runtime/fullsuite.lock"
    token = f"NORMAL codex-r63 pid={os.getpid()} phase={args.phase} eta=15min start={time.strftime('%Y-%m-%dT%H:%M:%S')}"
    try:
        with lock.open("x", encoding="utf-8") as f:
            f.write(token)
    except FileExistsError:
        print("LOCK BUSY: " + lock.read_text(), flush=True)
        return 3
    try:
        dest = ROOT / ".tmp" / ("r63_" + args.phase)
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / "head.zip"
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        subprocess.run(["git", "archive", head, "--format=zip", "-o", str(archive)], cwd=ROOT, check=True)
        shutil.unpack_archive(archive, dest)
        for rel in ("myassets", "tests/fixtures/maps/sprites"):
            source = ROOT / rel
            if source.exists():
                shutil.copytree(source, dest / rel, dirs_exist_ok=True)
        sources = ("model_server/s1_commons.py", "model_server/economy_audit.py", "at_the_beginning/systems/actions/agent_driver.py", "at_the_beginning/systems/roster/needs.py", "at_the_beginning/systems/actions/market_day.py", "at_the_beginning/systems/actions/ladder.py", "at_the_beginning/systems/actions/resource_verbs.py", "at_the_beginning/systems/actions/economy_verbs.py", "at_the_beginning/systems/affordance/predicates.py", "at_the_beginning/systems/affordance/economy_predicates.py", "tests/test_economy_balance.py")
        if case != "baseline":
            for rel in sources:
                if (ROOT / rel).exists():
                    shutil.copy2(ROOT / rel, dest / rel)
        py = str(ROOT / ".venv/Scripts/python.exe")
        env = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_")}
        scratch = dest / "temp"
        scratch.mkdir(exist_ok=True)
        env.update(TEMP=str(scratch), TMP=str(scratch))
        if case in ("baseline", "off", "after", "after_final"):
            if case.startswith("after"):
                env["EDEN_ECONOMY_BALANCE"] = "1"
            commands = [[py, "-m", "model_server.s1_commons", "--seeds", "1008,1,2,3", "--repeat", "--ticks", "4000", "--json", str(ROOT / "coordination_evidence" / ("r63_" + args.phase + ".json"))]]
        elif case == "goldens":
            commands = [[py, "tools/golden_trace.py", "--check", "--strict", *flag] for flag in ([], ["--resources"], ["--spaces"], ["--window-hook"])]
        else:
            commands = [[py, "-m", "unittest", "discover", "-s", "tests", "-p", name] for name in ("test_economy_balance.py", "test_market_book.py", "test_market_verbs.py", "test_labour.py", "test_roster_needs.py", "test_agent_driver.py")]
        manifest = {"base": head, "archive": str(dest), "phase": args.phase, "commands": commands,
                    "source_sha256": {rel: hashlib.sha256((dest / rel).read_bytes()).hexdigest() for rel in sources if (dest / rel).exists()}}
        (ROOT / "coordination_evidence" / ("r63_" + args.phase + "_manifest.json")).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for cmd in commands:
            print(json.dumps(cmd), flush=True)
            with (ROOT / "coordination_evidence" / ("r63_" + args.phase + ".log")).open("a", encoding="utf-8") as log:
                proc = subprocess.run(cmd, cwd=dest, env=env, stdout=log, stderr=subprocess.STDOUT)
            print(f"exit={proc.returncode}", flush=True)
            if proc.returncode:
                return proc.returncode
        return 0
    finally:
        if lock.exists() and lock.read_text(encoding="utf-8") == token:
            lock.unlink()

if __name__ == "__main__":
    sys.exit(main())
