"""Data-only snapshot codec. Never imports classes or unpickles save contents."""
from __future__ import annotations

import base64
import json
import math

import numpy as np
import torch

MAX_BYTES = 128 * 1024 * 1024
DTYPES = {"float32", "float64", "int8", "int16", "int32", "int64", "uint8", "uint32", "uint64", "bool"}


def encode(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"t": "float", "v": str(value)}
    if isinstance(value, np.generic):
        return encode(value.item())
    if isinstance(value, (torch.Tensor, np.ndarray)):
        array = value.detach().cpu().numpy() if isinstance(value, torch.Tensor) else value
        if array.dtype.name not in DTYPES or array.nbytes > MAX_BYTES:
            raise ValueError("Unsupported snapshot array")
        return {"t": "tensor" if isinstance(value, torch.Tensor) else "array",
                "dtype": array.dtype.name, "shape": list(array.shape),
                "v": base64.b64encode(array.tobytes()).decode("ascii")}
    if isinstance(value, dict):
        return {"t": "dict", "v": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (list, tuple, set)):
        return {"t": type(value).__name__, "v": [encode(v) for v in value]}
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def decode(value):
    if not isinstance(value, dict):
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise ValueError("Malformed snapshot value")
    kind = value["t"]
    if kind in ("tensor", "array"):
        if value["dtype"] not in DTYPES:
            raise ValueError("Unsupported array dtype")
        shape = value["shape"]
        if not isinstance(shape, list) or len(shape) > 8 or any(type(n) is not int or n < 0 for n in shape):
            raise ValueError("Invalid array shape")
        dtype = np.dtype(value["dtype"])
        size = math.prod(shape) * dtype.itemsize
        if size > MAX_BYTES:
            raise ValueError("Snapshot array too large")
        raw = base64.b64decode(value["v"], validate=True)
        if len(raw) != size:
            raise ValueError("Snapshot array length mismatch")
        array = np.frombuffer(raw, dtype=dtype).reshape(shape).copy()
        return torch.from_numpy(array) if kind == "tensor" else array
    if kind == "dict":
        return {decode(k): decode(v) for k, v in value["v"]}
    if kind in ("list", "tuple", "set"):
        values = [decode(v) for v in value["v"]]
        return {"list": list, "tuple": tuple, "set": set}[kind](values)
    if kind == "float" and value["v"] in ("inf", "-inf", "nan"):
        return float(value["v"])
    raise ValueError("Unknown snapshot type")


def dumps(value) -> bytes:
    data = json.dumps(encode(value), separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("World snapshot exceeds size limit")
    return data


def loads(data: bytes):
    if len(data) > MAX_BYTES:
        raise ValueError("World snapshot exceeds size limit")
    return decode(json.loads(data))
