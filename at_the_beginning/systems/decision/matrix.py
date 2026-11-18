"""Tier 1: the matrix policy. One batched torch computation decides for a whole population.

    S = X @ W + (X @ U) * (P @ V) + b          (N x K)   scores
    S[i, current_i] += hysteresis * stickiness_i           keep doing what you are doing unless something clearly beats it
    probabilities = masked softmax(S / temperature)        illegal options get exactly 0

``X`` (N x F) is the versioned feature matrix (needs, pressures, scene flags, commission context), ``P`` (N x 16) the personality
traits, ``M`` (N x K) the legality mask computed by Python from facts (the affordance engine will supply it later; here it is an input).
``K`` is a fixed vocabulary: 24 macro-actions plus the six commission outcomes. Rules are a special case: ``W``, ``U``, ``V``, ``b`` are
initialised from the hand-written commission scorer (``systems/commission/decide.py``), so on that topic the matrix reproduces
``RulesDecisionProvider`` exactly; the 24 macro-action weights are NEW placeholders (see ``MACRO_SPEC``), not distilled from anything.
No training code lives here. A confidence gate decides which rows should be sent on to Tier 2.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from .contract import DecisionError
from .providers import SOFTMAX_TEMPERATURE, DecisionProvider, RulesDecisionProvider

FEATURE_SCHEMA_VERSION = 1
WEIGHTS_FORMAT = "eden-matrix-weights"

FEATURES = (
    "hunger", "thirst", "low_stamina", "low_hp", "threat", "low_mood",                       # needs, 0..1 (low_* = 1 - value/100)
    "fear", "vengeance", "security", "curiosity", "loyalty",                                  # pressures (personality/appraisal.py), 0..1
    "is_night", "at_home", "at_station", "near_food", "near_water", "near_danger", "near_kin", "near_stranger",
    "has_food_item", "plan_active", "plan_step_failed", "goal_urgency",                       # scene and plan flags, 0..1
    "closeness", "rival",                                                                     # relationship to the other party (commission)
    "one",                                                                                    # constant 1: lets personality act alone
)
TRAITS = ("aggression", "caution", "vengefulness", "greed", "loyalty", "mercy", "pride", "fearfulness", "curiosity", "ambition",
          "deceitfulness", "protectiveness", "sociability", "discipline", "resourcefulness", "resolve")   # systems/personality/catalog.py
MACRO_ACTIONS = ("eat", "drink", "rest", "sleep", "work_at_station", "gather", "go_home", "socialise", "trade", "help", "avoid", "flee",
                 "defend", "attack", "explore", "build", "repair", "ask_for_help", "hide", "idle", "continue_plan_step",
                 "USE_BRAIN", "REPLAN", "PLOT")
COMMISSION_OUTCOMES = ("accept_commission", "refuse_no_materials", "refuse_no_forge", "refuse_cannot_afford", "refuse_busy",
                       "refuse_distrust")
MENU = MACRO_ACTIONS + COMMISSION_OUTCOMES
F, P_DIM, K = len(FEATURES), len(TRAITS), len(MENU)
FEATURE_INDEX = {name: i for i, name in enumerate(FEATURES)}
TRAIT_INDEX = {name: i for i, name in enumerate(TRAITS)}
ACTION_INDEX = {name: i for i, name in enumerate(MENU)}
COGNITIVE = ("USE_BRAIN", "REPLAN", "PLOT")   # options that route to a higher tier when chosen
DEFAULT_TRAIT = 0.5
DEFAULT_HYSTERESIS = 0.35
WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"

# action -> {"b": bias, "w": {feature: weight}, "mod": (feature, {trait: weight}) -> + feature * (traits . weights)}.
# "mod" with feature "one" is a plain linear personality bias; with another feature it is a bilinear interaction.
MACRO_SPEC = {
    "eat": {"b": -1.2, "w": {"hunger": 4.0, "has_food_item": 0.6, "near_food": 0.5, "threat": -1.5}},
    "drink": {"b": -1.2, "w": {"thirst": 4.2, "near_water": 0.5, "threat": -1.5}},
    "rest": {"b": -0.6, "w": {"low_stamina": 2.5, "low_hp": 1.0, "is_night": 0.3, "threat": -1.5}},
    "sleep": {"b": -1.5, "w": {"is_night": 2.0, "low_stamina": 1.5, "at_home": 0.8, "threat": -2.0}},
    "work_at_station": {"b": -0.2, "w": {"at_station": 1.5, "is_night": -1.0, "plan_active": 0.3, "hunger": -1.0, "thirst": -1.0, "threat": -2.0},
                        "mod": ("one", {"discipline": 0.6})},
    "gather": {"b": -0.8, "w": {"near_food": 0.5, "hunger": 0.8, "threat": -1.5}, "mod": ("one", {"resourcefulness": 0.5})},
    "go_home": {"b": -0.6, "w": {"is_night": 1.2, "at_home": -2.0, "low_hp": 0.8, "security": 0.8}},
    "socialise": {"b": -0.7, "w": {"near_kin": 0.8, "near_stranger": 0.5, "low_mood": 1.0, "threat": -2.0, "is_night": -0.5},
                  "mod": ("one", {"sociability": 1.2})},
    "trade": {"b": -1.2, "w": {"near_stranger": 0.8, "has_food_item": 0.3}, "mod": ("one", {"greed": 0.5, "sociability": 0.4})},
    "help": {"b": -1.3, "w": {"near_kin": 0.8, "loyalty": 1.0}, "mod": ("one", {"protectiveness": 0.8, "mercy": 0.5})},
    "avoid": {"b": -1.0, "w": {"near_stranger": 0.5, "security": 1.0, "near_danger": 0.8}, "mod": ("one", {"caution": 0.8, "fearfulness": 0.5})},
    "flee": {"b": -2.0, "w": {"threat": 3.0, "fear": 1.5, "near_danger": 1.5, "low_hp": 1.0},
             "mod": ("one", {"fearfulness": 1.0, "caution": 0.5, "aggression": -1.0})},
    "defend": {"b": -1.8, "w": {"threat": 2.0, "near_kin": 1.0, "loyalty": 0.8}, "mod": ("one", {"protectiveness": 1.0, "resolve": 0.6})},
    "attack": {"b": -2.5, "w": {"vengeance": 2.0, "rival": 0.8}, "mod": ("threat", {"aggression": 2.0, "mercy": -1.0})},
    "explore": {"b": -1.4, "w": {"curiosity": 1.5, "goal_urgency": -1.0, "threat": -2.0, "is_night": -1.0}, "mod": ("one", {"curiosity": 1.0})},
    "build": {"b": -1.6, "w": {"plan_active": 0.8}, "mod": ("one", {"resourcefulness": 0.5, "ambition": 0.5})},
    "repair": {"b": -1.6, "w": {"plan_active": 0.5}, "mod": ("one", {"resourcefulness": 0.5, "discipline": 0.4})},
    "ask_for_help": {"b": -1.8, "w": {"low_hp": 1.5, "threat": 1.0, "near_kin": 1.0}, "mod": ("one", {"sociability": 0.5, "fearfulness": 0.4})},
    "hide": {"b": -2.0, "w": {"threat": 2.0, "fear": 1.5, "near_danger": 1.0}, "mod": ("one", {"caution": 0.7, "fearfulness": 0.8})},
    "idle": {"b": 0.2, "w": {}},
    "continue_plan_step": {"b": 0.0, "w": {"plan_active": 1.5, "plan_step_failed": -3.0}},
    "USE_BRAIN": {"b": -2.0, "w": {"goal_urgency": 1.5, "plan_step_failed": 1.0, "near_stranger": 0.3}},
    "REPLAN": {"b": -2.4, "w": {"plan_step_failed": 3.0, "plan_active": 0.3}},
    "PLOT": {"b": -3.0, "w": {"vengeance": 2.0, "rival": 1.0, "goal_urgency": 0.5}, "mod": ("one", {"vengefulness": 1.0, "ambition": 0.8})},
}
# The commission scorer (systems/commission/decide.py::commission_scorer) written as matrix entries. Constants are folded into b:
#   accept = 1.0 + 1.2 closeness + 0.6 (greed - .5) + 0.4 (discipline - .5) - 0.3 security
#   refuse_distrust = 0.4 + 1.0 vengeance - 0.8 closeness + 1.0 rival      refuse_* = constants 3.0 / 2.5 / 2.0 / 1.5
COMMISSION_SPEC = {
    "accept_commission": {"b": 1.0 - 0.3 - 0.2, "w": {"closeness": 1.2, "security": -0.3}, "mod": ("one", {"greed": 0.6, "discipline": 0.4})},
    "refuse_distrust": {"b": 0.4, "w": {"vengeance": 1.0, "closeness": -0.8, "rival": 1.0}},
    "refuse_no_forge": {"b": 3.0, "w": {}}, "refuse_no_materials": {"b": 2.5, "w": {}},
    "refuse_cannot_afford": {"b": 2.0, "w": {}}, "refuse_busy": {"b": 1.5, "w": {}},
}


def initial_arrays():
    """W, U, V, b as float64 numpy arrays built from MACRO_SPEC and COMMISSION_SPEC."""
    W, U, V, b = np.zeros((F, K)), np.zeros((F, K)), np.zeros((P_DIM, K)), np.zeros(K)
    for name, spec in {**MACRO_SPEC, **COMMISSION_SPEC}.items():
        k = ACTION_INDEX[name]
        b[k] = spec["b"]
        for feature, weight in spec["w"].items():
            W[FEATURE_INDEX[feature], k] = weight
        if "mod" in spec:
            feature, traits = spec["mod"]
            U[FEATURE_INDEX[feature], k] = 1.0
            for trait, weight in traits.items():
                V[TRAIT_INDEX[trait], k] = weight
    return W, U, V, b


def arrays_hash(W, U, V, b, temperature, hysteresis) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps({"format": WEIGHTS_FORMAT, "schema": FEATURE_SCHEMA_VERSION, "features": FEATURES, "traits": TRAITS,
                              "menu": MENU, "temperature": float(temperature), "hysteresis": float(hysteresis)},
                             sort_keys=True).encode("utf-8"))
    for array in (W, U, V, b):
        digest.update(np.ascontiguousarray(array, dtype="<f8").tobytes())
    return digest.hexdigest()


@dataclass
class MatrixResult:
    probabilities: torch.Tensor   # N x K, rows sum to 1 over legal options (all zero when no option is legal)
    action: torch.Tensor          # N, index into MENU of the argmax (-1 when nothing is legal)
    top_p: torch.Tensor           # N
    margin: torch.Tensor          # N, top_p minus the runner-up
    no_legal: torch.Tensor        # N bool

    def names(self):
        return [MENU[i] if i >= 0 else None for i in self.action.tolist()]


@dataclass
class GateConfig:
    """When is a Tier 1 answer too uncertain to be final? Tuned later from shadow data; these are placeholders."""
    min_top_p: float = 0.45
    min_margin: float = 0.10


class MatrixPolicy:
    def __init__(self, W, U, V, b, temperature: float = SOFTMAX_TEMPERATURE, hysteresis: float = DEFAULT_HYSTERESIS,
                 version: int = 1, dtype=torch.float64):
        if temperature <= 0 or not math.isfinite(temperature):
            raise ValueError("temperature must be finite and > 0")
        self.dtype = dtype
        self.version = int(version)
        self.temperature, self.hysteresis = float(temperature), float(hysteresis)
        arrays = [np.asarray(a, dtype="<f8") for a in (W, U, V, b)]
        for a, shape, label in zip(arrays, ((F, K), (F, K), (P_DIM, K), (K,)), "WUVb"):
            if a.shape != shape or not np.isfinite(a).all():
                raise ValueError(f"{label} must be finite with shape {shape}, got {a.shape}")
        self._np = arrays
        self.W, self.U, self.V, self.b = (torch.as_tensor(a, dtype=dtype) for a in arrays)
        self.weights_hash = arrays_hash(*arrays, self.temperature, self.hysteresis)

    @classmethod
    def initial(cls, **kw) -> "MatrixPolicy":
        return cls(*initial_arrays(), **kw)

    def _t(self, value, shape, label):
        tensor = torch.as_tensor(value, dtype=self.dtype)
        if tuple(tensor.shape[1:]) != shape:
            raise ValueError(f"{label} must be N x {shape}, got {tuple(tensor.shape)}")
        return tensor

    def scores(self, X, P, current=None, stickiness=None) -> torch.Tensor:
        """S = X@W + (X@U)*(P@V) + b, plus the hysteresis bonus on each row's running action."""
        X, P = self._t(X, (F,), "X"), self._t(P, (P_DIM,), "P")
        S = X @ self.W + (X @ self.U) * (P @ self.V) + self.b
        if current is not None:
            current = torch.as_tensor(current, dtype=torch.long)
            stick = torch.ones(len(current), dtype=self.dtype) if stickiness is None else torch.as_tensor(stickiness, dtype=self.dtype)
            rows = torch.nonzero(current >= 0).squeeze(1)
            if len(rows):
                S[rows, current[rows]] += self.hysteresis * stick[rows]
        return S

    def decide(self, X, P, M, current=None, stickiness=None) -> MatrixResult:
        S = self.scores(X, P, current, stickiness)
        legal = torch.as_tensor(M, dtype=torch.bool)
        if legal.shape != S.shape:
            raise ValueError(f"M must be N x {K}, got {tuple(legal.shape)}")
        no_legal = ~legal.any(dim=1)
        masked = S.masked_fill(~legal, float("-inf")) / self.temperature
        masked = torch.where(no_legal[:, None], torch.zeros_like(masked), masked)       # avoid NaN rows
        probs = torch.softmax(masked, dim=1) * legal
        probs = torch.where(no_legal[:, None], torch.zeros_like(probs), probs / probs.sum(dim=1, keepdim=True).clamp_min(1e-300))
        top, idx = probs.max(dim=1)
        runner = probs.scatter(1, idx[:, None], -1.0).max(dim=1).values.clamp_min(0.0)
        return MatrixResult(probs, torch.where(no_legal, torch.full_like(idx, -1), idx), top, top - runner, no_legal)

    def probabilities(self, X, P, M, current=None, stickiness=None) -> torch.Tensor:
        return self.decide(X, P, M, current, stickiness).probabilities

    def gate(self, result: MatrixResult, significant, config: GateConfig | None = None) -> torch.Tensor:
        """N bool: rows that should escalate to Tier 2 (uncertain AND the situation matters). Rows with nothing legal never escalate."""
        config = config or GateConfig()
        sig = torch.as_tensor(significant, dtype=torch.bool)
        uncertain = (result.top_p < config.min_top_p) | (result.margin < config.min_margin)
        return uncertain & sig & ~result.no_legal

    # ---- weights file ---------------------------------------------------------------------------------------------

    def save(self, path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        W, U, V, b = self._np
        np.savez(path, W=W, U=U, V=V, b=b, version=np.int64(self.version), schema=np.int64(FEATURE_SCHEMA_VERSION),
                 temperature=np.float64(self.temperature), hysteresis=np.float64(self.hysteresis), hash=np.array(self.weights_hash),
                 features=np.array(FEATURES), traits=np.array(TRAITS), menu=np.array(MENU), format=np.array(WEIGHTS_FORMAT))
        return self.weights_hash

    @classmethod
    def load(cls, path, dtype=torch.float64) -> "MatrixPolicy":
        with np.load(path, allow_pickle=False) as data:
            if str(data["format"]) != WEIGHTS_FORMAT:
                raise DecisionError(f"{path}: not a matrix weights file")
            if int(data["schema"]) != FEATURE_SCHEMA_VERSION or tuple(data["features"]) != FEATURES or tuple(data["menu"]) != MENU \
                    or tuple(data["traits"]) != TRAITS:
                raise DecisionError(f"{path}: feature schema or menu does not match this build (schema {int(data['schema'])})")
            policy = cls(data["W"], data["U"], data["V"], data["b"], float(data["temperature"]), float(data["hysteresis"]),
                         int(data["version"]), dtype)
            if policy.weights_hash != str(data["hash"]):
                raise DecisionError(f"{path}: hash mismatch (file says {str(data['hash'])[:12]}, content is {policy.weights_hash[:12]})")
        return policy

    def describe(self) -> dict:
        return {"version": self.version, "hash": self.weights_hash, "feature_schema": FEATURE_SCHEMA_VERSION, "features": F, "actions": K,
                "temperature": self.temperature, "hysteresis": self.hysteresis}


def default_weights_path(version: int = 1) -> Path:
    return WEIGHTS_DIR / f"weights_v{version}.npz"


# ---- featurizers ------------------------------------------------------------------------------------------------------

def trait_matrix(personalities) -> torch.Tensor:
    """N x 16 from a list of trait dicts (missing traits default to 0.5)."""
    rows = [[float(p.get(name, DEFAULT_TRAIT)) for name in TRAITS] for p in personalities]
    return torch.tensor(rows, dtype=torch.float64).reshape(len(rows), P_DIM)


def commission_features(state: dict):
    """(x[F], p[16]) from the ``state`` snapshot of a commission DecisionRequest (what DecisionLog records)."""
    x = torch.zeros(F, dtype=torch.float64)
    pressures = state.get("pressures", {}) or {}
    x[FEATURE_INDEX["closeness"]] = float(state.get("closeness", 0.0))
    x[FEATURE_INDEX["rival"]] = 1.0 if state.get("rival") else 0.0
    x[FEATURE_INDEX["security"]] = float(pressures.get("security", 0.0))
    x[FEATURE_INDEX["vengeance"]] = float(pressures.get("vengeance", 0.0))
    x[FEATURE_INDEX["one"]] = 1.0
    return x, trait_matrix([state.get("traits", {}) or {}])[0]


def population_features(h_tensor, rows, extras: dict | None = None) -> torch.Tensor:
    """N x F for the human rows ``rows`` of ``h_tensor``: needs from the tensor in one vectorised read, the rest from ``extras``
    ({feature name: length-N array}, from perception/plan/personality code; missing features are 0)."""
    import genesis_config as cfg
    rows = torch.as_tensor(rows, dtype=torch.long)
    h = h_tensor[rows].to(torch.float64)
    X = torch.zeros(len(rows), F, dtype=torch.float64)
    X[:, FEATURE_INDEX["hunger"]] = (h[:, cfg.HUNGER] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["thirst"]] = (h[:, cfg.THIRST] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_stamina"]] = (1.0 - h[:, cfg.H_STAMINA] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_hp"]] = (1.0 - h[:, cfg.HP] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["threat"]] = (h[:, cfg.THREAT] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_mood"]] = (1.0 - h[:, cfg.MOOD] / 100.0).clamp(0, 1)
    for name, values in (extras or {}).items():
        if name not in FEATURE_INDEX or name == "one":
            raise ValueError(f"unknown feature {name!r}")
        X[:, FEATURE_INDEX[name]] = torch.as_tensor(values, dtype=torch.float64).clamp(0, 1)
    X[:, FEATURE_INDEX["one"]] = 1.0
    return X


# ---- provider on the existing seam ------------------------------------------------------------------------------------

class MatrixDecisionProvider(DecisionProvider):
    """Tier 1 behind the existing ``DecisionProvider`` interface: for topics with a featurizer it answers from the matrix over
    exactly the offered (legal) options; any other topic is handed to ``fallback`` (rules), so enabling the matrix never narrows
    what can be decided. Offered options outside the menu are an error (the service falls back to rules)."""
    mode = "matrix"

    def __init__(self, policy: MatrixPolicy | None = None, fallback: DecisionProvider | None = None):
        self.policy = policy or MatrixPolicy.initial()
        self.fallback = fallback or RulesDecisionProvider()
        self.featurizers = {"commission": commission_features}
        self.last_mode = None

    def decide(self, request):
        featurize = self.featurizers.get(request.topic)
        if featurize is None:
            self.last_mode = self.fallback.mode
            return self.fallback.decide(request)
        ids = [o.id for o in request.options]
        unknown = [i for i in ids if i not in ACTION_INDEX]
        if unknown:
            raise DecisionError(f"options outside the matrix menu: {unknown}")
        x, p = featurize(request.state)
        mask = torch.zeros(1, K, dtype=torch.bool)
        mask[0, [ACTION_INDEX[i] for i in ids]] = True
        probs = self.policy.probabilities(x[None], p[None], mask)[0]
        self.last_mode = "matrix"
        return {i: float(probs[ACTION_INDEX[i]]) for i in ids}


# ---- benchmark --------------------------------------------------------------------------------------------------------

def benchmark(n: int = 100, repeats: int = 2000, seed: int = 0, policy: MatrixPolicy | None = None) -> dict:
    """Measured wall time of one batched ``decide`` for ``n`` residents (inputs prebuilt; this is the policy cost, not featurizing)."""
    policy = policy or MatrixPolicy.initial()
    gen = torch.Generator().manual_seed(seed)
    X = torch.rand(n, F, generator=gen, dtype=torch.float64)
    X[:, FEATURE_INDEX["one"]] = 1.0
    P = torch.rand(n, P_DIM, generator=gen, dtype=torch.float64)
    M = torch.rand(n, K, generator=gen) > 0.3
    M[:, ACTION_INDEX["idle"]] = True
    current = torch.randint(0, K, (n,), generator=gen)
    for _ in range(50):
        policy.decide(X, P, M, current)
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        policy.decide(X, P, M, current)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return {"residents": n, "repeats": repeats, "mean_ms": round(sum(times) / len(times), 4), "p50_ms": round(times[len(times) // 2], 4),
            "p99_ms": round(times[int(len(times) * 0.99) - 1], 4), "max_ms": round(times[-1], 4), "dtype": str(policy.dtype),
            "torch_threads": torch.get_num_threads()}
