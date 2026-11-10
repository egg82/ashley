"""`routes.parse`: the documented shape, every documented rejection, the unwired provider that is kept, and
`check_params` called on the present ones; `routes.load()` returns a valid table for every task."""

import copy
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from anthropic import AsyncAnthropic
from ashley.inference import routes as routes_module
from ashley.inference.routes import TASKS
from ashley.inference.model import DEFAULT_VARIANT, Route
from ashley.inference.provider import Provider
from ashley.inference.providers import AnthropicProvider, OpenAICompatibleProvider
from ashley.inference.routes import Routes, load, parse
from inference_support import FakeProvider
from openai import AsyncOpenAI

Data = dict[str, Any]


def good() -> Data:
    return {"cooldown_s": 60, "tasks": {k: [{"provider": "alpha", "model": "m1", "timeout_s": 10}] for k in TASKS}}


def wired(*names: str) -> dict[str, Provider]:
    return {n: FakeProvider(n) for n in names}


def first(data: Data, task: str = "chat") -> Data:
    route: Data = data["tasks"][task][0]
    return route


def test_a_minimal_table_parses_with_defaults_for_variant_and_params() -> None:
    parsed = parse(good(), wired("alpha"))
    assert parsed.cooldown_s == 60
    assert set(parsed.by_task) == set(TASKS)
    for task in TASKS:
        assert parsed.by_task[task] == (Route("alpha", "m1", 10, DEFAULT_VARIANT, {}),)


def test_every_field_is_carried_and_routes_keep_their_order() -> None:
    data = good()
    data["cooldown_s"] = 12.5
    data["tasks"]["chat"] = [
        {"provider": "alpha", "model": "m2", "timeout_s": 0.5, "variant": "tuned", "params": {"max_tokens": 9}},
        {"provider": "beta", "model": "m1", "timeout_s": 30},
        {"provider": "alpha", "model": "m1", "timeout_s": 7.25, "params": {}},
    ]
    parsed = parse(data, wired("alpha", "beta"))
    assert parsed.cooldown_s == 12.5
    assert parsed.by_task["chat"] == (
        Route("alpha", "m2", 0.5, "tuned", {"max_tokens": 9}),
        Route("beta", "m1", 30, DEFAULT_VARIANT, {}),
        Route("alpha", "m1", 7.25, DEFAULT_VARIANT, {}),
    )
    assert isinstance(parsed.by_task["chat"], tuple)


def set_cooldown(value: object) -> Callable[[Data], None]:
    return lambda d: d.__setitem__("cooldown_s", value)


def set_route(key: str, value: object) -> Callable[[Data], None]:
    return lambda d: first(d).__setitem__(key, value)


def drop_route_key(key: str) -> Callable[[Data], None]:
    return lambda d: first(d).pop(key)


BAD_NUMBERS: list[object] = [0, -1, -0.5, True, False, "5", None, math.nan, math.inf, -math.inf, [1], {"n": 1}]
BAD_STRINGS: list[object] = ["", 5, None, True, ["alpha"], {"a": 1}]
MUTATIONS: dict[str, Callable[[Data], None]] = {
    "cooldown missing": lambda d: d.pop("cooldown_s"),
    "tasks missing": lambda d: d.pop("tasks"),
    "extra top-level key": lambda d: d.__setitem__("extra", 1),
    "tasks not an object": lambda d: d.__setitem__("tasks", [d["tasks"]]),
    "a task missing": lambda d: d["tasks"].pop("brainstorm"),
    "an unknown task": lambda d: d["tasks"].__setitem__("shout", [first(d)]),
    "a task with no routes": lambda d: d["tasks"].__setitem__("chat", []),
    "a task's routes not a list": lambda d: d["tasks"].__setitem__("chat", first(d)),
    "a route not an object": lambda d: d["tasks"].__setitem__("chat", ["alpha"]),
    "route without provider": drop_route_key("provider"),
    "route without model": drop_route_key("model"),
    "route without timeout": drop_route_key("timeout_s"),
    "route with an extra key": set_route("retries", 3),
    "params not an object": set_route("params", ["max_tokens"]),
    **{f"cooldown {v!r}": set_cooldown(v) for v in BAD_NUMBERS},
    **{f"timeout {v!r}": set_route("timeout_s", v) for v in BAD_NUMBERS},
    **{f"provider {v!r}": set_route("provider", v) for v in BAD_STRINGS},
    **{f"model {v!r}": set_route("model", v) for v in BAD_STRINGS},
    **{f"variant {v!r}": set_route("variant", v) for v in BAD_STRINGS},
}


@pytest.mark.parametrize("mutate", MUTATIONS.values(), ids=MUTATIONS.keys())
def test_every_documented_rejection_raises_value_error(mutate: Callable[[Data], None]) -> None:
    data = good()
    mutate(data)
    with pytest.raises(ValueError):
        parse(data, wired("alpha"))


@pytest.mark.parametrize("data", [None, [], "routes", 5, True, [good()]])
def test_a_table_that_is_not_an_object_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        parse(data, wired("alpha"))


def test_the_rejections_have_a_valid_twin() -> None:
    """Controls: numbers and strings of the accepted tasks go through, so each refusal above is its one change."""
    data = good()
    data["cooldown_s"] = 0.001
    first(data).update(timeout_s=1e-3, variant="v", params={})
    parse(data, wired("alpha"))
    first(data).update(timeout_s=10**6)
    parse(copy.deepcopy(data), wired("alpha"))


