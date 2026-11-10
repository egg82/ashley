"""Presence and room speakers through each household's own Home Assistant: `senses.homes_presence.HomesPresence` reads a
household's people on its own house and answers unknown (logged) for a household with no house or one unreadable now;
`home_assistant.media_player.play_for` plays on the household's own house and is False without one."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import logs, services
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.media_player import play_for
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.homes_presence import HomesPresence
from homes_support import ByHousehold, StandIn

ALANA = Account(10, 1, 1, "home_assistant", "person.alana")


class FixedPeople(People):
    def __init__(self, accounts: tuple[Account, ...]) -> None:
        self._accounts = accounts

    async def household(self, household_id: int) -> Household | None:
        raise AssertionError("presence reads accounts only")

    async def person_for(self, system: str, external_id: str) -> Person | None:
        raise AssertionError("presence reads accounts only")

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return self._accounts
CLIP = "https://ashley.test/clip"


@pytest.fixture
def house() -> Generator[ByHousehold]:
    made = ByHousehold()
    services.register(Homes, made)
    yield made
    services.unregister(Homes)


def test_presence_reads_the_households_own_house(house: ByHousehold) -> None:
    stand = StandIn(token="t")
    house.give(1, "http://one.test", stand)
    assert asyncio.run(HomesPresence(FixedPeople((ALANA,))).home(1)) == frozenset({1})
    assert stand.seen == [("http://one.test", "/api/states/person.alana", "t")]


@pytest.mark.parametrize(("down", "reason"), [(False, "no_house"), (True, "house_unavailable")])
def test_presence_without_a_readable_house_is_unknown(house: ByHousehold, down: bool, reason: str,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    house.down = down
    logs.setup()
    capsys.readouterr()
    assert asyncio.run(HomesPresence(FixedPeople((ALANA,))).home(2)) is None
    assert f"event=presence.unknown reason={reason}" in capsys.readouterr().out


def test_a_room_speaker_plays_on_the_households_own_house(house: ByHousehold) -> None:
    stand = StandIn(token="t")
    house.give(1, "http://one.test", stand)
    assert asyncio.run(play_for(1, "media_player.kitchen", CLIP)) is True
    assert stand.seen == [("http://one.test", "/api/services/media_player/play_media", "t")]
    assert asyncio.run(play_for(2, "media_player.kitchen", CLIP)) is False
    house.down = True
    assert asyncio.run(play_for(1, "media_player.kitchen", CLIP)) is False
