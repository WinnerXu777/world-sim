"""Observe Tier 0 food calls in two unchanged final archives, without editing shared code."""
from pathlib import Path
import argparse
import asyncio
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def single(args):
    archive = Path(args.archive)
    sys.path[:0] = [str(archive), str(archive / "at_the_beginning")]
    os.environ["EDEN_ECONOMY_BALANCE"] = args.enabled
    from model_server import s1_commons as commons
    config = commons.parser().parse_args(["--single", "--seed", "1008", "--ticks", "4000"])
    original_setup = commons.setup
    counts, tail, reasons, samples, water_ticks = {}, {}, {}, [], set()
    engines = []
    saved = []

    def setup(engine, scenario_args):
        result = original_setup(engine, scenario_args)
        engines.append(engine)
        from systems.roster import needs
        saved.append((needs, needs.ration))
        names = {uid: key for key, uid in commons.farm.keys_of(engine).items()}

        def observe_ration(engine, slot, kind, settings, state, human_id):
            import genesis_config as cfg
            from systems.actions.agent_driver import driver_of
            pair = (int(engine.tick), human_id)
            if kind == "water":
                water_ticks.add(pair)
            if kind == "food":
                key = names.get(human_id, human_id)
                counts[key] = counts.get(key, 0) + 1
                if int(engine.tick) > 3000:
                    tail[key] = tail.get(key, 0) + 1
                hunger = float(engine.state.h_tensor[slot, cfg.HUNGER])
                reason = "hunger_floor" if hunger >= 90 else ("thirst_then_food" if pair in water_ticks else "below_floor_other")
                reasons[reason] = reasons.get(reason, 0) + 1
                errand = driver_of(engine).ladder.errands.get(human_id)
                tasks = (engine.resident_store.get(human_id) or {}).get("tasks", [])
                resting = [t.get("kind", t.get("name", "")) for t in tasks if t.get("status") in ("active", "queued")]
                if len(samples) < 100:
                    samples.append({"tick": int(engine.tick), "who": key, "hunger": round(hunger, 3), "reason": reason,
                                    "errand": errand.purpose if errand else "", "active_tasks": resting})
            return saved[0][1](engine, slot, kind, settings, state, human_id)

        needs.ration = observe_ration
        return result

    commons.setup = setup
    try:
        result = asyncio.run(commons.run(config))
    finally:
        commons.setup = original_setup
        for module, original in saved:
            module.ration = original
    from systems.actions.agent_driver import driver_of
    driver = driver_of(engines[0])
    result["exact_food_ration_calls"] = {"total": counts, "tail": tail, "reasons": reasons, "samples": samples,
                                        "rest_routes": {k: v for k, v in driver.routed.items() if "rest" in k},
                                        "yielded_ticks": driver.yielded,
                                        "meal_events": {k: v for k, v in result["events"].items() if "ate" in k},
                                        "harvested_crop_bundles": result["balance"]["declared_farm_crop_bundles"]}
    Path(args.output).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"enabled": args.enabled, "digest": result["digest"], "food_rations": result["exact_food_ration_calls"]}), flush=True)
    return 0 if result["verdict"]["pass"] else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--single", action="store_true")
    p.add_argument("--archive")
    p.add_argument("--output")
    p.add_argument("--enabled", default="0")
    args = p.parse_args()
    if args.single:
        return single(args)
    lock = ROOT / ".runtime/fullsuite.lock"
    token = f"NORMAL codex-r63 pid={os.getpid()} exact-ration-probe eta=8min"
    try:
        with lock.open("x") as f:
            f.write(token)
    except FileExistsError:
        print("LOCK BUSY", flush=True)
        return 3
    try:
        scratch = ROOT / ".tmp/r63_ration_probe"
        scratch.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_")}
        env.update(TEMP=str(scratch), TMP=str(scratch))
        for phase, flag in (("off", "0"), ("after_final", "1")):
            command = [sys.executable, str(Path(__file__).resolve()), "--single", "--archive", str(ROOT / ".tmp" / ("r63_" + phase)),
                       "--enabled", flag, "--output", str(ROOT / "coordination_evidence" / ("r63_exact_rations_" + phase + ".json"))]
            print(json.dumps(command), flush=True)
            code = subprocess.run(command, cwd=ROOT, env=env).returncode
            if code:
                return code
        return 0
    finally:
        if lock.exists() and lock.read_text() == token:
            lock.unlink()


if __name__ == "__main__":
    sys.exit(main())
