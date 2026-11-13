"""`HouseholdConnection.checked_at` is "when the service last answered with it": a WebSocket command a household's Home
Assistant answers moves that household's connection, one write per command, as a REST read does; a command it does not
answer, or one made with another household's client, leaves it."""

import pytest
from ashley.connections.connections import Connections
from ashley.home_assistant.ha_socket import Commands
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from ashley.home_assistant.homes import Home
from contract.conversations_support import scalar
from ha_ws_answered_support import (Ha, World, age, all_logs, connections, count_writes, go,
                                    hold, homes, log_text, settings, stored_at, writes)

LIST = {"type": "config/area_registry/list"}


async def opened(c: Connections, world: World, ha: Ha, household: int) -> Home:
    home = await homes(c, ha).of(household)
    assert home is not None
    return home


def test_a_command_moves_checked_at_each_time(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            commands = Commands((await opened(c, world, ha, world.home)).home_assistant, settings())
            before = age(world.url, world.home)
            await commands.run(LIST)
            first = stored_at(world.url, world.home)
            assert first > before
            age(world.url, world.home)
            await commands.run(LIST)
            assert stored_at(world.url, world.home) > before

    go(scenario())


def test_one_write_per_command(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            commands = Commands((await opened(c, world, ha, world.home)).home_assistant, settings())
            count_writes(world.url)
            for expected in (1, 2, 3):
                await commands.run(LIST)
                assert writes(world.url) == expected

    go(scenario())


@pytest.mark.parametrize("failure", ["rejected", "refused", "dropped", "garbage"])
def test_a_command_home_assistant_does_not_answer_leaves_checked_at(world: World, ha: Ha, failure: str) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            commands = Commands((await opened(c, world, ha, world.home)).home_assistant, settings())
            before = age(world.url, world.home)
            count_writes(world.url)
            ha.auth_ok, ha.drop, ha.garbage = failure != "refused", failure == "dropped", failure == "garbage"
            command = {"type": "reject/x"} if failure == "rejected" else LIST
            with pytest.raises(HouseRejected if failure == "rejected" else HouseUnavailable):
                await commands.run(command)
            assert stored_at(world.url, world.home) == before
            assert writes(world.url) == 0

    go(scenario())


def test_a_command_moves_only_its_own_households_connection(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            await hold(c, world, world.other)
            commands = Commands((await opened(c, world, ha, world.home)).home_assistant, settings())
            mine, theirs = age(world.url, world.home), age(world.url, world.other)
            await commands.run(LIST)
            assert stored_at(world.url, world.home) > mine
            assert stored_at(world.url, world.other) == theirs

    go(scenario())


def test_two_households_clients_each_move_their_own(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            await hold(c, world, world.other)
            service = homes(c, ha)
            home, other = await service.of(world.home), await service.of(world.other)
            assert home is not None and other is not None
            mine, theirs = age(world.url, world.home), age(world.url, world.other)
            await Commands(other.home_assistant, settings()).run(LIST)
            assert stored_at(world.url, world.home) == mine
            assert stored_at(world.url, world.other) > theirs

    go(scenario())


def test_a_rest_read_still_moves_checked_at(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            before = age(world.url, world.home)
            response = await home.home_assistant.http.get("/api/")
            assert response.status_code == 200
            assert stored_at(world.url, world.home) > before

    go(scenario())


def test_a_registry_read_through_her_house_moves_it_once_per_command(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            before = age(world.url, world.home)
            count_writes(world.url)
            await home.house.records("area")
            assert ha.commands, "an area registry read goes over the WebSocket"
            assert stored_at(world.url, world.home) > before
            assert writes(world.url) == ha.ws_ok + ha.rest_ok

    go(scenario())


def test_a_registry_write_through_her_house_moves_it(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            before = age(world.url, world.home)
            count_writes(world.url)
            await home.house.create_record("area", {"name": "den"})
            assert [x["type"] for x in ha.commands].count("config/area_registry/create") == 1
            assert stored_at(world.url, world.home) > before
            assert writes(world.url) == ha.ws_ok + ha.rest_ok

    go(scenario())


def test_a_helper_listing_through_her_house_moves_it(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            before = age(world.url, world.home)
            await home.house.configs("helper")
            assert ha.commands, "helper listing goes over the WebSocket"
            assert stored_at(world.url, world.home) > before

    go(scenario())


def test_a_connection_that_is_gone_does_not_fail_the_command(world: World, ha: Ha, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            commands = Commands((await opened(c, world, ha, world.home)).home_assistant, settings())
            all_logs(caplog)
            assert await commands.run(LIST) == []
            scalar(world.url, "DELETE FROM connections WHERE household_id = %s RETURNING 1", (world.home,))
            assert await commands.run(LIST) == []

    go(scenario())
    assert "ha-token-0001-SECRETKEY" not in log_text(caplog)


def test_a_rest_read_that_failed_or_was_not_json_leaves_it(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            before = age(world.url, world.home)
            count_writes(world.url)
            refused = await home.home_assistant.http.get("/api/", headers={"Authorization": "Bearer wrong-0002"})
            assert refused.status_code == 401
            plain = await home.home_assistant.http.get("/api/text")
            assert plain.status_code == 200 and plain.headers["content-type"].startswith("text/plain")
            assert stored_at(world.url, world.home) == before and writes(world.url) == 0

    go(scenario())


def test_a_rest_read_is_one_write(world: World, ha: Ha) -> None:
    async def scenario() -> None:
        async with connections(world.url) as c:
            await hold(c, world, world.home)
            home = await opened(c, world, ha, world.home)
            count_writes(world.url)
            for expected in (1, 2):
                await home.home_assistant.http.get("/api/")
                assert writes(world.url) == expected

    go(scenario())

