"""Screens are re-told "thinking" once half of `thinking_at_most_s` has passed (`Showing.still_working`), so a turn
longer than a screen believes thinking is not shown idle while it works."""

import time
from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels.live_turn import Showing
from ashley.channels.model import on_bench
from ashley.live.events import HerState
from ashley.live.live import Live, load
from bench_run_support import Heard

AT_MOST = load().thinking_at_most_s


class Clock:
    now = 1000.0


@pytest.fixture
def heard() -> Generator[Heard]:
    made = Heard()
    services.register(Live, made)
    yield made
    services.unregister(Live)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    for name in ("monotonic", "perf_counter", "time"):
        monkeypatch.setattr(time, name, lambda: fake.now)
    return fake


def states(heard: Heard) -> list[str]:
    return [e.state for e in heard.events if isinstance(e, HerState)]


def test_a_turn_is_told_thinking_again_only_once_half_of_what_a_screen_believes_it_for_has_passed(
        heard: Heard, clock: Clock) -> None:
    showing = Showing(on_bench(1, 2, 3, "hello"))
    showing.state("thinking")
    assert states(heard) == ["thinking"]
    clock.now += AT_MOST * 0.45
    showing.still_working()
    assert states(heard) == ["thinking"], "not yet half"
    clock.now += AT_MOST * 0.1
    showing.still_working()
    assert states(heard) == ["thinking", "thinking"], "past half"
    told = [e for e in heard.events if isinstance(e, HerState)]
    assert told[0].turn == told[1].turn and told[1].at_most_s == AT_MOST, "the same turn, told afresh"


def test_the_retelling_counts_from_the_last_telling(heard: Heard, clock: Clock) -> None:
    showing = Showing(on_bench(1, 2, 3, "hello"))
    showing.state("thinking")
    clock.now += AT_MOST * 0.6
    showing.still_working()
    assert len(states(heard)) == 2
    clock.now += AT_MOST * 0.3
    showing.still_working()
    assert len(states(heard)) == 2, "told 0.3 of the span ago"
    clock.now += AT_MOST * 0.3
    showing.still_working()
    assert len(states(heard)) == 3


def test_a_turn_that_is_short_is_never_retold(heard: Heard, clock: Clock) -> None:
    showing = Showing(on_bench(1, 2, 3, "hello"))
    showing.state("thinking")
    for _ in range(20):
        clock.now += AT_MOST * 0.02
        showing.still_working()
    assert states(heard) == ["thinking"]
