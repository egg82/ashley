"""A failed start-up seed heals itself (`ConnectedHomes` with the env set): while household 1 has no `home_assistant`
row and none has been seen, the env's HA answers for it and the seed is tried again on a read, at most once per
`RETRY_S`, logged; once a row is seen, a person removing it is respected. Against a real database, a seed that the
`kind` CHECK refuses (a pod started before 0045) is `unavailable`, never an exception."""

import asyncio
from dataclasses import dataclass

import psycopg
import pytest
from ashley import logs
from ashley.connections.connections import ConnectionsUnavailable
from ashley.connections.model import Connection, Kind
from ashley.home_assistant import connected_homes
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.seed import seed_from_env
from ashley.people import admin
from automations_support import CONFIG
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from homes_support import TOKEN, StandIn
from money_support import HeldConnections
from test_connections_postgres import connections_on
from connection_legacy_support import opened_of, remove_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

ENV = "http://ha.willow.test:8123"


@dataclass
class SeedFails(HeldConnections):
    """Seeding raises ConnectionsUnavailable `failures` times, then works; every other call works."""

    failures: int = 0
    seeds: int = 0

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        self.seeds += 1
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionsUnavailable("refused")
        return await super().seed(household_id, kind, base_url, secret)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def base_of(home: object) -> str:
    return str(getattr(home, "home_assistant").http.base_url).rstrip("/")


def test_without_a_row_the_env_answers_and_a_later_read_seeds_it_once_per_interval(
        capsys: pytest.CaptureFixture[str]) -> None:
    connections, clock = SeedFails(failures=2), Clock()
    found = ConnectedHomes(connections, CONFIG, StandIn().connect, env=(ENV, TOKEN), clock=clock)
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        first = await found.of(1)
        assert first is not None and base_of(first) == ENV and connections.seeds == 1
        assert await found.of(1) is first and connections.seeds == 1, "within the interval, no retry"
        assert await found.of(2) is None
        clock.now += connected_homes.RETRY_S
        assert await found.of(1) is first and connections.seeds == 2
        clock.now += connected_homes.RETRY_S
        seeded = await found.of(1)
        assert connections.seeds == 3 and seeded is not None and seeded is not first
        opened = await opened_of(connections, 1, "home_assistant")
        assert opened is not None and (opened.connection.base_url, opened.secret) == (ENV, TOKEN)

    asyncio.run(scenario())
    outcomes = [ln.split("outcome=")[1].split()[0] for ln in capsys.readouterr().out.splitlines()
                if "event=homes.seed " in ln]
    assert outcomes == ["unavailable", "unavailable", "seeded"]


def test_once_a_row_has_been_seen_a_removal_is_respected() -> None:
    connections, clock = SeedFails(), Clock()
    connections.connect(1, "http://ha.own.test", "own", "home_assistant")
    found = ConnectedHomes(connections, CONFIG, StandIn().connect, env=(ENV, TOKEN), clock=clock)

    async def scenario() -> None:
        own = await found.of(1)
        assert own is not None and base_of(own) == "http://ha.own.test"
        await remove_of(connections, 1, "home_assistant")
        clock.now += connected_homes.RETRY_S
        assert await found.of(1) is None and connections.seeds == 0

    asyncio.run(scenario())


def test_connections_unreadable_with_nothing_seen_give_household_one_the_env() -> None:
    connections = SeedFails(down=True)
    found = ConnectedHomes(connections, CONFIG, StandIn().connect, env=(ENV, TOKEN), clock=Clock())
    home = asyncio.run(found.of(1))
    assert home is not None and base_of(home) == ENV


def narrow_kinds(url: str) -> None:
    with psycopg.connect(url) as conn:
        conn.execute("ALTER TABLE connections RENAME TO connections_away")


def widen_kinds(url: str) -> None:
    with psycopg.connect(url) as conn:
        conn.execute("ALTER TABLE connections_away RENAME TO connections")


def test_a_seed_before_the_migration_is_unavailable_and_a_read_after_it_seeds_the_row(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    with psycopg.connect(db_url) as conn:
        household = admin.add_household(conn, "home", "UTC")
    assert household == 1
    narrow_kinds(db_url)
    clock = Clock()
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        async with connections_on(db_url) as connections:
            await seed_from_env(connections, ENV, TOKEN)
            found = ConnectedHomes(connections, CONFIG, StandIn().connect, env=(ENV, TOKEN), clock=clock)
            home = await found.of(1)
            assert home is not None and base_of(home) == ENV
            widen_kinds(db_url)
            clock.now += connected_homes.RETRY_S
            again = await found.of(1)
            assert again is not None and again is not home and base_of(again) == ENV

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'home_assistant'") == 1
    out = capsys.readouterr().out
    assert "event=homes.seed household=1 outcome=unavailable" in out and "outcome=seeded" in out
