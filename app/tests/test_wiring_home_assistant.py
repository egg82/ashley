"""Each household's Home Assistant is wired from its connection (`ConnectedHomes`), with presence and the everyday tools
over it. The locator's `Tools` is the look-up alone."""

import asyncio
from collections.abc import Generator

import pytest

from ashley import services
from ashley.connections.connections import Connections
from ashley.db.database import Database
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Homes
from ashley.inference.inference import Inference
from ashley.people.people import People
from ashley.people.postgres import PostgresPeople
from ashley.senses.homes_presence import HomesPresence
from ashley.senses.presence import Presence
from ashley.settings import Settings
from ashley.tools.composite import CompositeTools
from ashley.tools.everyday import Everyday, HomesEveryday
from ashley.tools.tools import Tools
from ashley.wiring import wire

URL = "postgresql://nobody@127.0.0.1:1/none"
WIRED = (People, Tools, Presence, Homes, Everyday, Connections, Inference)


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    for interface in WIRED:
        services.unregister(interface)
    yield
    for interface in (*WIRED, Database):
        services.unregister(interface)


def test_homes_presence_and_the_everyday_tools_are_wired() -> None:
    wire(Settings(database_url=URL, build_version="t"))
    assert isinstance(services.get(People), PostgresPeople)
    assert isinstance(services.get(Homes), ConnectedHomes)
    assert isinstance(services.get(Presence), HomesPresence)
    assert isinstance(services.get(Everyday), HomesEveryday)
    assert isinstance(services.get(Tools), CompositeTools)
    assert [s.name for s in asyncio.run(services.get(Tools).catalogue()).specs] == ["look_up"]


def test_without_a_key_no_household_reaches_a_house() -> None:
    wire(Settings(database_url=URL, build_version="t"))
    homes = services.get(Homes)
    assert asyncio.run(homes.of(1)) is None and asyncio.run(homes.of(2)) is None
    bare = asyncio.run(services.get(Everyday).of(1))
    assert getattr(bare, "_sources").keys() == {"search"}


def test_wire_hands_back_what_closes_the_search_client_and_every_house_client() -> None:
    closers = wire(Settings(database_url=URL, build_version="t"))
    assert len(closers) == 5, "the keyed providers, the live feed, Homes, the search client and the Discord channel client"
    for close in closers:
        asyncio.run(close())
