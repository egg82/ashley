"""Each household's Home Assistant (`home_assistant.homes`, `home_assistant.connected_homes.ConnectedHomes`): a household
reaches the HA its own connection names, with its own token, and none without one; the same Home while the connection
is unchanged, a new one (the old client closed) once it is replaced, none once it is removed; connections unreadable
keep the last Home seen, and with none seen are HomesUnavailable; with no key to open connections, the env's HA
answers for its one household alone. A new address and token are checked with one `GET /api/`. The env's HA is
seeded as household 1's connection once (`home_assistant.seed.seed_from_env`), never over a row, and the token and
address reach no log line."""

import asyncio

import pytest
from ashley import logs
from ashley.connections.connections import NullConnections
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import HomeAssistantFailed, HomesUnavailable, NullHomes
from ashley.home_assistant.seed import seed_from_env
from homes_support import TOKEN, StandIn
from money_support import HeldConnections
from connection_legacy_support import opened_of, remove_of

ONE, TWO = 1, 2
WILLOW, BIRCH = "http://ha.willow.test:8123", "https://ha.birch.test"


def homes(connections: HeldConnections | NullConnections, stand: StandIn, fallback: str | None = None,
          ) -> ConnectedHomes:
    return ConnectedHomes(connections, stand.connect, env=(fallback, TOKEN) if fallback else None)


def held(**by_household: tuple[str, str]) -> HeldConnections:
    connections = HeldConnections()
    for household, (base, token) in by_household.items():
        connections.connect(int(household.removeprefix("h")), base, token, "home_assistant")
    return connections


def test_each_household_reaches_its_own_home_assistant_with_its_own_token() -> None:
    stand = StandIn()
    found = homes(held(h1=(WILLOW, TOKEN), h2=(BIRCH, "birch-token")), stand)

    async def scenario() -> None:
        one, two = await found.of(ONE), await found.of(TWO)
        assert one is not None and two is not None and one.household_id == ONE and two.household_id == TWO
        await one.home_assistant.http.get("/api/states/person.alana")
        await two.home_assistant.http.get("/api/states/person.kim")
        assert await found.of(3) is None

    asyncio.run(scenario())
    assert stand.seen == [(WILLOW, "/api/states/person.alana", TOKEN), (BIRCH, "/api/states/person.kim", "birch-token")]


def test_the_same_home_while_unchanged_and_a_new_one_once_replaced_or_none_once_removed() -> None:
    stand = StandIn()
    connections = held(h1=(WILLOW, TOKEN))
    found = homes(connections, stand)

    async def scenario() -> None:
        first = await found.of(ONE)
        assert first is not None and await found.of(ONE) is first
        connections.connect(ONE, WILLOW, "a-new-token", "home_assistant")
        second = await found.of(ONE)
        assert second is not None and second is not first and first.home_assistant.http.is_closed
        await second.home_assistant.http.get("/api/")
        connections.connect(ONE, BIRCH, "a-new-token", "home_assistant")
        third = await found.of(ONE)
        assert third is not None and third is not second and str(third.home_assistant.http.base_url).startswith(BIRCH)
        await remove_of(connections, ONE, "home_assistant")
        assert await found.of(ONE) is None and third.home_assistant.http.is_closed

    asyncio.run(scenario())
    assert stand.seen == [(WILLOW, "/api/", "a-new-token")]


def test_connections_unreadable_keep_the_last_home_and_with_none_seen_are_unavailable() -> None:
    connections = held(h1=(WILLOW, TOKEN), h2=(BIRCH, TOKEN))
    found = homes(connections, StandIn())

    async def scenario() -> None:
        seen = await found.of(ONE)
        connections.down = True
        assert await found.of(ONE) is seen
        with pytest.raises(HomesUnavailable):
            await found.of(TWO)

    asyncio.run(scenario())


def test_without_a_key_the_envs_home_assistant_answers_for_household_one_alone() -> None:
    stand = StandIn()
    found = homes(NullConnections(), stand, fallback=WILLOW)
    bare = homes(NullConnections(), stand)

    async def scenario() -> None:
        one = await found.of(ONE)
        assert one is not None and await found.of(ONE) is one
        assert await found.of(TWO) is None and await bare.of(ONE) is None

    asyncio.run(scenario())


def test_close_closes_every_client_it_made() -> None:
    stand = StandIn()
    found = homes(held(h1=(WILLOW, TOKEN)), stand, fallback=WILLOW)

    async def scenario() -> None:
        await found.of(ONE)
        await found.close()

    asyncio.run(scenario())
    assert len(stand.made) == 2 and all(c.is_closed for c in stand.made)


@pytest.mark.parametrize(("status", "raw", "down", "reason"), [
    (401, None, False, "refused"), (403, None, False, "refused"), (404, None, False, "not_home_assistant"),
    (200, b"<html>sign in</html>", False, "not_home_assistant"), (200, b'{"other": 1}', False, "not_home_assistant"),
    (302, None, False, "unreachable"), (502, None, False, "unreachable"), (None, None, True, "unreachable")])
def test_a_check_that_home_assistant_does_not_pass_says_why(status: int | None, raw: bytes | None, down: bool,
                                                             reason: str) -> None:
    stand = StandIn(status=status, raw=raw, down=down)
    with pytest.raises(HomeAssistantFailed) as failed:
        asyncio.run(homes(HeldConnections(), stand).check(WILLOW, TOKEN))
    assert failed.value.reason == reason
    assert all(c.is_closed for c in stand.made)


def test_a_check_home_assistant_answers_asks_once_with_the_token_and_closes() -> None:
    stand = StandIn()
    asyncio.run(homes(HeldConnections(), stand).check(WILLOW, TOKEN))
    assert stand.seen == [(WILLOW, "/api/", TOKEN)] and stand.made[0].is_closed


def test_the_null_homes_reach_no_house() -> None:
    async def scenario() -> None:
        assert await NullHomes().of(ONE) is None
        with pytest.raises(HomeAssistantFailed):
            await NullHomes().check(WILLOW, TOKEN)

    asyncio.run(scenario())


def test_the_envs_home_assistant_is_seeded_as_household_ones_once_and_never_over_a_row(
        capsys: pytest.CaptureFixture[str]) -> None:
    connections = HeldConnections()
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        await seed_from_env(connections, WILLOW, TOKEN)
        opened = await opened_of(connections, ONE, "home_assistant")
        assert opened is not None and (opened.connection.base_url, opened.secret) == (WILLOW, TOKEN)
        await seed_from_env(connections, BIRCH, "another")
        again = await opened_of(connections, ONE, "home_assistant")
        assert again is not None and (again.connection.base_url, again.secret) == (WILLOW, TOKEN)

    asyncio.run(scenario())
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "event=homes.seed" in ln]
    assert [ln.split("outcome=")[1].split()[0] for ln in lines] == ["seeded", "kept"]
    assert not any(TOKEN in ln or "willow" in ln or "another" in ln for ln in lines)


@pytest.mark.parametrize(("connections", "base", "outcome"), [
    (NullConnections(), WILLOW, "no_key"), (HeldConnections(down=True), WILLOW, "unavailable"),
    (HeldConnections(), "ftp://ha.test", "bad_url")])
def test_a_seed_that_cannot_be_written_is_logged_and_never_raises(
        connections: HeldConnections | NullConnections, base: str, outcome: str,
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    asyncio.run(seed_from_env(connections, base, TOKEN))
    assert f"outcome={outcome}" in capsys.readouterr().out
    if isinstance(connections, HeldConnections):
        assert connections.held == {}
