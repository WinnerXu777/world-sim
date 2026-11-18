"""R0.2 snapshot verification. Wait read-only, acquire once, abort on lock race."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "coordination_evidence"
LOCK = ROOT / ".runtime/fullsuite.lock"
STATUS = OUT / "codex_1010_r02_status.json"
REPORT = OUT / "codex_1010_r02_report.md"
PYTHON = ROOT / ".venv/Scripts/python.exe"
# Toronto is UTC-04:00 on this 2026-10-10 run; no tzdata installation needed.
ZONE = timezone(timedelta(hours=-4), "America/Toronto")
TOKEN = "codex-r02-" + uuid.uuid4().hex[:10]


def now():
    return datetime.now(ZONE).isoformat(timespec="seconds")


def status(state, **extra):
    STATUS.write_text(json.dumps({"status": state, "time": now(), **extra}, indent=2), encoding="utf-8")
    print(state, json.dumps(extra), flush=True)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def source_inventory():
    changed = set(git("diff", "HEAD", "--name-only", "-z").decode("utf-8").split("\0")) - {""}
    added = set(git("ls-files", "--others", "--exclude-standard", "-z", "--",
                    "at_the_beginning", "model_server", "tools", "tests", "world_data").decode("utf-8").split("\0")) - {""}
    paths = sorted(changed | added)
    return {name: {"sha256": digest(ROOT / name), "bytes": (ROOT / name).stat().st_size} if (ROOT / name).is_file() else {"deleted": True}
            for name in paths}


def main():
    REPORT.write_text("# R0.2 verification — 2026-10-10\n\nQueued: waiting read-only for the economy worker's heavy-run lock. No golden run or snapshot capture has started. No lock overridden.\n", encoding="utf-8")
    status("waiting_for_economy_compatibility")
    deadline = time.monotonic() + 45 * 60
    final_phase = OUT / "r63_goldens_manifest.json"
    preceding_phase = OUT / "r63_after_final_manifest.json"
    def compatibility_started():
        return (final_phase.exists() and preceding_phase.exists()
                and final_phase.stat().st_mtime >= preceding_phase.stat().st_mtime)
    # The economy pipeline releases/reacquires between phases. Its final-phase
    # manifest is written only after taking that phase's lock. Do not steal a gap.
    while LOCK.exists() or not compatibility_started():
        if time.monotonic() >= deadline:
            status("wait_timeout")
            return 2
        time.sleep(5)
    LOCK.parent.mkdir(exist_ok=True)
    # Exactly one acquisition attempt; a race aborts this entire script.
    try:
        handle = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        status("busy_abort")
        return 2
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump({"mode": "NORMAL", "owner": TOKEN, "pid": os.getpid(), "started": now(),
                   "phase": "R0.2 clean snapshot + four strict goldens", "eta": "10 minutes"}, stream)
    results = []
    try:
        head = git("rev-parse", "HEAD").decode().strip()
        inventory = source_inventory()
        snap = ROOT / ".runtime" / TOKEN
        snap.mkdir()
        archive = OUT / (TOKEN + "-HEAD.tar")
        subprocess.run(["git", "archive", "--format=tar", "--output", str(archive), head], cwd=ROOT, check=True)
        archive_sha = digest(archive)
        with tarfile.open(archive) as bundle:
            bundle.extractall(snap, filter="data")
        for name, info in inventory.items():
            target = snap / name
            if snap.resolve() not in target.resolve().parents:
                raise RuntimeError("Overlay escaped snapshot: " + name)
            if info.get("deleted"):
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
            if digest(target) != info["sha256"]:
                raise RuntimeError("Source changed during overlay copy: " + name)
        support = {}
        for relative in ("myassets", "tests/fixtures/maps/sprites"):
            source = ROOT / relative
            if not source.exists():
                raise RuntimeError("Required support directory missing: " + relative)
            destination = snap / relative
            shutil.copytree(source, destination, dirs_exist_ok=True)
            for item in sorted(destination.rglob("*")):
                if item.is_file():
                    support[item.relative_to(snap).as_posix()] = {"sha256": digest(item), "bytes": item.stat().st_size}
        if inventory != source_inventory() or head != git("rev-parse", "HEAD").decode().strip():
            raise RuntimeError("Source changed during snapshot capture; this snapshot is not verified")
        snapshot_id = hashlib.sha256(json.dumps({"head_archive_sha256": archive_sha, "overlays": inventory, "support": support}, sort_keys=True).encode()).hexdigest()
        manifest = OUT / "codex_1010_r02_snapshot.json"
        data = {"capture_time": now(), "head": head, "snapshot": str(snap), "archive": str(archive),
                "archive_sha256": archive_sha, "snapshot_sha256": snapshot_id, "overlays": inventory,
                "support_files": support, "strict_modes": ["default", "resources", "spaces", "window-hook"]}
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        (snap / ".runtime").mkdir(exist_ok=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith("EDEN_")}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        modes = [("default", []), ("resources", ["--resources"]), ("spaces", ["--spaces"]), ("window-hook", ["--window-hook"])]
        for name, flags in modes:
            log = OUT / ("codex_1010_r02_" + name + ".log")
            trace = OUT / ("codex_1010_r02_" + name + ".json")
            command = [str(PYTHON), "tools/golden_trace.py", "--check", "--strict", *flags, "--out", str(trace)]
            status("running", mode=name, snapshot=str(snap), head=head, snapshot_sha256=snapshot_id)
            started = time.monotonic()
            with log.open("w", encoding="utf-8") as stream:
                finished = subprocess.run(command, cwd=snap, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=20 * 60)
            result = {"mode": name, "exit_code": finished.returncode, "seconds": round(time.monotonic() - started, 1),
                      "command": command, "log": str(log), "trace": str(trace), "trace_sha256": digest(trace) if trace.exists() else None}
            results.append(result)
            data["results"] = results
            manifest.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            status("mode_complete", **result)
        drift = any(result["exit_code"] for result in results)
        changed_after = inventory != source_inventory() or head != git("rev-parse", "HEAD").decode().strip()
        lines = ["# R0.2 strict golden verification — 2026-10-10", "",
                 "Status: " + ("FAIL: inspect preserved logs; references were not rewritten." if drift else "PASS for the captured uncommitted source snapshot; this is not final at-HEAD/full-suite evidence."), "",
                 f"Captured {data['capture_time']} (America/Toronto). HEAD `{head}`. Snapshot `{snap}`.",
                 f"Archive SHA-256 `{archive_sha}`. Composite snapshot SHA-256 `{snapshot_id}`.",
                 "Full overlay and support-file hashes are in `coordination_evidence/codex_1010_r02_snapshot.json`.", "",
                 "Snapshot is git archive HEAD plus every modified tracked path and untracked source/test path under at_the_beginning, model_server, tools, tests and world_data, plus required myassets and fixture sprites. No client snapshot/visual acceptance claimed. All inherited EDEN_* variables removed in the child environment; each mode sets only its intended flags and headless isolation.", "",
                 "| Mode | Exit | Seconds |", "| --- | --- | --- |"]
        lines.extend(f"| {r['mode']} | {r['exit_code']} | {r['seconds']} |" for r in results)
        lines.extend(["", "Each command used `tools/golden_trace.py --check --strict` with default seed 1008 / 3600 ticks and its indicated mode, saving fresh traces with `--out` and complete logs. No record mode, default flag change or reference rewrite.", "",
                      f"Working source changed after capture: {changed_after}. These results cover the immutable snapshot, including all recorded ownership overlays; they do not certify later edits, R0.1 full suite, live client/portal behavior, ecology or final HEAD.", "",
                      "Owned NORMAL lock acquired atomically once after the economy worker released it, held throughout capture/tests, and released only if its owner token still matched. No other lock removed. Snapshot, HEAD archive, manifest, traces and logs retained. No commits/pushes or code repairs performed."])
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        status("failed" if drift else "complete", results=results, source_changed_after_capture=changed_after, report=str(REPORT))
        return 1 if drift else 0
    except Exception as exc:
        status("error", error=repr(exc), results=results)
        with REPORT.open("a", encoding="utf-8") as stream:
            stream.write("\nVerification stopped: `" + repr(exc) + "`. No passing acceptance claim. Any snapshot/logs remain preserved.\n")
        raise
    finally:
        if LOCK.exists():
            try:
                if json.loads(LOCK.read_text(encoding="utf-8")).get("owner") == TOKEN:
                    LOCK.unlink()
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    sys.exit(main())
