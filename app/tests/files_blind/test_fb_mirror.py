"""`MirroredStore` over several stores: a write goes to every one and counts once a copy lands, a read takes the nearest
that has it, and `repair` copies what one lacks from another until they hold the same; `repair.run_once` and `run` drive it."""

import asyncio
import logging

import pytest
from ashley.files import repair
from ashley.files.mirror import MirroredStore
from ashley.files.store import ObjectStore, StoreUnavailable
from files_blind_support import go as run, FakeStore
from hypothesis import given, settings
from hypothesis import strategies as st


def pair(**kw: bool) -> tuple[FakeStore, FakeStore, MirroredStore]:
    a, b = FakeStore("a", down=kw.get("a_down", False)), FakeStore("b", down=kw.get("b_down", False))
    return a, b, MirroredStore([a, b])


def test_a_write_goes_to_every_store_and_counts_each_copy() -> None:
    a, b, m = pair()
    assert run(m.put("k", b"v")) == 2
    assert a.held == b.held == {"k": b"v"}


def test_a_write_is_replaced_by_a_later_one() -> None:
    a, b, m = pair()
    run(m.put("k", b"one"))
    run(m.put("k", b"two"))
    assert a.held["k"] == b.held["k"] == b"two" and run(m.get("k")) == b"two"


@pytest.mark.parametrize("which", ["a_down", "b_down"])
def test_one_copy_counts_when_the_other_store_is_down_and_it_is_still_attempted_in_full(which: str, caplog: pytest.LogCaptureFixture) -> None:
    a, b, m = pair(**{which: True})
    with caplog.at_level(logging.DEBUG):
        assert run(m.put("k", b"v")) == 1
    up = b if which == "a_down" else a
    assert up.held == {"k": b"v"}
    assert "files.copy_failed" in caplog.text


def test_a_write_no_store_took_raises_unavailable() -> None:
    a, b, m = pair(a_down=True, b_down=True)
    with pytest.raises(StoreUnavailable):
        run(m.put("k", b"v"))
    assert a.held == b.held == {}


def test_a_write_that_fails_in_the_first_store_still_reaches_the_second_and_one_that_fails_in_the_second_reaches_the_first() -> None:
    a, b = FakeStore("a", fail=frozenset({"put"})), FakeStore("b")
    assert run(MirroredStore([a, b]).put("k", b"v")) == 1 and b.held == {"k": b"v"}
    a, b = FakeStore("a"), FakeStore("b", fail=frozenset({"put"}))
    assert run(MirroredStore([a, b]).put("k", b"v")) == 1 and a.held == {"k": b"v"}


def test_a_read_takes_the_nearest_store_that_has_it_and_asks_no_further() -> None:
    a, b, m = pair()
    a.held["k"], b.held["k"] = b"near", b"far"
    assert run(m.get("k")) == b"near"
    assert b.calls.of("get") == []


def test_a_read_falls_back_to_the_next_store_when_the_first_lacks_the_key_or_is_down() -> None:
    a, b, m = pair()
    b.held["k"] = b"far"
    assert run(m.get("k")) == b"far"
    a.down = True
    assert run(m.get("k")) == b"far"


def test_a_read_nothing_holds_is_none_and_a_read_no_store_answered_is_unavailable() -> None:
    a, b, m = pair()
    assert run(m.get("nope")) is None
    a.down = b.down = True
    with pytest.raises(StoreUnavailable):
        run(m.get("nope"))


def test_a_read_missing_in_the_one_store_that_answers_is_none_not_an_error() -> None:
    _, _, m = pair(a_down=True)
    assert run(m.get("nope")) is None


def test_the_order_of_the_stores_is_the_order_of_the_reads() -> None:
    a, b = FakeStore("a"), FakeStore("b")
    a.held["k"], b.held["k"] = b"A", b"B"
    assert run(MirroredStore([b, a]).get("k")) == b"B"


def test_keys_are_the_union_under_the_prefix_of_the_stores_that_answered() -> None:
    a, b, m = pair()
    a.held.update({"bench/1/x": b"", "other/y": b""})
    b.held.update({"bench/1/z": b"", "bench/2/w": b""})
    assert run(m.keys("bench/1/")) == frozenset({"bench/1/x", "bench/1/z"})
    b.down = True
    assert run(m.keys("bench/")) == frozenset({"bench/1/x"})
    a.down = True
    with pytest.raises(StoreUnavailable):
        run(m.keys("bench/"))


def test_repair_copies_what_each_lacks_from_the_other_and_counts_the_copies() -> None:
    a, b, m = pair()
    a.held["bench/1/x"], b.held["bench/1/y"] = b"X", b"Y"
    assert run(m.repair("bench/")) == 2
    assert a.held == b.held == {"bench/1/x": b"X", "bench/1/y": b"Y"}


