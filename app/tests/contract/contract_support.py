"""Helpers for the blind contract tests: the served HTTP contract as data, a validator for a body against its declared
schema, and apps built through the public factory."""

import json
import socket
from pathlib import Path
from typing import Any

from ashley.main import create_app
from ashley.settings import Settings
from fastapi.testclient import TestClient

OPENAPI: dict[str, Any] = json.loads((Path(__file__).parents[2] / "openapi.json").read_text())
JSON_TYPES: dict[str, type[object] | tuple[type[object], ...]] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": dict,
    "array": list,
}


def resolve(schema: dict[str, Any]) -> dict[str, Any]:
    """Follow a `$ref` into `components.schemas`."""
    ref = schema.get("$ref")
    if ref is None:
        return schema
    name = ref.rsplit("/", 1)[1]
    return OPENAPI["components"]["schemas"][name]


def violations(schema: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """Every way `body` fails the declared object schema: missing field, wrong type, value other than a `const`."""
    schema = resolve(schema)
    problems: list[str] = []
    for field in schema.get("required", []):
        if field not in body:
            problems.append(f"missing {field}")
    for field, spec in schema["properties"].items():
        if field not in body:
            continue
        value = body[field]
        expected = JSON_TYPES[spec["type"]]
        if isinstance(value, bool) and spec["type"] in ("integer", "number"):
            problems.append(f"{field} is a bool, declared {spec['type']}")
        elif not isinstance(value, expected):
            problems.append(f"{field} is {type(value).__name__}, declared {spec['type']}")
        elif "const" in spec and value != spec["const"]:
            problems.append(f"{field}={value!r}, declared const {spec['const']!r}")
    return problems


def declared_responses(path: str, method: str = "get") -> dict[str, dict[str, Any]]:
    """The status code to response schema map the contract declares for `method` on `path`; a response whose declared
    body is not JSON (audio), or that has no body (a redirect, a 204), maps to an empty schema."""
    out: dict[str, dict[str, Any]] = {}
    for code, response in OPENAPI["paths"][path][method]["responses"].items():
        content = response.get("content", {})
        out[code] = content["application/json"]["schema"] if "application/json" in content else {}
    return out


def closed_port() -> int:
    """A local TCP port nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def unreachable_conninfo(password: str = "pw") -> str:
    return f"host=127.0.0.1 port={closed_port()} dbname=ashley user=postgres password={password} connect_timeout=3"


def client(conninfo: str, build_version: str = "dev", **kwargs: Any) -> TestClient:
    """A client over the app the factory builds; use it as a context manager so startup and shutdown run."""
    return TestClient(create_app(Settings(database_url=conninfo, build_version=build_version)), **kwargs)
