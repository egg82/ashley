"""`HomeAssistant.answered` is "awaited once per WebSocket command Home Assistant answered successfully": a rejected
command, a refused token, a connection that drops or an answer that is not read awaits nothing. `Commands.run` awaits it
after the result is accepted, and the default records nothing."""

import asyncio

import pytest
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.ha_socket import Commands
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from ha_ws_answered_support import TOKEN, Counter, Ha, client_for, go, settings


def run(client: HomeAssistant, command: dict[str, object]) -> object:
    return go(Commands(client, settings()).run(command))


def test_the_default_answered_is_an_awaitable_that_does_nothing(ha: Ha) -> None:
    client = client_for(ha.url)

    async def awaited() -> None:
        return await client.answered()

    assert go(awaited()) is None


def test_a_command_with_the_default_callback_returns_its_result(ha: Ha) -> None:
    assert run(client_for(ha.url), {"type": "config/area_registry/list"}) == []


def test_a_successful_command_awaits_answered_once(ha: Ha) -> None:
    counter = Counter()
    assert run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"}) == []
    assert counter.n == 1


def test_each_command_awaits_it_once_more(ha: Ha) -> None:
    counter = Counter()
    commands = Commands(client_for(ha.url, answered=counter), settings())

    async def scenario() -> None:
        for expected in (1, 2, 3):
            await commands.run({"type": "config/floor_registry/list"})
            assert counter.n == expected

    go(scenario())
    assert ha.connections == 3


def test_commands_run_together_each_await_it_once(ha: Ha) -> None:
    counter = Counter()
    commands = Commands(client_for(ha.url, answered=counter), settings())

    async def scenario() -> None:
        await asyncio.gather(*(commands.run({"type": "config/label_registry/list"}) for _ in range(4)))

    go(scenario())
    assert counter.n == 4


def test_a_write_command_awaits_it_once_and_returns_the_result(ha: Ha) -> None:
    counter = Counter()
    got = run(client_for(ha.url, answered=counter), {"type": "config/area_registry/create", "name": "den"})
    assert isinstance(got, dict) and got["name"] == "den"
    assert counter.n == 1


def test_answered_is_awaited_before_run_returns(ha: Ha) -> None:
    done: list[str] = []

    async def slow() -> None:
        await asyncio.sleep(0.05)
        done.append("answered")

    run(client_for(ha.url, answered=slow), {"type": "config/area_registry/list"})
    assert done == ["answered"]


def test_answered_is_awaited_after_home_assistant_has_answered(ha: Ha) -> None:
    seen: list[int] = []

    async def note() -> None:
        seen.append(len(ha.commands))

    run(client_for(ha.url, answered=note), {"type": "config/area_registry/list"})
    assert seen == [1]


def test_a_rejected_command_raises_and_awaits_nothing(ha: Ha) -> None:
    counter = Counter()
    with pytest.raises(HouseRejected) as raised:
        run(client_for(ha.url, answered=counter), {"type": "reject/config/area_registry/create"})
    assert raised.value.message == "extra keys not allowed"
    assert counter.n == 0


def test_a_rejection_does_not_spoil_the_next_command(ha: Ha) -> None:
    counter = Counter()
    commands = Commands(client_for(ha.url, answered=counter), settings())

    async def scenario() -> None:
        with pytest.raises(HouseRejected):
            await commands.run({"type": "reject/x"})
        await commands.run({"type": "config/area_registry/list"})
        with pytest.raises(HouseRejected):
            await commands.run({"type": "reject/y"})

    go(scenario())
    assert counter.n == 1


def test_a_refused_token_raises_unavailable_and_awaits_nothing(ha: Ha) -> None:
    counter = Counter()
    with pytest.raises(HouseUnavailable) as raised:
        run(client_for(ha.url, token="wrong-token-0002", answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0
    assert TOKEN not in str(raised.value) and "wrong-token-0002" not in str(raised.value)


def test_a_house_that_refuses_every_login_awaits_nothing(ha: Ha) -> None:
    ha.auth_ok = False
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_a_connection_that_drops_awaits_nothing(ha: Ha) -> None:
    ha.drop = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_an_answer_that_is_not_read_awaits_nothing(ha: Ha) -> None:
    ha.garbage = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_a_house_that_cannot_be_reached_awaits_nothing() -> None:
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for("http://127.0.0.1:9", answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_a_rest_read_through_the_client_does_not_await_it(ha: Ha) -> None:
    counter = Counter()
    client = client_for(ha.url, answered=counter)
    response = go(client.http.get("/api/"))
    assert response.status_code == 200 and ha.rest_ok == 1
    assert counter.n == 0


def test_an_error_of_a_kind_it_does_not_read_is_unavailable_and_awaits_nothing(ha: Ha) -> None:
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "odd/x"})
    assert counter.n == 0


def test_an_answer_that_is_not_a_result_awaits_nothing(ha: Ha) -> None:
    ha.event = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_the_result_is_returned_whatever_the_callback_does_with_the_time(ha: Ha) -> None:
    async def slow() -> None:
        await asyncio.sleep(0.01)

    got = run(client_for(ha.url, answered=slow), {"type": "config/area_registry/create", "name": "den"})
    assert isinstance(got, dict) and got["name"] == "den"


def test_an_answer_with_no_verdict_awaits_nothing(ha: Ha) -> None:
    ha.shapeless = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0


def test_a_house_that_says_the_token_is_invalid_but_keeps_listening_awaits_nothing(ha: Ha) -> None:
    ha.stubborn = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, token="wrong-token-0002", answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0 and ha.commands == []


def test_a_house_that_does_not_greet_as_home_assistant_does_awaits_nothing(ha: Ha) -> None:
    ha.mute = True
    counter = Counter()
    with pytest.raises(HouseUnavailable):
        run(client_for(ha.url, answered=counter), {"type": "config/area_registry/list"})
    assert counter.n == 0 and ha.commands == []
