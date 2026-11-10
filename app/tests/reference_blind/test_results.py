"""`ashley.tools.results`: numbers run from 1 and on, each number keeps its URL, an unknown number has none, stores do
not share, and `bound`/`current` scope the one a call sees."""

import asyncio
from contextvars import copy_context

import pytest
from ashley.tools.results import Results, bound, current


def test_numbers_run_from_one_and_each_keeps_its_url() -> None:
    r = Results()
    assert r.next_number() == 1
    got = [r.record(f"https://example.org/{i}") for i in range(4)]
    assert got == [1, 2, 3, 4]
    assert [r.url(i) for i in range(1, 5)] == [f"https://example.org/{i}" for i in range(4)]
    assert r.next_number() == 5


def test_next_number_is_the_number_the_next_record_gets() -> None:
    r = Results()
    r.record("https://example.org/a")
    expected = r.next_number()
    assert r.record("https://example.org/b") == expected


@pytest.mark.parametrize("number", [0, -1, 3, 99])
def test_a_number_nobody_has_has_no_url(number: int) -> None:
    r = Results()
    r.record("https://example.org/a")
    r.record("https://example.org/b")
    assert r.url(number) is None


def test_a_recorded_url_comes_back_unchanged() -> None:
    r = Results()
    url = "https://Example.org/A b?x=1&y=%20#f"
    assert r.url(r.record(url)) == url


def test_stores_do_not_share_numbers() -> None:
    a, b = Results(), Results()
    a.record("https://example.org/a")
    assert b.next_number() == 1 and b.url(1) is None


def test_bound_makes_current_the_store_inside_and_restores_it_after() -> None:
    outer, inner = Results(), Results()
    with bound(outer):
        assert current() is outer
        with bound(inner):
            assert current() is inner
        assert current() is outer
    assert current() is not outer and current() is not inner


def test_a_call_outside_any_turn_sees_a_store_nothing_else_reads() -> None:
    n = current().record("https://example.org/a")
    assert n == 1
    assert current().url(1) is None or current().url(1) == "https://example.org/a"
    with bound(Results()):
        assert current().next_number() == 1


def test_bound_restores_on_an_exception() -> None:
    mine = Results()
    with pytest.raises(RuntimeError):
        with bound(mine):
            raise RuntimeError("x")
    assert current() is not mine


def test_a_task_started_inside_bound_sees_the_store_and_concurrent_turns_keep_their_own() -> None:
    async def turn(name: str, gate: asyncio.Event, out: dict[str, int]) -> None:
        store = Results()
        with bound(store):
            await gate.wait()
            out[name] = current().record(f"https://example.org/{name}")
            assert current() is store
            assert store.url(out[name]) == f"https://example.org/{name}"

    async def go() -> dict[str, int]:
        gate, out = asyncio.Event(), dict[str, int]()
        tasks = [asyncio.create_task(turn(n, gate, out)) for n in "abc"]
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(*tasks)
        return out

    assert copy_context().run(asyncio.run, go()) == {"a": 1, "b": 1, "c": 1}
