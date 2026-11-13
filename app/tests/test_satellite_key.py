"""The satellites' Noise key as a connection, on a real database: the env seeds the first household's row once, by one of
several pods at once, and never over an edited row; a satellite is reached with its own household's row, the env's key
only for the first household and only where there is no row; with no key a satellite is a failed connect, retried; the
kind's check tells a key's shape from anything else."""

import asyncio
import base64

import psycopg
import pytest
from ashley import logs
from ashley.channels.model import Device, Satellite
from ashley.channels.voice import config
from ashley.channels.voice.key_in_force import KeyInForce, NoKey
from ashley.channels.voice.key_kind import KIND, check
from ashley.channels.voice.key_seed import Outcome, seed_key
from ashley.channels.voice.session import hold
from ashley.connections.connections import ConnectionsUnavailable, NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import events, scalar
from test_connections_postgres import connections_on
from voice_support import FakeConnection, FakeTurnLoop, pipeline, settle

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

ENV = base64.b64encode(b"e" * 32).decode()
ROW = base64.b64encode(b"r" * 32).decode()
OTHER = base64.b64encode(b"o" * 32).decode()


def households(url: str) -> tuple[int, int]:
    with psycopg.connect(url) as conn:
        first = admin.add_household(conn, "home", "UTC")
        assert first == FIRST_HOUSEHOLD
        return admin.add_person(conn, first, "Alana"), admin.add_household(conn, "other", "UTC")


def test_the_env_seeds_the_row_once_never_over_an_edit_and_the_row_then_wins(db_url: str) -> None:
    alana, _ = households(db_url)

    async def scenario() -> tuple[list[Outcome], Outcome, list[str]]:
        async with connections_on(db_url) as connections:
            first = list(await asyncio.gather(*(seed_key(connections, ENV) for _ in range(6))))
            before = await KeyInForce(lambda: connections, "")(FIRST_HOUSEHOLD)
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.kind == KIND.name)
            await connections.replace(row.id, FIRST_HOUSEHOLD, alana, row.base_url, ROW)
            again = await seed_key(connections, ENV)
            return first, again, [before, await KeyInForce(lambda: connections, OTHER)(FIRST_HOUSEHOLD)]
    first, again, read = asyncio.run(scenario())
    assert sorted(first) == ["kept"] * 5 + ["seeded"]
    assert again == "kept"
    assert read == [ENV, ROW], "the seeded key is the env's; the edit wins over a seed and over the env"
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'esphome'") == 1


def test_without_the_apps_key_nothing_is_written_and_the_env_answers() -> None:
    assert asyncio.run(seed_key(NullConnections(), ENV)) == "no_key"
    assert asyncio.run(KeyInForce(NullConnections, ENV)(FIRST_HOUSEHOLD)) == ENV


def test_the_key_in_force_is_the_households_row_then_for_the_first_household_the_env_then_none(db_url: str) -> None:
    alana, other = households(db_url)

    async def scenario() -> list[str]:
        async with connections_on(db_url) as connections:
            seen: list[str] = []
            for household, env in ((FIRST_HOUSEHOLD, ENV), (other, ENV), (FIRST_HOUSEHOLD, "")):
                try:
                    seen.append(await KeyInForce(lambda: connections, env)(household))
                except NoKey:
                    seen.append("none")
            added = await connections.add(FIRST_HOUSEHOLD, KIND.name, "", str(KIND.fixed_address), ROW, alana)
            seen.append(await KeyInForce(lambda: connections, ENV)(FIRST_HOUSEHOLD))
            await connections.remove(added.id, FIRST_HOUSEHOLD, None)
            seen.append(await KeyInForce(lambda: connections, ENV)(FIRST_HOUSEHOLD))
            return seen
    assert asyncio.run(scenario()) == [ENV, "none", "none", ROW, ENV]


def test_unreadable_rows_are_no_key_not_the_env(db_url: str) -> None:
    class Down(NullConnections):
        def can_open(self) -> bool:
            return True

        async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[()]:
            raise ConnectionsUnavailable("down")

    with pytest.raises(NoKey):
        asyncio.run(KeyInForce(Down, ENV)(FIRST_HOUSEHOLD))


def test_a_satellite_with_no_key_is_a_failed_connect_that_is_retried(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    echo = Satellite(Device(5, 1, "office echo", "office", "present", "spoken", "command"), "10.0.0.9", None)
    connection = FakeConnection()
    asked: list[int] = []

    async def connect(satellite: Satellite) -> FakeConnection:
        asked.append(satellite.device.household_id)
        if len(asked) < 3:
            raise NoKey("no satellite key is set")
        return connection

    async def sleep(_: float) -> None:
        await asyncio.sleep(0)

    async def scenario() -> None:
        task = asyncio.create_task(hold(echo, connect, pipeline(FakeTurnLoop()), config.load(), sleep))
        await settle()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
    out = capsys.readouterr().out
    assert asked == [1, 1, 1] and connection.connects == 1
    assert [e["error"] for e in events(out, "voice.connect_failed")] == ["NoKey"], "logged once, with the type only"


@pytest.mark.parametrize(("key", "refused"), [(ENV, False), ("", True), ("not base64!", True),
                                              (base64.b64encode(b"short").decode(), True)])
def test_the_check_reads_the_keys_shape(key: str, refused: bool) -> None:
    assert (asyncio.run(check(str(KIND.fixed_address), key, 1)) == "key_refused") is refused
