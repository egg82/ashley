"""The provider-schema gate's public data: which keywords each provider refuses, and the reply schemas it is sent."""

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.model import Task
from ashley.inference.reply import Reply

REJECTS = Path(__file__).parents[1] / "provider_schema_rejects.json"
ROUTES = Path(__file__).parents[2] / "ashley" / "inference" / "routes.json"


def rejects() -> dict[str, list[dict[str, str]]]:
    return json.loads(REJECTS.read_text())


def chat_providers() -> set[str]:
    tasks = json.loads(ROUTES.read_text())["tasks"]
    return {r["provider"] for t in get_args(Task) for r in tasks[t] if isinstance(tasks[t], list)}


OBJECT = TypeAdapter(dict[str, object])
ARRAY = TypeAdapter(list[object])


def keywords_in(schema: object) -> set[str]:
    """Every key of a JSON Schema that is a keyword, not a property name."""
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in OBJECT.validate_python(schema).items():
            if key in ("properties", "$defs", "definitions", "patternProperties") and isinstance(value, dict):
                for sub in OBJECT.validate_python(value).values():
                    found |= keywords_in(sub)
            else:
                found.add(key)
                found |= keywords_in(value)
    elif isinstance(schema, list):
        for item in ARRAY.validate_python(schema):
            found |= keywords_in(item)
    return found


def test_every_provider_a_text_task_routes_to_has_an_entry_in_the_list() -> None:
    assert chat_providers() <= set(rejects())


def test_gemini_refuses_nested_maxitems() -> None:
    assert "maxItems" in {e["keyword"] for e in rejects()["gemini"]}


def test_every_refused_keyword_is_named_with_a_shape_and_a_source() -> None:
    entries = [e for listed in rejects().values() for e in listed]
    assert entries
    for entry in entries:
        assert entry["keyword"].strip()
        assert entry["shape"].strip()
        assert entry["source"].strip()


def test_a_recorded_400_names_when_and_what_it_answered() -> None:
    [entry] = [e for e in rejects()["gemini"] if e["keyword"] == "maxItems"]
    assert "400" in entry["source"]


WIRE_OF = {"gemini": openai_wire, "openai": openai_wire, "anthropic": anthropic_wire}


def test_the_reply_schema_of_each_wire_is_an_object_schema() -> None:
    assert openai_wire.reply_schema(Reply)["type"] == "object"
    assert anthropic_wire.reply_schema(Reply)["type"] == "object"


@pytest.mark.parametrize("provider", sorted(WIRE_OF))
def test_the_reply_schema_a_provider_is_sent_has_none_of_the_keywords_it_refuses(provider: str) -> None:
    schema = WIRE_OF[provider].reply_schema(Reply)
    assert keywords_in(schema)
    assert keywords_in(schema).isdisjoint({e["keyword"] for e in rejects().get(provider, [])})
