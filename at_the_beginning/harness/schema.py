"""A small JSON Schema subset: build schemas from Python signatures and validate values against them.

``jsonschema`` is not installed in the venv, and the harness only needs a strict subset: ``type`` (including lists),
``enum``, ``const``, ``minimum``/``maximum``, ``minLength``, ``items``, ``minItems``/``maxItems``, ``properties`` with
``required`` and ``additionalProperties: false``, and ``anyOf``. Errors are returned as ``"<json path>: message"`` strings so a
model gets structured, repairable feedback.
"""
from __future__ import annotations

import enum
import inspect
import typing
from typing import Any, Callable, Iterable

_TYPE_NAMES = {"string": str, "boolean": bool, "object": dict, "array": (list, tuple), "null": type(None)}


def _is_type(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPE_NAMES[name])


def validate(schema: dict, value: Any, path: str = "$") -> list:
    """List of error strings; empty means ``value`` conforms."""
    errors: list[str] = []
    if "anyOf" in schema:
        branches = [validate(branch, value, path) for branch in schema["anyOf"]]
        if all(branches):
            errors.append(f"{path}: matches none of the allowed shapes ({'; '.join(b[0] for b in branches)})")
        return errors
    if "const" in schema and value != schema["const"]:
        return [f"{path}: must equal {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} is not one of {list(schema['enum'])}"]
    wanted = schema.get("type")
    if wanted is not None:
        names = [wanted] if isinstance(wanted, str) else list(wanted)
        if not any(_is_type(value, n) for n in names):
            return [f"{path}: expected {' or '.join(names)}, got {type(value).__name__}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} is above the maximum {schema['maximum']}")
        if value != value or value in (float("inf"), float("-inf")):
            errors.append(f"{path}: must be finite")
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: shorter than {schema['minLength']} characters")
    if isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate(schema["items"], item, f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required field {name!r}")
        for name, item in value.items():
            if name in props:
                errors.extend(validate(props[name], item, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown field {name!r} (allowed: {sorted(props)})")
    return errors


# -- schemas from signatures ------------------------------------------------------------------------------------------
def schema_for_type(annotation) -> dict:
    """JSON Schema for a Python annotation (the subset the capability manifest uses)."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is str:
        return {"type": "string"}
    if annotation is type(None):
        return {"type": "null"}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {"enum": [m.value for m in annotation]}
    if origin is typing.Literal:
        return {"enum": list(args)}
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", object())):
        return {"anyOf": [schema_for_type(a) for a in args]}
    if origin in (list, tuple, set, frozenset, Iterable) or annotation in (list, tuple):
        out = {"type": "array"}
        if args:
            out["items"] = schema_for_type(args[0])
        return out
    if origin is dict or annotation is dict:
        return {"type": "object"}
    return {}


def schema_for_function(fn: Callable, skip: Iterable[str] = ("world", "ctx", "self", "cls")) -> dict:
    """Object schema for the parameters of ``fn`` (parameters named in ``skip`` and ``*args``/``**kwargs`` are omitted)."""
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - unresolved forward references: fall back to raw annotations
        hints = {}
    properties, required = {}, []
    for name, param in signature.parameters.items():
        if name in skip or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        schema = schema_for_type(hints.get(name, param.annotation))
        if param.default is not inspect.Parameter.empty and param.default is not None:
            schema = {**schema, "default": param.default} if isinstance(param.default, (int, float, str, bool)) else schema
        properties[name] = schema
        if param.default is inspect.Parameter.empty:
            required.append(name)
    out = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out