def test_the_error_names_the_kind_and_the_route_index() -> None:
    data = good()
    routes = [{"provider": "alpha", "model": "m1", "timeout_s": 10} for _ in range(3)]
    routes[2]["timeout_s"] = -1
    data["tasks"]["brainstorm"] = routes
    with pytest.raises(ValueError) as caught:
        parse(data, wired("alpha"))
    assert "brainstorm" in str(caught.value)
    assert "2" in str(caught.value)


def test_a_kind_with_no_routes_is_named() -> None:
    data = good()
    data["tasks"]["command"] = []
    with pytest.raises(ValueError, match="command"):
        parse(data, wired("alpha"))


def test_a_route_naming_an_unwired_provider_is_kept_and_its_params_are_not_checked() -> None:
    data = good()
    data["tasks"]["chat"] = [
        {"provider": "ghost", "model": "x", "timeout_s": 5, "params": {"bad": 1, "anything": "goes"}},
        {"provider": "alpha", "model": "m1", "timeout_s": 10},
    ]
    parsed = parse(data, wired("alpha"))
    assert [r.provider for r in parsed.by_task["chat"]] == ["ghost", "alpha"]
    assert parsed.by_task["chat"][0].params == {"bad": 1, "anything": "goes"}


def test_a_table_where_nothing_is_wired_still_parses() -> None:
    parsed = parse(good(), {})
    assert all(parsed.by_task[k][0].provider == "alpha" for k in TASKS)


def test_params_of_a_present_provider_are_checked_by_that_provider_once_per_route() -> None:
    data = good()
    data["tasks"]["chat"] = [
        {"provider": "alpha", "model": "m1", "timeout_s": 10, "params": {"max_tokens": 5}},
        {"provider": "beta", "model": "m1", "timeout_s": 10, "params": {"effort": "low"}},
        {"provider": "alpha", "model": "m2", "timeout_s": 10, "params": {"max_tokens": 7}},
        {"provider": "ghost", "model": "m1", "timeout_s": 10, "params": {"zzz": 1}},
    ]
    providers = {"alpha": FakeProvider("alpha"), "beta": FakeProvider("beta")}
    parse(data, providers)
    assert [dict(p) for p in providers["alpha"].checked if p] == [{"max_tokens": 5}, {"max_tokens": 7}]
    assert [dict(p) for p in providers["beta"].checked if p] == [{"effort": "low"}]


def test_a_provider_that_rejects_the_params_fails_the_parse_naming_the_route() -> None:
    data = good()
    data["tasks"]["brainstorm"] = [
        {"provider": "alpha", "model": "m1", "timeout_s": 10},
        {"provider": "alpha", "model": "m1", "timeout_s": 10},
        {"provider": "alpha", "model": "m1", "timeout_s": 10, "params": {"bad_key": 1}},
    ]
    with pytest.raises(ValueError) as caught:
        parse(data, wired("alpha"))
    assert "brainstorm" in str(caught.value)
    assert "2" in str(caught.value)


def test_the_cooldown_is_a_float_or_int_that_is_kept_as_given() -> None:
    for value in (1, 0.25, 3600):
        data = good()
        data["cooldown_s"] = value
        assert parse(data, wired("alpha")).cooldown_s == value


# --- the shipped table -------------------------------------------------------------------------------------------


def shipped() -> Any:
    return json.loads(Path(routes_module.__file__).with_name("routes.json").read_text(encoding="utf-8"))


def real_providers() -> dict[str, Provider]:
    """The names the decision gives (`anthropic`, `openai`, `gemini`, `local`) wired to the real classes, so the
    shipped params meet a real `check_params`."""
    made: dict[str, Provider] = {"anthropic": AnthropicProvider("anthropic", AsyncAnthropic(api_key="k"))}
    for name in ("openai", "gemini", "local"):
        made[name] = OpenAICompatibleProvider(name, AsyncOpenAI(api_key="k", base_url="http://127.0.0.1:9/v1"))
    return made


def test_load_returns_a_valid_table_for_every_kind_with_nothing_wired() -> None:
    table = load({})
    assert set(table.by_task) == set(TASKS)
    assert table.cooldown_s > 0 and math.isfinite(table.cooldown_s)
    for task in TASKS:
        assert table.by_task[task], f"{task} has no route"
        for r in table.by_task[task]:
            assert r.provider and r.model and r.variant
            assert r.timeout_s > 0 and math.isfinite(r.timeout_s)


def test_load_is_the_shipped_file_parsed() -> None:
    assert load({}) == parse(shipped(), {})


def test_load_checks_the_shipped_params_against_real_providers() -> None:
    providers = real_providers()
    table: Routes = load(providers)
    assert table == parse(shipped(), providers)
    assert table == load({})


def test_load_checks_params_when_a_provider_is_present() -> None:
    """Control: `load` really passes `providers` through (a provider rejecting everything makes it raise)."""
    class Strict(FakeProvider):
        def check_params(self, params: Any) -> None:
            raise ValueError("no params accepted")

    names = {r.provider for rs in load({}).by_task.values() for r in rs}
    with pytest.raises(ValueError):
        load({name: Strict(name) for name in names})
