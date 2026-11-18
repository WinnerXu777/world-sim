"""Export JSON Schema and OpenAPI 3.1 from the contract dataclasses.

``python -m model_server.schema --write`` regenerates ``schema_v1.json`` and ``openapi_v1.json``; a test fails when the
committed files differ from what the dataclasses generate.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import typing
from pathlib import Path

from . import contract as c

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema_v1.json"
OPENAPI_PATH = HERE / "openapi_v1.json"
_KEYWORDS = ("enum", "minimum", "maximum", "minLength", "minItems", "maxItems", "description", "default")


def _type_schema(tp) -> dict:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        inner = _type_schema(non_none[0])
        return {"anyOf": [inner, {"type": "null"}]} if len(non_none) == 1 else {"anyOf": [_type_schema(a) for a in non_none]}
    if origin is list:
        return {"type": "array", "items": _type_schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object", "additionalProperties": _type_schema(args[1]) if len(args) == 2 else True}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is str:
        return {"type": "string"}
    if tp is dict:
        return {"type": "object"}
    if dataclasses.is_dataclass(tp):
        return {"$ref": f"#/$defs/{tp.__name__}"}
    raise TypeError(f"no JSON Schema mapping for {tp!r}")


def dataclass_schema(cls) -> dict:
    hints = typing.get_type_hints(cls, vars(c))
    properties, required = {}, []
    for f in dataclasses.fields(cls):
        schema = _type_schema(hints[f.name])
        for key in _KEYWORDS:
            if key in f.metadata:
                schema[key] = f.metadata[key]
        properties[f.name] = schema
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            required.append(f.name)
    schema = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    if cls.__doc__:
        schema["description"] = " ".join(cls.__doc__.split())
    return schema


def json_schema() -> dict:
    defs = {cls.__name__: dataclass_schema(cls) for cls in c.ALL_TYPES}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "eden-model-contract-v1",
            "title": "Eden model plane wire contract", "x-schema-version": c.SCHEMA_VERSION, "$defs": defs}


def openapi() -> dict:
    schemas = json_schema()["$defs"]
    paths = {}
    for role, route in c.ROLE_ROUTES.items():
        paths[route] = {"post": {
            "operationId": f"model_{role}", "summary": f"Run the {role} role",
            "description": f"Request: Envelope with role={role!r} and payload {c.PAYLOAD_TYPES[role].__name__}. "
                           f"Reply: ResponseEnvelope with result {c.RESULT_TYPES[role].__name__}.",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}}},
            "responses": {
                "200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ResponseEnvelope"}}}},
                **{str(code): {"description": text, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ResponseEnvelope"}}}}
                   for code, text in ((400, "malformed_request, invalid_payload, unknown_role, schema_version_unsupported"),
                                      (501, "backend_not_implemented"), (502, "backend_error"),
                                      (503, "backend_unavailable"), (504, "deadline_exceeded"))}}}}
    paths["/v1/cancel"] = {"post": {"summary": "Abandon work for a cancel_token",
                                    "requestBody": {"content": {"application/json": {"schema": {
                                        "type": "object", "required": ["cancel_token"],
                                        "properties": {"cancel_token": {"type": "string"}}}}}},
                                    "responses": {"200": {"description": "ok"}}}}
    for path, summary in (("/health", "Process is up"), ("/ready", "Every configured backend can answer"),
                          ("/v1/models", "Role to backend and model id"), ("/v1/contract", "This contract (JSON Schema)")):
        paths[path] = {"get": {"summary": summary, "responses": {"200": {"description": "ok"}}}}
    return {"openapi": "3.1.0", "info": {"title": "Eden model plane", "version": f"contract-v{c.SCHEMA_VERSION}"},
            "paths": paths, "components": {"schemas": schemas}}


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--write" in argv:
        SCHEMA_PATH.write_text(render(json_schema()), encoding="utf-8", newline="\n")
        OPENAPI_PATH.write_text(render(openapi()), encoding="utf-8", newline="\n")
        print(f"wrote {SCHEMA_PATH.name} and {OPENAPI_PATH.name}")
    else:
        print(render(openapi()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
