"""Imitation-train the Tier 1 matrix weights from the rules prior. No external model, deterministic, versioned.

    .venv/Scripts/python.exe -m model_server.train_matrix --collect data.npz --seeds 1008,1,2 --ticks 1200
    .venv/Scripts/python.exe -m model_server.train_matrix --data data.npz --version 2 --out report.json              # fit, check, write weights_v2.npz (+ provenance)

* **Data.** The real headless engine (starter village, 8 residents) is stepped; every ``--every`` ticks each resident's needs are rewritten from a seeded generator (the same stress
  states ``shadow_compare`` uses), then the feature builder, the affordance mask and the Stage 1 survival rules are read: ``(X, P, mask, rules macro)``. Rows where the rules have an
  opinion and their choice is legal are the *labelled* rows; the rest (the rules are silent) are the *prior* rows.
* **Fit.** Only ``W`` and ``b`` move (``U`` and ``V``, the personality modulation, stay the prior's). Loss = cross-entropy of the rules' macro on the labelled rows (softmax over the legal
  options at the prior's temperature) + ``--prior-weight`` x mean KL(prior policy || new policy) over **all** rows (so silent states keep the prior's behaviour) + ``--l2`` x squared
  distance of (W, b) from the prior. LBFGS, float64, one thread, fixed iterations: the same data gives the same file hash.
* **Gate.** The file is written only if the held-out agreement with the rules improves and the mean KL to the prior on the silent rows stays below ``--max-silent-kl``. Otherwise the
  report says so and nothing is written: the rules prior (weights v1) stays the answer. ``EDEN_MATRIX_WEIGHTS=2`` selects a written file at run time
  (``systems/actions/weights.default_policy``); a missing or tampered file falls back to the prior.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _paths():
    for path in (str(ROOT), str(ROOT / "at_the_beginning")):
        if path not in sys.path:
            sys.path.insert(0, path)


# -- data --------------------------------------------------------------------------------------------------------------------------------
async def collect_seed(seed: int, ticks: int, every: int) -> dict:
    _paths()
    import numpy as np
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    backend, engine = await boot_engine(seed)
    import genesis_config as cfg
    from harness.adapter import EngineWorld
    from systems.affordance import AffordanceEngine, EngineServices
    from systems.decision import matrix
    from systems.decision.features import build_features, rules_macro
    world, services = EngineWorld(engine, seed=0), EngineServices(engine)
    aff = AffordanceEngine(world, services, driver_mode="agent")      # the mask the agent driver uses
    residents = [u for u in engine._human_uid_by_slot if u]
    rng = np.random.default_rng(seed)
    h = engine.state.h_tensor
    X, P, M, Y = [], [], [], []
    for t in range(ticks + 1):
        if t % every == 0:
            for human in residents:
                slot = engine._human_slot_for_id(human)
                h[slot, cfg.HUNGER], h[slot, cfg.THIRST] = float(rng.uniform(0, 85)), float(rng.uniform(0, 85))     # under the damage thresholds: nobody dies between samples
                h[slot, cfg.THREAT] = float(rng.uniform(0, 100)) if rng.random() < 0.3 else 0.0
                h[slot, cfg.H_STAMINA], h[slot, cfg.HP] = float(rng.uniform(5, 100)), float(rng.uniform(60, 100))
            batch = build_features(world, services, residents)
            mask = aff.mask(residents)
            for i, human in enumerate(residents):
                slot = engine._human_slot_for_id(human)
                raw = {"hunger": float(h[slot, cfg.HUNGER]), "thirst": float(h[slot, cfg.THIRST]), "threat": float(h[slot, cfg.THREAT]),
                       "stamina": float(h[slot, cfg.H_STAMINA]), "hp": float(h[slot, cfg.HP])}
                rule = rules_macro(raw, services.inventory(human), bool(h[slot, cfg.H_SHELTER] > 0))
                X.append(batch.X[i].numpy()), P.append(batch.P[i].numpy()), M.append(mask[i].numpy())
                Y.append(matrix.ACTION_INDEX[rule] if rule is not None else -1)
        if t < ticks:
            engine.step()
    return {"X": np.array(X), "P": np.array(P), "M": np.array(M, dtype=bool), "Y": np.array(Y, dtype=np.int64)}


async def collect(seeds: list, ticks: int, every: int) -> dict:
    import numpy as np
    parts = []
    for seed in seeds:
        parts.append(await collect_seed(seed, ticks, every))      # one engine per seed in this process: the harness resets the singleton between boots
    data = {k: np.concatenate([p[k] for p in parts]) for k in ("X", "P", "M", "Y")}
    data["seed_of_row"] = np.concatenate([np.full(len(p["Y"]), s, dtype=np.int64) for p, s in zip(parts, seeds)])
    return data


def data_hash(data: dict) -> str:
    digest = hashlib.sha256()
    for key in ("X", "P", "M", "Y"):
        digest.update(key.encode())
        digest.update(data[key].tobytes())
    return digest.hexdigest()[:16]


# -- fit ---------------------------------------------------------------------------------------------------------------------------------
def fit(data: dict, *, prior_weight: float = 1.0, l2: float = 1e-2, iterations: int = 150, holdout_seed=None) -> dict:
    _paths()
    import numpy as np
    import torch
    from systems.decision import matrix
    torch.set_num_threads(1)
    prior = matrix.MatrixPolicy.initial()
    X, P, M, Y = (torch.as_tensor(data[k]) for k in ("X", "P", "M", "Y"))
    X, P = X.double(), P.double()
    rows = np.arange(len(Y))
    if holdout_seed is None:
        holdout_seed = int(data["seed_of_row"][-1]) if "seed_of_row" in data else None
    test = (data["seed_of_row"] == holdout_seed) if holdout_seed is not None and "seed_of_row" in data else (rows % 5 == 0)
    if test.all() or not test.any():
        test = rows % 5 == 0
    has_legal = M.any(dim=1).numpy()                                        # a row with nothing legal has no policy: it carries no signal (and would poison the gradient with NaN)
    test = test & has_legal
    train = (~test) & has_legal
    labelled = (Y >= 0) & M[torch.arange(len(Y)), Y.clamp_min(0)]
    T = prior.temperature
    mod = (X @ prior.U) * (P @ prior.V)                                    # the personality term stays the prior's

    def logits(W, b, sel):
        S = X[sel] @ W + mod[sel] + b
        return (S / T).masked_fill(~M[sel], float("-inf"))

    W0, b0 = prior.W.clone(), prior.b.clone()
    W, b = W0.clone().requires_grad_(True), b0.clone().requires_grad_(True)
    sel_train = torch.as_tensor(train)
    with torch.no_grad():
        prior_logp = torch.log_softmax(logits(W0, b0, sel_train), dim=1)
        prior_logp = torch.where(torch.isfinite(prior_logp), prior_logp, torch.zeros_like(prior_logp))
        prior_p = prior_logp.exp() * M[sel_train]
    lab_train = labelled[sel_train]
    y_train = Y[sel_train]
    legal_train = M[sel_train]
    any_legal = legal_train.any(dim=1)
    optimizer = torch.optim.LBFGS([W, b], lr=1.0, max_iter=iterations, line_search_fn="strong_wolfe", tolerance_grad=1e-10, tolerance_change=1e-12)

    def closure():
        optimizer.zero_grad()
        logp = torch.log_softmax(logits(W, b, sel_train), dim=1)
        logp = torch.where(legal_train, logp, torch.zeros_like(logp))
        ce = -(logp[torch.arange(len(y_train)), y_train.clamp_min(0)] * lab_train).sum() / lab_train.sum().clamp_min(1)
        kl = (prior_p * (torch.log(prior_p.clamp_min(1e-300)) - logp) * legal_train).sum(dim=1)
        kl = (kl * any_legal).sum() / any_legal.sum().clamp_min(1)
        loss = ce + prior_weight * kl + l2 * (((W - W0) ** 2).sum() + ((b - b0) ** 2).sum())
        loss.backward()
        return loss

    optimizer.step(closure)
    new = matrix.MatrixPolicy(W.detach().numpy(), prior._np[1], prior._np[2], b.detach().numpy(), prior.temperature, prior.hysteresis, version=2)

    def report(policy, sel):
        sel_t = torch.as_tensor(sel)
        res = policy.decide(X[sel_t], P[sel_t], M[sel_t])
        top = res.action
        lab = labelled[sel_t]
        agree = float(((top == Y[sel_t]) & lab).sum()) / max(1, int(lab.sum()))
        silent = (~lab) & (res.no_legal == False)    # noqa: E712
        return {"rows": int(sel.sum()), "labelled": int(lab.sum()), "agreement": round(agree, 4), "silent_rows": int(silent.sum()), "probabilities": res.probabilities}

    out = {"train": {}, "test": {}}
    for name, sel in (("train", train), ("test", test)):
        before, after = report(prior, sel), report(new, sel)
        sel_t = torch.as_tensor(sel)
        silent = (~labelled[sel_t]) & M[sel_t].any(dim=1)
        kl = (before["probabilities"] * (torch.log(before["probabilities"].clamp_min(1e-300)) - torch.log(after["probabilities"].clamp_min(1e-300)))).sum(dim=1)
        silent_kl = float(kl[silent].mean()) if bool(silent.any()) else 0.0
        out[name] = {"rows": before["rows"], "labelled": before["labelled"], "agreement_prior": before["agreement"], "agreement_new": after["agreement"],
                     "silent_rows": int(silent.sum()), "silent_kl_to_prior": round(silent_kl, 5)}
    out["max_weight_shift"] = round(float((W.detach() - W0).abs().max()), 4)
    out["policy"] = new
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--collect", help="write the dataset (.npz) here")
    p.add_argument("--data", help="fit from this dataset")
    p.add_argument("--seeds", default="1008,1,2")
    p.add_argument("--ticks", type=int, default=1200)
    p.add_argument("--every", type=int, default=20)
    p.add_argument("--version", type=int, default=2)
    p.add_argument("--prior-weight", type=float, default=1.0, dest="prior_weight")
    p.add_argument("--l2", type=float, default=1e-2)
    p.add_argument("--iterations", type=int, default=150)
    p.add_argument("--max-silent-kl", type=float, default=0.15, dest="max_silent_kl")
    p.add_argument("--no-write", action="store_true", dest="no_write")
    p.add_argument("--out", help="JSON report")
    args = p.parse_args(argv)
    _paths()
    import numpy as np
    if args.collect:
        data = asyncio.run(collect([int(s) for s in args.seeds.split(",") if s], args.ticks, args.every))
        np.savez_compressed(args.collect, **data)
        print(json.dumps({"rows": int(len(data["Y"])), "labelled": int((data["Y"] >= 0).sum()), "data_hash": data_hash(data)}))
        if not args.data:
            return 0
    if not args.data and not args.collect:
        p.error("--collect or --data is required")
    path = args.data or args.collect
    with np.load(path) as loaded:
        data = {k: loaded[k] for k in loaded.files}
    result = fit(data, prior_weight=args.prior_weight, l2=args.l2, iterations=args.iterations)
    policy = result.pop("policy")
    test = result["test"]
    improved = test["agreement_new"] > test["agreement_prior"]
    bounded = test["silent_kl_to_prior"] <= args.max_silent_kl
    report = {"data": path, "data_hash": data_hash(data), "rows": int(len(data["Y"])), "hyper": {"prior_weight": args.prior_weight, "l2": args.l2, "iterations": args.iterations},
              **result, "gate": {"improved_on_holdout": improved, "silent_kl_bounded": bounded, "max_silent_kl": args.max_silent_kl}, "written": False}
    if improved and bounded and not args.no_write:
        from systems.decision import matrix
        target = matrix.default_weights_path(args.version)
        policy.version = args.version
        report["weights_hash"] = policy.save(target)
        report["written"] = str(target)
        target.with_suffix(".provenance.json").write_text(json.dumps({**{k: v for k, v in report.items() if k != "written"}, "format": matrix.WEIGHTS_FORMAT,
                                                                       "schema": matrix.FEATURE_SCHEMA_VERSION, "prior": "MatrixPolicy.initial() (weights v1)"}, indent=1), encoding="utf-8")
    else:
        report["note"] = "not written: the rules prior (weights v1) stays the answer" if not (improved and bounded) else "dry run"
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
