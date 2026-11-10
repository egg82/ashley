"""Contract gates (`~/.claude/skills/api-contract-first/SKILL.md`). Each iterates a whole population of the spec and
asserts it was non-empty, and each has a control: a planted spec it must reject."""

import json
import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

import pytest

from export_openapi import SPEC_FILE, build_spec, render

Spec = dict[str, Any]
REGEN = "regenerate: cd app && python tools/export_openapi.py, then cd app/web && npm run types"


@pytest.fixture(scope="module")
def spec() -> Spec:
    return build_spec()


def operations(spec: Spec) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in spec["paths"].items():
        for method, op in item.items():
            yield path, method, op


def json_schemas(spec: Spec) -> Iterator[tuple[str, dict[str, Any]]]:
    """(where, schema) for every JSON response of every operation."""
    for path, method, op in operations(spec):
        for status, response in op["responses"].items():
            content = response.get("content", {}).get("application/json")
            if content is not None:
                yield f"{method} {path} {status}", content.get("schema", {})


def prop_type(p: dict[str, Any]) -> Any:
    if "$ref" in p:
        return p["$ref"]
    if "anyOf" in p:  # Optional[X] is X: nullability is not a different type
        alts = [x for x in p["anyOf"] if x.get("type") != "null"]
        return prop_type(alts[0]) if len(alts) == 1 else sorted(json.dumps(prop_type(x)) for x in alts)
    if p.get("type") == "array":
        return ["array", prop_type(p.get("items", {}))]
    return [p.get("type"), p.get("format")]


def split_types(spec: Spec) -> tuple[int, dict[str, set[str]]]:
    """(how many distinct field names were seen, the names that resolve to more than one type)."""
    seen: dict[str, set[str]] = defaultdict(set)
    for schema in spec.get("components", {}).get("schemas", {}).values():
        for name, p in schema.get("properties", {}).items():
            seen[name].add(json.dumps(prop_type(p), sort_keys=True))
    return len(seen), {name: kinds for name, kinds in seen.items() if len(kinds) > 1}


def unnamed(spec: Spec) -> tuple[int, list[str]]:
    """(how many JSON responses were examined, those whose schema is not a named component with properties)."""
    schemas = spec.get("components", {}).get("schemas", {})
    bad: list[str] = []
    total = 0
    for where, schema in json_schemas(spec):
        total += 1
        target = schema.get("items", schema) if schema.get("type") == "array" else schema
        ref = target.get("$ref", "")
        name = ref.rsplit("/", 1)[-1]
        if not ref or "properties" not in schemas.get(name, {}):
            bad.append(where)
    return total, bad


def unreadable_ids(spec: Spec) -> tuple[int, list[str]]:
    ids = [op.get("operationId", "") for _, _, op in operations(spec)]
    return len(ids), sorted(i for i in ids if not re.fullmatch(r"[a-z]+(_[a-z]+)*", i) or "_api_" in i)


def repeated_ids(spec: Spec) -> list[str]:
    seen = [op.get("operationId", "") for _, _, op in operations(spec)]
    return sorted({i for i in seen if seen.count(i) > 1})


def test_the_committed_spec_is_what_the_app_generates(spec: Spec) -> None:
    assert SPEC_FILE.exists(), REGEN
    assert SPEC_FILE.read_text(encoding="utf-8") == render(spec), REGEN


def test_one_field_name_is_one_type_across_every_schema(spec: Spec) -> None:
    names, conflicts = split_types(spec)
    assert names >= 5, "the gate saw almost no fields"
    assert not conflicts, f"a field name with two types: {conflicts}"


def test_every_json_response_is_a_named_model_with_properties(spec: Spec) -> None:
    total, bad = unnamed(spec)
    assert total >= 3, "the gate saw almost no responses"
    assert not bad, f"anything-goes or missing response schemas: {bad}"


def test_every_operation_id_is_readable(spec: Spec) -> None:
    total, bad = unreadable_ids(spec)
    assert total >= 2 and not bad, bad


def test_no_two_operations_share_an_id(spec: Spec) -> None:
    assert not repeated_ids(spec), "two routes share a function name, so the generated client has one of them"


def planted() -> Spec:
    return {
        "paths": {
            "/a": {"get": {"operationId": "get_a", "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}}}}},
            "/b": {"get": {"operationId": "get_b_api_b_get", "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
            "/c": {"get": {"operationId": "getC", "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}}},
            "/d": {"get": {"operationId": "get_d", "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}}}}},
            "/e": {"get": {"operationId": "get_e", "responses": {"200": {"description": "no body"}}}},
        },
        "components": {"schemas": {
            "A": {"properties": {"at": {"type": "number"}, "ok": {"type": "boolean"}}},
            "B": {"properties": {"at": {"type": "string", "format": "date-time"}, "ok": {"anyOf": [{"type": "boolean"}, {"type": "null"}]}}},
        }},
    }


def test_the_gates_fail_on_a_planted_bad_spec() -> None:
    bad = planted()
    assert split_types(bad) == (2, {"at": {'["number", null]', '["string", "date-time"]'}}), "nullable is not a split, a changed type is"
    total, unnamed_where = unnamed(bad)
    assert total == 4 and unnamed_where == ["get /b 200", "get /c 200", "get /d 200"]
    assert unreadable_ids(bad)[1] == ["getC", "get_b_api_b_get"]
    bad["paths"]["/f"] = {"get": {"operationId": "get_a", "responses": {}}}
    assert repeated_ids(bad) == ["get_a"]


def test_the_gates_pass_a_clean_spec() -> None:
    clean = planted()
    del clean["paths"]["/b"], clean["paths"]["/c"], clean["paths"]["/d"]
    clean["components"]["schemas"]["B"]["properties"]["at"] = {"type": "number"}
    assert split_types(clean)[1] == {} and unnamed(clean) == (1, []) and unreadable_ids(clean)[1] == []
    assert repeated_ids(clean) == []
