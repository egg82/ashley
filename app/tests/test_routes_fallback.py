"""The `fallback` field of a task entry in `routes.parse`: a task that waits for its first route."""

import pytest
from ashley.inference import routes

TWO = [{"provider": "a", "model": "m1", "timeout_s": 1}, {"provider": "b", "model": "m2", "timeout_s": 1}]


def table(entry: object) -> dict[str, object]:
    text: dict[str, object] = {t: TWO for t in routes.TASKS}
    text["memory_write"] = entry
    return {"cooldown_s": 60, "tasks": text}


def test_a_task_marked_without_fallback_is_listed_whole_and_narrowed_by_without_fallback() -> None:
    loaded = routes.parse(table({"fallback": False, "routes": TWO}), {})
    assert loaded.waits_for_first == {"memory_write"}
    assert len(loaded.by_task["memory_write"]) == 2
    narrowed = routes.without_fallback(loaded)
    assert [r.provider for r in narrowed.by_task["memory_write"]] == ["a"]
    assert narrowed.by_task["chat"] == loaded.by_task["chat"]


def test_a_plain_list_keeps_every_route() -> None:
    loaded = routes.parse(table(TWO), {})
    assert loaded.waits_for_first == frozenset()
    assert routes.without_fallback(loaded) == loaded


def test_the_narrowing_control_can_fail() -> None:
    loaded = routes.parse(table({"fallback": False, "routes": TWO}), {})
    assert routes.without_fallback(loaded) != loaded, "a narrowing that changed nothing would pass the tests above"


@pytest.mark.parametrize("entry", [
    {"routes": TWO}, {"routes": TWO, "fallback": True}, {"routes": TWO, "fallback": "no"},
    {"routes": TWO, "fallback": False, "extra": 1}])
def test_only_exactly_routes_and_fallback_false_is_accepted(entry: object) -> None:
    with pytest.raises(ValueError, match="memory_write"):
        routes.parse(table(entry), {})


def test_a_speech_task_cannot_wait_for_its_first_route() -> None:
    text: dict[str, object] = {t: TWO for t in routes.TASKS}
    data = {"cooldown_s": 60, "tasks": {**text, "speak": {"routes": TWO, "fallback": False}}}
    with pytest.raises(ValueError, match="speak"):
        routes.parse(data, {})


def test_the_shipped_routes_make_memory_write_wait_for_its_first_route() -> None:
    shipped = routes.load({})
    assert shipped.waits_for_first == {"memory_write"}
    assert len(shipped.by_task["memory_write"]) > 1
