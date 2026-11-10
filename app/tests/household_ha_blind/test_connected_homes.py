"""`ConnectedHomes`: a household's Home Assistant is its connection; household 1 with no row seen gets the env's, and a
read retries the seed at most once per RETRY_S; a removed row stays removed; other households never get the env."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from ashley.home_assistant.connected_homes import RETRY_S, ConnectedHomes
from ashley.home_assistant.homes import Home, HomeAssistantFailed, Homes, HomesUnavailable
from hha_blind_support import A_TOKEN, A_URL, B_TOKEN, B_URL, CONFIG, ENV, Clock, FakeHouses, HeldConnections
from connection_legacy_support import remove_of


def run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(coro, 20))


def base_of(home: Home | None) -> str:
    assert home is not None
    return str(home.home_assistant.http.base_url).rstrip("/")


def build(houses: FakeHouses, connections: HeldConnections, env: tuple[str, str] | None = ENV,
          clock: Clock | None = None) -> ConnectedHomes:
    return ConnectedHomes(connections, CONFIG, houses.connect, env=env, clock=clock or Clock())


def test_it_is_a_homes() -> None:
    assert issubclass(ConnectedHomes, Homes)


def test_a_household_gets_its_own_connection() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(2, A_URL, A_TOKEN)
    held.connect(3, B_URL, B_TOKEN)

    async def go() -> None:
        homes = build(houses, held)
        a, b = await homes.of(2), await homes.of(3)
        assert a is not None and b is not None
        assert (a.household_id, base_of(a)) == (2, A_URL) and (b.household_id, base_of(b)) == (3, B_URL)
        assert (A_URL, A_TOKEN) in houses.made and (B_URL, B_TOKEN) in houses.made

    run(go())


def test_a_household_without_a_connection_has_no_home_and_never_the_env() -> None:
    houses, held = FakeHouses(), HeldConnections()

    async def go() -> None:
        homes = build(houses, held)
        assert await homes.of(2) is None and await homes.of(7) is None

    run(go())


def test_no_env_and_no_row_is_no_home_even_for_household_one() -> None:
    houses, held = FakeHouses(), HeldConnections()

    async def go() -> None:
        assert await build(houses, held, env=None).of(1) is None

    run(go())


def test_household_one_with_no_row_is_seeded_from_the_env_and_answers_with_it() -> None:
    houses, held = FakeHouses(), HeldConnections()

    async def go() -> None:
        home = await build(houses, held).of(1)
        assert base_of(home) == ENV[0] and home is not None and home.household_id == 1

    run(go())


def test_household_one_gets_the_env_even_when_connections_are_unreadable() -> None:
    houses, held = FakeHouses(), HeldConnections(down=True)

    async def go() -> None:
        home = await build(houses, held).of(1)
        assert base_of(home) == ENV[0]

    run(go())


def test_a_row_of_household_ones_beats_the_env() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(1, A_URL, A_TOKEN)

    async def go() -> None:
        assert base_of(await build(houses, held).of(1)) == A_URL

    run(go())


def test_a_persons_row_is_never_overwritten_by_the_retry() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(1, A_URL, A_TOKEN)
    clock = Clock()

    async def go() -> None:
        homes = build(houses, held, clock=clock)
        for _ in range(3):
            clock.now += RETRY_S * 2
            await homes.of(1)
        assert held.held[(1, "home_assistant")].secret == A_TOKEN

    run(go())


def test_once_a_row_was_seen_removing_it_is_respected() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(1, A_URL, A_TOKEN)
    clock = Clock()

    async def go() -> None:
        homes = build(houses, held, clock=clock)
        assert base_of(await homes.of(1)) == A_URL
        await remove_of(held, 1, "home_assistant")
        for _ in range(3):
            clock.now += RETRY_S * 5
            assert await homes.of(1) is None
        assert (1, "home_assistant") not in held.held

    run(go())


def test_the_seeding_read_creates_household_ones_row_and_a_later_removal_stays() -> None:
    houses, held = FakeHouses(), HeldConnections()
    clock = Clock()

    async def go() -> None:
        homes = build(houses, held, clock=clock)
        await homes.of(1)
        assert (1, "home_assistant") in held.held and held.held[(1, "home_assistant")].secret == ENV[1]
        await remove_of(held, 1, "home_assistant")
        clock.now += RETRY_S * 3
        assert await homes.of(1) is None

    run(go())


def test_a_failed_seed_is_retried_at_most_once_per_window_and_heals() -> None:
    houses, held = FakeHouses(), HeldConnections(seed_fails=True)
    clock = Clock()

    async def go() -> None:
        homes = build(houses, held, clock=clock)
        for _ in range(10):
            assert base_of(await homes.of(1)) == ENV[0]
        first = len(held.seeds)
        assert first == 1
        clock.now += RETRY_S / 2
        for _ in range(10):
            await homes.of(1)
        assert len(held.seeds) == first
        clock.now += RETRY_S
        for _ in range(10):
            await homes.of(1)
        assert first < len(held.seeds) <= first + 1
        held.seed_fails = False
        clock.now += RETRY_S * 2
        await homes.of(1)
        assert (1, "home_assistant") in held.held
        # healed: the row is household 1's, and it is now the source
        held.connect(1, A_URL, A_TOKEN)
        assert base_of(await homes.of(1)) == A_URL

    run(go())


def test_other_households_never_get_the_env_while_connections_are_down() -> None:
    houses, held = FakeHouses(), HeldConnections(down=True)

    async def go() -> None:
        homes = build(houses, held)
        try:
            got = await homes.of(2)
        except HomesUnavailable:
            got = None
        assert got is None

    run(go())


def test_without_the_key_household_one_has_the_env_and_nobody_else_has_anything() -> None:
    class NoKey(HeldConnections):
        def can_open(self) -> bool:
            return False

    houses, held = FakeHouses(), NoKey()

    async def go() -> None:
        homes = build(houses, held)
        assert base_of(await homes.of(1)) == ENV[0]
        assert await homes.of(2) is None

    run(go())


def test_unreadable_connections_are_unavailable_for_a_household_never_seen() -> None:
    houses, held = FakeHouses(), HeldConnections(down=True)

    async def go() -> None:
        with pytest.raises(HomesUnavailable):
            await build(houses, held).of(2)

    run(go())


def test_while_connections_are_unreadable_the_last_home_seen_goes_on_answering() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(2, A_URL, A_TOKEN)

    async def go() -> None:
        homes = build(houses, held)
        assert base_of(await homes.of(2)) == A_URL
        held.down = True
        assert base_of(await homes.of(2)) == A_URL

    run(go())


def test_a_replacement_is_seen_on_the_next_call_and_an_unchanged_one_keeps_its_home() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(2, A_URL, A_TOKEN)

    async def go() -> None:
        homes = build(houses, held)
        first = await homes.of(2)
        assert first is await homes.of(2)
        assert len([m for m in houses.made if m[0] == A_URL]) == 1
        held.connect(2, B_URL, B_TOKEN)
        assert base_of(await homes.of(2)) == B_URL
        held.connect(2, B_URL, "rotated")
        again = await homes.of(2)
        assert again is not None and again.home_assistant.http.headers["authorization"] == "Bearer rotated"

    run(go())


def test_a_removal_is_seen_on_the_next_call() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(2, A_URL, A_TOKEN)

    async def go() -> None:
        homes = build(houses, held)
        assert await homes.of(2) is not None
        await remove_of(held, 2, "home_assistant")
        assert await homes.of(2) is None

    run(go())


def test_a_sure_connection_is_not_a_house() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(2, "https://money.test", "key", kind="sure")

    async def go() -> None:
        assert await build(houses, held).of(2) is None

    run(go())


def test_check_asks_the_greeting_with_the_token_and_stores_nothing() -> None:
    houses, held = FakeHouses(), HeldConnections()

    async def go() -> None:
        await build(houses, held).check(A_URL, A_TOKEN)
        assert houses.seen and {(m, p, b) for _, m, p, b in houses.seen} == {("GET", "/api/", f"Bearer {A_TOKEN}")}
        assert held.held == {}

    run(go())


@pytest.mark.parametrize("mode", ["refused", "unreachable", "not_home_assistant", "html"])
def test_check_says_why_it_failed(mode: str) -> None:
    houses, held = FakeHouses(), HeldConnections()
    if mode == "refused":
        houses.refuse.add("a-house.test")
    elif mode == "unreachable":
        houses.down.add("a-house.test")
    elif mode == "not_home_assistant":
        houses.greeting = {"hello": "somebody else"}
    else:
        houses.greeting = {}

    async def go() -> None:
        with pytest.raises(HomeAssistantFailed) as failed:
            await build(houses, held).check(A_URL, A_TOKEN)
        assert failed.value.reason == {"html": "not_home_assistant"}.get(mode, mode)
        assert A_TOKEN not in str(failed.value) and A_TOKEN not in repr(failed.value)

    run(go())
