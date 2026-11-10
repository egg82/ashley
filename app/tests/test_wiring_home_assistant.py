"""Each household's Home Assistant is wired from its connection (`ConnectedHomes`), with presence and the everyday tools
over it, whatever the env says; HA_URL and HA_TOKEN, both or neither, only give household 1 its house while there is
no key to open connections, and are sealed as its connection at start. The locator's `Tools` is the look-up alone."""

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
from ashley.settings import Settings, from_env
from ashley.tools.composite import CompositeTools
from ashley.tools.everyday import Everyday, HomesEveryday
from ashley.tools.tools import Tools
from ashley.wiring import warmups, wire

URL = "postgresql://nobody@127.0.0.1:1/none"
WIRED = (People, Tools, Presence, Homes, Everyday, Connections, Inference)


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    for interface in WIRED:
        services.unregister(interface)
    yield
    for interface in (*WIRED, Database):
        services.unregister(interface)


@pytest.mark.parametrize("ha", [{}, {"ha_url": "http://ha.test:8123", "ha_token": "t"}])
def test_homes_presence_and_the_everyday_tools_are_wired_with_or_without_the_env(ha: dict[str, str]) -> None:
    wire(Settings(database_url=URL, build_version="t", **ha))
    assert isinstance(services.get(People), PostgresPeople)
    assert isinstance(services.get(Homes), ConnectedHomes)
    assert isinstance(services.get(Presence), HomesPresence)
    assert isinstance(services.get(Everyday), HomesEveryday)
    assert isinstance(services.get(Tools), CompositeTools)
    assert [s.name for s in asyncio.run(services.get(Tools).catalogue()).specs] == ["look_up"]


def test_without_a_key_household_one_reaches_the_envs_house_and_no_other_household_does() -> None:
    wire(Settings(database_url=URL, build_version="t", ha_url="http://ha.test:8123", ha_token="t"))
    homes = services.get(Homes)
    one, two = asyncio.run(homes.of(1)), asyncio.run(homes.of(2))
    assert one is not None and str(one.home_assistant.http.base_url).startswith("http://ha.test:8123") and two is None
    assert getattr(asyncio.run(services.get(Everyday).of(1)), "_sources").keys() == {"house", "search"}
    bare = asyncio.run(services.get(Everyday).of(2))
    assert bare is not services.get(Tools) and getattr(bare, "_sources").keys() == {"search"}


@pytest.mark.parametrize("env", [{"HA_URL": "http://ha.test:8123"}, {"HA_TOKEN": "t"}])
def test_one_without_the_other_refuses_to_start(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="HA_URL and HA_TOKEN"):
        from_env({"DATABASE_URL": URL, **env})
    with pytest.raises(ValueError):
        Settings(database_url=URL, build_version="t", **{k.lower(): v for k, v in env.items()})


def test_both_are_read_from_the_environment() -> None:
    settings = from_env({"DATABASE_URL": URL, "HA_URL": "http://ha.test:8123", "HA_TOKEN": "t"})
    assert (settings.ha_url, settings.ha_token) == ("http://ha.test:8123", "t")


def test_the_env_is_seeded_at_start_only_when_set() -> None:
    bare, with_ha = Settings(database_url=URL, build_version="t"), Settings(
        database_url=URL, build_version="t", ha_url="http://ha.test:8123", ha_token="t")
    wire(bare)
    plain = warmups(bare)
    seeding = warmups(with_ha)
    assert len(seeding) == len(plain) + 1
    for job in (*plain, *seeding):
        job.close()


def test_wire_hands_back_what_closes_the_search_client_and_every_house_client() -> None:
    closers = wire(Settings(database_url=URL, build_version="t"))
    assert len(closers) == 4, "the keyed providers, the live feed, Homes and the search client"
    closers += wire(Settings(database_url=URL, build_version="t", ha_url="http://ha.test:8123", ha_token="t"))
    assert len(closers) == 8
    for close in closers:
        asyncio.run(close())
