"""`ConnectedHomes`: a household's Home Assistant is its connection, every household's alike; a household with none has
no home, and a removed row is gone on the next call."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Home, HomeAssistantFailed, Homes, HomesUnavailable
from hha_blind_support import A_TOKEN, A_URL, B_TOKEN, B_URL, FakeHouses, HeldConnections
from connection_legacy_support import remove_of


def run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(coro, 20))


def base_of(home: Home | None) -> str:
    assert home is not None
    return str(home.home_assistant.http.base_url).rstrip("/")


def build(houses: FakeHouses, connections: HeldConnections) -> ConnectedHomes:
    return ConnectedHomes(connections, houses.connect)


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


def test_a_household_without_a_connection_has_no_home_household_one_included() -> None:
    houses, held = FakeHouses(), HeldConnections()

    async def go() -> None:
        homes = build(houses, held)
        assert await homes.of(1) is None and await homes.of(2) is None

    run(go())


def test_a_removed_row_of_household_one_is_not_brought_back() -> None:
    houses, held = FakeHouses(), HeldConnections()
    held.connect(1, A_URL, A_TOKEN)

    async def go() -> None:
        homes = build(houses, held)
        assert base_of(await homes.of(1)) == A_URL
        await remove_of(held, 1, "home_assistant")
        for _ in range(3):
            assert await homes.of(1) is None
        assert (1, "home_assistant") not in held.held and held.seeds == []

    run(go())


def test_without_the_key_nobody_has_a_home() -> None:
    class NoKey(HeldConnections):
        def can_open(self) -> bool:
            return False

    houses, held = FakeHouses(), NoKey()

    async def go() -> None:
        homes = build(houses, held)
        assert await homes.of(1) is None and await homes.of(2) is None

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
