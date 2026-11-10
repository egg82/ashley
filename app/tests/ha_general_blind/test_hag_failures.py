"""How HaHouse tells a failure apart: a refused token, an unreachable house, a server error, a non-JSON answer, a socket
that closes or errors, each as HouseUnavailable and never naming the token or a body."""

import pytest
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from contract.conversations_support import run
from hag_state_support import TOKEN, Ha
from hag_support import dead_house, furnish, make_house


def test_a_refused_token_is_unavailable_on_rest_without_naming_it(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        for call in ("states", "actions"):
            with pytest.raises(HouseUnavailable) as raised:
                await getattr(make_house(ha, token="not-the-token"), call)()
            assert "not-the-token" not in str(raised.value) and TOKEN not in str(raised.value)
    run(go())


def test_a_refused_token_on_the_socket_is_unavailable_without_naming_it(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseUnavailable) as raised:
            await make_house(ha, token="not-the-token").records("area")
        assert "not-the-token" not in str(raised.value) and TOKEN not in str(raised.value)
    run(go())


def test_an_unreachable_house_a_server_error_and_a_non_json_answer_are_unavailable(ha: Ha) -> None:
    furnish(ha)

    async def go() -> None:
        with pytest.raises(HouseUnavailable):
            await dead_house().states()
        with pytest.raises(HouseUnavailable):
            await dead_house().records("device")
        ha.status = 500
        with pytest.raises(HouseUnavailable) as raised:
            await make_house(ha).states()
        assert "broken" not in str(raised.value)
        ha.status = None
        ha.garbage = True
        with pytest.raises(HouseUnavailable) as raised:
            await make_house(ha).actions()
        assert "not json" not in str(raised.value)
    run(go())


def test_a_socket_dropped_before_its_greeting_is_unavailable_for_a_read(ha: Ha) -> None:
    furnish(ha)
    ha.ws_drop = True

    async def go() -> None:
        with pytest.raises(HouseUnavailable):
            await make_house(ha).records("area")
    run(go())


def test_a_command_the_house_errors_on_is_rejected_or_unavailable_never_another_exception(ha: Ha) -> None:
    furnish(ha)
    ha.ws_error = "unknown_error"

    async def go() -> None:
        with pytest.raises((HouseUnavailable, HouseRejected)):
            await make_house(ha).records("area")
    run(go())
