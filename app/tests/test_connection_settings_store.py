"""A connection's settings in Postgres, through the reader and writer a route and the readers use: replaced whole under a
version, one log row per changed key in the same transaction, the log pruned by the write, nothing visible across
households or on a person's own connection, and the migration that seeds Moore's lists from the shipped files."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import psycopg
import pytest
from alembic import command
from ashley import services
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.settings import SettingsInvalid
from ashley.connections.settings_postgres import PostgresSettingsReader
from ashley.connections.settings_write import RETAIN_DAYS, VersionConflict
from ashley.connections.settings_write_postgres import PostgresSettingsWriter
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.kind import HOME_ASSISTANT
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, scalar

LISTS = {"todo.get_items": ["todo.inbox", "todo.groceries"]}


def household(url: str, name: str = "home") -> tuple[int, int]:
    home = int(scalar(url, "INSERT INTO households (name) VALUES (%s) RETURNING id", (name,)))
    return home, int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'A') RETURNING id", (home,)))


def connection(url: str, home: int, kind: str = "home_assistant", person: int | None = None) -> int:
    return int(scalar(url, "INSERT INTO connections (household_id, kind, label, base_url, secret, person_id) "
                           "VALUES (%s, %s, '', 'http://ha.test', '\\x00', %s) RETURNING id", (home, kind, person)))


def run(url: str, scenario: Callable[[PostgresSettingsReader, PostgresSettingsWriter], Coroutine[Any, Any, None]]) -> None:
    async def go() -> None:
        db = PoolDatabase(url)
        await db.open()
        try:
            services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
            await scenario(PostgresSettingsReader(db), PostgresSettingsWriter(db))
        finally:
            await db.close()

    asyncio.run(go())


def test_a_connection_never_set_reads_as_version_zero_and_nothing(db_url: str) -> None:
    home, _ = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        stored = await reader.stored(cid, home)
        assert (stored.version, stored.values, stored.updated_at, stored.updated_by) == (0, {}, None, None)
        assert await reader.of(home, "house") == {}

    run(db_url, scenario)


def test_a_write_is_stored_whole_and_read_back_by_connection_and_by_port(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        stored = await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"household_reads": LISTS, "reads": ["script.a"]})
        assert stored is not None and stored.version == 1 and stored.updated_by == person
        assert (await reader.stored(cid, home)).values == {"household_reads": LISTS, "reads": ["script.a"]}
        assert await reader.of(home, "house") == {"household_reads": LISTS, "reads": ["script.a"]}
        second = await writer.put(HOME_ASSISTANT, cid, home, person, 1, {"reads": ["script.b"]})
        assert second is not None and second.version == 2 and second.values == {"reads": ["script.b"]}, "replaced, not merged"
        assert await reader.of(home, "house") == {"reads": ["script.b"]}

    run(db_url, scenario)


def test_a_write_at_a_stale_version_is_refused_and_changes_nothing(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]})
        with pytest.raises(VersionConflict):
            await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.z"]})
        with pytest.raises(VersionConflict):
            await writer.put(HOME_ASSISTANT, cid, home, person, 5, {"reads": ["script.z"]})
        stored = await reader.stored(cid, home)
        assert (stored.version, stored.values) == (1, {"reads": ["script.a"]})
        assert len(await reader.history(cid, home, 10)) == 1

    run(db_url, scenario)


def test_two_writes_at_one_version_let_exactly_one_through(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        got = await asyncio.gather(*(writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": [f"script.s{i}"]})
                                     for i in range(4)), return_exceptions=True)
        assert sum(isinstance(g, VersionConflict) for g in got) == 3
        assert (await reader.stored(cid, home)).version == 1

    run(db_url, scenario)


def test_an_invalid_value_is_refused_before_anything_is_written(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        with pytest.raises(SettingsInvalid) as refused:
            await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["not an id"]})
        assert (refused.value.key, refused.value.reason) == ("reads", "bad_id")
        assert (await reader.stored(cid, home)).version == 0

    run(db_url, scenario)


def test_each_changed_key_is_logged_once_with_who_and_what_it_was(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"], "service_reads": ["weather.x"]})
        await writer.put(HOME_ASSISTANT, cid, home, person, 1, {"reads": ["script.a", "script.b"], "service_reads": ["weather.x"]})
        keys = [c.key for c in await reader.history(cid, home, 10)]
        assert sorted(keys) == ["reads", "reads", "service_reads"]
        assert {c.changed_by for c in await reader.history(cid, home, 10)} == {person}
        with psycopg.connect(db_url) as conn:
            row = conn.execute("SELECT before, after FROM connection_settings_log WHERE key = 'reads' "
                               "ORDER BY id DESC LIMIT 1").fetchone()
        assert row == (["script.a"], ["script.a", "script.b"])

    run(db_url, scenario)


def test_a_key_set_for_the_first_time_logs_no_before_and_one_cleared_logs_no_after(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]})
        await writer.put(HOME_ASSISTANT, cid, home, person, 1, {})
        with psycopg.connect(db_url) as conn:
            rows = conn.execute("SELECT before, after FROM connection_settings_log ORDER BY id").fetchall()
        assert rows == [(None, ["script.a"]), (["script.a"], None)]

    run(db_url, scenario)


def test_history_pages_newest_first(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        for version in range(3):
            await writer.put(HOME_ASSISTANT, cid, home, person, version, {"reads": [f"script.s{version}"]})
        first = await reader.history(cid, home, 2)
        rest = await reader.history(cid, home, 2, before=first[-1].id)
        assert [c.id for c in first] == sorted((c.id for c in first), reverse=True) and len(first) == 2
        assert len(rest) == 1 and rest[0].id < first[-1].id

    run(db_url, scenario)


def test_a_write_prunes_the_log_past_retention_and_keeps_what_is_within_it(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)
    with psycopg.connect(db_url, autocommit=True) as conn:
        for days in (RETAIN_DAYS + 1, RETAIN_DAYS - 1):
            conn.execute("INSERT INTO connection_settings_log (connection_id, household_id, key, changed_at) "
                         "VALUES (%s, %s, %s, now() - make_interval(days => %s))", (cid, home, f"aged{days}", days))

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        assert len(await reader.history(cid, home, 10)) == 2
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]})
        keys = {c.key for c in await reader.history(cid, home, 10)}
        assert keys == {f"aged{RETAIN_DAYS - 1}", "reads"}

    run(db_url, scenario)


def test_another_household_reads_and_writes_nothing_of_it(db_url: str) -> None:
    home, person = household(db_url)
    other, outsider = household(db_url, "other")
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]})
        assert await writer.put(HOME_ASSISTANT, cid, other, outsider, 0, {"reads": ["script.x"]}) is None
        assert (await reader.stored(cid, other)).version == 0
        assert await reader.history(cid, other, 10) == ()
        assert await reader.of(other, "house") == {}
        assert (await reader.stored(cid, home)).values == {"reads": ["script.a"]}

    run(db_url, scenario)


def test_a_person_s_own_connection_takes_no_settings(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home, person=person)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        assert await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]}) is None

    run(db_url, scenario)


def test_settings_of_another_port_are_not_read_as_the_house_s(db_url: str) -> None:
    home, _ = household(db_url)
    cid = connection(db_url, home, kind="sure")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO connection_settings (connection_id, household_id, values, version, updated_at) "
                     "VALUES (%s, %s, '{\"reads\": [\"script.a\"]}', 1, now())", (cid, home))

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        assert await reader.of(home, "house") == {}
        assert await reader.of(home, "ledger") == {"reads": ["script.a"]}

    run(db_url, scenario)


def test_settings_that_cannot_be_read_are_none_not_an_error(db_url: str) -> None:
    home, _ = household(db_url)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        dead = PostgresSettingsReader(PoolDatabase("postgresql://postgres:t@127.0.0.1:1/none", connect_timeout_s=0.5))
        assert await dead.of(home, "house") == {}

    run(db_url, scenario)


def test_removing_the_connection_removes_its_settings_and_keeps_the_log_until_retention(db_url: str) -> None:
    home, person = household(db_url)
    cid = connection(db_url, home)

    async def scenario(reader: PostgresSettingsReader, writer: PostgresSettingsWriter) -> None:
        await writer.put(HOME_ASSISTANT, cid, home, person, 0, {"reads": ["script.a"]})
        scalar(db_url, "DELETE FROM connections WHERE id = %s RETURNING 1", (cid,))
        assert int(scalar(db_url, "SELECT count(*) FROM connection_settings")) == 0
        assert int(scalar(db_url, "SELECT count(*) FROM connection_settings_log")) == 1

    run(db_url, scenario)


def seeded(url: str, with_connection: bool) -> list[tuple[Any, ...]]:
    """The migration run over a database that has household 1, with or without its Home Assistant connection."""
    config = alembic_config(url)
    command.downgrade(config, "0084")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'moore') ON CONFLICT DO NOTHING")
        if with_connection:
            conn.execute("INSERT INTO connections (household_id, kind, label, base_url, secret) "
                         "VALUES (1, 'home_assistant', '', 'http://ha.test', '\\x00')")
    command.upgrade(config, "0085")
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT household_id, values, version FROM connection_settings").fetchall()


def test_the_migration_seeds_nothing_on_household_ones_connection_either(db_url: str) -> None:
    assert seeded(db_url, True) == []


def test_the_migration_seeds_nothing_where_there_is_no_connection(db_url: str) -> None:
    assert seeded(db_url, False) == []