def test_repair_twice_writes_nothing_the_second_time() -> None:
    a, _, m = pair()
    a.held["bench/1/x"] = b"X"
    assert run(m.repair("bench/")) == 1
    assert run(m.repair("bench/")) == 0


def test_repair_leaves_keys_outside_its_prefix_alone() -> None:
    a, b, m = pair()
    a.held.update({"bench/1/x": b"X", "elsewhere/q": b"Q"})
    run(m.repair("bench/"))
    assert "elsewhere/q" not in b.held and b.held["bench/1/x"] == b"X"


def test_repair_of_identical_stores_does_nothing() -> None:
    a, b, m = pair()
    a.held["bench/1/x"] = b.held["bench/1/x"] = b"X"
    assert run(m.repair("bench/")) == 0 and a.calls.of("put") == [] and b.calls.of("put") == []


def test_repair_copies_into_a_store_that_was_down_when_the_file_was_written() -> None:
    _, b, m = pair(b_down=True)
    run(m.put("bench/1/x", b"X"))
    b.down = False
    assert b.held == {}
    assert run(m.repair("bench/")) == 1 and b.held == {"bench/1/x": b"X"}


def test_repair_with_a_store_that_cannot_be_listed_raises_and_copies_nothing() -> None:
    a, b, m = pair(b_down=True)
    a.held["bench/1/x"] = b"X"
    with pytest.raises(StoreUnavailable):
        run(m.repair("bench/"))
    assert b.held == {} and a.calls.of("put") == []


def test_repair_across_three_stores_converges_on_the_union() -> None:
    stores = [FakeStore(n) for n in "abc"]
    m = MirroredStore(list[ObjectStore](stores))
    stores[0].held["bench/1/a"] = b"A"
    stores[1].held["bench/1/b"] = b"B"
    stores[2].held["bench/1/c"] = b"C"
    assert run(m.repair("bench/")) == 6
    assert all(s.held == {"bench/1/a": b"A", "bench/1/b": b"B", "bench/1/c": b"C"} for s in stores)


@settings(max_examples=25)
@given(down=st.lists(st.booleans(), min_size=3, max_size=3), data=st.binary(min_size=1, max_size=8))
def test_property_a_write_counts_the_stores_that_took_it_and_every_one_gets_it_back_by_repair(down: list[bool], data: bytes) -> None:
    stores = [FakeStore(n, down=d) for n, d in zip("abc", down)]
    m = MirroredStore(list[ObjectStore](stores))
    if all(down):
        with pytest.raises(StoreUnavailable):
            run(m.put("bench/1/k", data))
        return
    assert run(m.put("bench/1/k", data)) == down.count(False)
    for s in stores:
        s.down = False
    run(m.repair("bench/"))
    assert [s.held for s in stores] == [{"bench/1/k": data}] * 3
    assert run(m.get("bench/1/k")) == data


@settings(max_examples=25)
@given(held=st.lists(st.sets(st.sampled_from(["bench/1/a", "bench/1/b", "bench/2/c", "x/d"]), max_size=4), min_size=2, max_size=3))
def test_property_repair_converges_on_the_union_under_the_prefix_and_is_idempotent(held: list[set[str]]) -> None:
    stores = [FakeStore(str(i)) for i in range(len(held))]
    for s, keys in zip(stores, held):
        s.held = {k: k.encode() for k in keys}
    m = MirroredStore(list[ObjectStore](stores))
    union = {k for keys in held for k in keys if k.startswith("bench/")}
    run(m.repair("bench/"))
    for s, keys in zip(stores, held):
        assert {k for k in s.held if k.startswith("bench/")} == union
        assert {k for k in s.held if not k.startswith("bench/")} == {k for k in keys if not k.startswith("bench/")}
    assert run(m.repair("bench/")) == 0


def test_run_once_repairs_and_returns_the_copies_written() -> None:
    a, b, m = pair()
    a.held["bench/1/x"] = b"X"
    assert run(repair.run_once(m, ("bench/",))) == 1 and b.held == {"bench/1/x": b"X"}


def test_run_once_does_not_raise_when_a_store_cannot_be_listed_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    a, b, m = pair(b_down=True)
    a.held["bench/1/x"] = b"X"
    with caplog.at_level(logging.DEBUG):
        assert run(repair.run_once(m, ("bench/",))) == 0
    assert "files.repair_failed" in caplog.text and b.held == {}


def test_run_compares_then_waits_the_interval_and_repeats_until_cancelled() -> None:
    a, b, m = pair()
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)
        if len(waits) == 1:
            a.held["bench/1/late"] = b"L"
        if len(waits) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run(repair.run(m, ("bench/",), 12.5, sleep))
    assert waits == [12.5, 12.5, 12.5] and b.held == {"bench/1/late": b"L"}
