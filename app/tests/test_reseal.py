"""Rotating `CONNECTIONS_KEY` (`connections.reseal`): the pass seals every sealed column under the current key and loses
nothing when a pod dies mid-pass; a value that opens under neither key is left as it was, counted and logged by row id;
`reseal` is a singleton under the lease, started only while a second key is named; a log line never holds a value, a
key or a sealed byte. Keys are made here at run time."""

import asyncio
import base64
import hashlib
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

import psycopg
import pytest
from ashley import logs, services
from ashley.connections import reseal
from ashley.connections.reseal_columns import SEALED, SealedColumn
from ashley.connections.sealing import Sealer, bound_to, sealer_of
from ashley.db.database import Database, DatabaseUnavailable
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings, from_env
from ashley.wiring_singletons import singletons
from contract.conversations_support import blank_ts, db_url as db_url, migrated_template as migrated_template, run

OLD, NEW, OTHER = os.urandom(32), os.urandom(32), os.urandom(32)
FROM_OLD, TO_NEW = Sealer({1: OLD}), Sealer({1: OLD, 2: NEW}, current=2)
PLAIN = {"connections.secret": "plain-secret-aaa", "connections.access_token": "plain-access-bbb",
         "deployment_secrets.sealed": "plain-deployment-ccc", "connect_pending.verifier": "plain-verifier-ddd",
         "proton_bridge.vault": "plain-vault-eee", "proton_bridge.keychain": "plain-keychain-fff",
         "proton_bridge.keeper_access": "plain-keeper-ggg"}
NOT_SEALED = {"connect_pending.state_sha256", "devices.token_sha256", "link_pending.state_sha256",
              "proton_bridge.token_sha256", "sessions.token_sha256", "signin_pending.state_sha256",
              "voice_clips.token_sha256"}
"""The `bytea` columns that hold a hash, not a sealed value."""


def plant(url: str, sealer: Sealer = FROM_OLD, secret: str = PLAIN["connections.secret"]) -> dict[str, int]:
    """One value in every column of `SEALED`, sealed by `sealer`, `secret` in `connections.secret`. Returns the ids."""
    with psycopg.connect(url, autocommit=True) as conn:
        house = admin.add_household(conn, "h", "UTC")
        person = admin.add_person(conn, house, "Alana")

        def sealed(name: str, bound: bytes) -> bytes:
            return sealer.seal(secret if name == "connections.secret" else PLAIN[name], bound)
        row = conn.execute(
            "INSERT INTO connections (household_id, kind, label, base_url, secret, access_token) "
            "VALUES (%s, 'sure', '', 'https://x.test', %s, %s) RETURNING id",
            (house, sealed("connections.secret", bound_to(house, "sure")),
             sealed("connections.access_token", bound_to(house, "sure")))).fetchone()
        assert row is not None
        conn.execute("INSERT INTO deployment_secrets (name, sealed) VALUES ('files_link_key', %s)",
                     (sealed("deployment_secrets.sealed", b"deployment:files_link_key"),))
        conn.execute("INSERT INTO connect_pending (state_sha256, household_id, person_id, kind, label, holder, verifier) "
                     "VALUES (%s, %s, %s, 'google', '', 'person', %s)",
                     (os.urandom(32), house, person, sealed("connect_pending.verifier", f"connect:{house}:{person}".encode())))
        conn.execute("UPDATE proton_bridge SET vault = %s, keychain = %s, keeper_access = %s",
                     (sealed("proton_bridge.vault", b"proton_bridge:vault"),
                      sealed("proton_bridge.keychain", b"proton_bridge:keychain"),
                      sealed("proton_bridge.keeper_access", b"proton_bridge:keeper")))
    return {"connection": row[0]}


def stored(url: str, c: SealedColumn) -> list[tuple[Any, ...]]:
    extra = "".join(f", {e}" for e in c.extra)
    with psycopg.connect(url, autocommit=True) as conn:
        rows = conn.execute(f"SELECT {c.column}{extra} FROM {c.table} WHERE {c.column} IS NOT NULL".encode()).fetchall()
    assert rows, f"{c.name} holds nothing, so nothing here proves it was sealed again"
    return rows


def assert_all_current(url: str, sealer: Sealer) -> None:
    for c in SEALED:
        for row in stored(url, c):
            assert bytes(row[0])[0] == sealer.current, c.name
            assert sealer.open(bytes(row[0]), c.bound(row[1:])) in (PLAIN[c.name], "s"), c.name


@asynccontextmanager
async def on(url: str) -> AsyncGenerator[Database]:
    database = PoolDatabase(url, connect_timeout_s=5.0)
    await database.open()
    try:
        yield database
    finally:
        await database.close()


def test_a_bytea_column_is_either_sealed_here_or_a_hash(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        found = {f"{t}.{c}" for t, c in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE data_type = 'bytea' "
            "AND table_schema = 'public'").fetchall()}
    names = {c.name for c in SEALED}
    assert names <= found and len(names) == len(SEALED), "a listed column is not a bytea column"
    assert found - names == NOT_SEALED, f"a bytea column nobody classified: is it sealed? then it joins SEALED"


def test_a_pass_seals_every_sealed_column_under_the_current_key_and_a_second_changes_nothing(db_url: str) -> None:
    plant(db_url)
    assert set(PLAIN) == {c.name for c in SEALED}, "a column in SEALED has no planted value"
    for c in SEALED:
        assert bytes(stored(db_url, c)[0][0])[0] == 1

    async def scenario() -> None:
        async with on(db_url) as database:
            first = await reseal.reseal_all(database, TO_NEW)
            assert first == reseal.Tally(resealed=len(SEALED), raced=0, unsealable=0)
            assert await reseal.reseal_all(database, TO_NEW) == reseal.Tally()
    run(scenario())
    assert_all_current(db_url, TO_NEW)


class Dies(Database):
    """A database whose connections stop after `left` uses, as a pod that dies between two batches."""

    def __init__(self, inner: Database, left: int) -> None:
        self._inner, self._left = inner, left

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[Any]:
        if self._left == 0:
            raise DatabaseUnavailable("the pod died")
        self._left -= 1
        async with self._inner.connection() as conn:
            yield conn

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def probe(self) -> Any: ...


class Beaten(Database):
    """A database whose connection runs `before_write` just before the pass writes a row, as another pod's write."""

    def __init__(self, inner: Database, before_write: Callable[[], None]) -> None:
        self._inner, self._before = inner, before_write

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[Any]:
        async with self._inner.connection() as conn:
            yield _Hooked(conn, self._before)

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def probe(self) -> Any: ...


class _Hooked:
    def __init__(self, conn: Any, before: Callable[[], None]) -> None:
        self._conn, self._before = conn, before

    async def execute(self, query: bytes, args: Any = None) -> Any:
        if query.startswith(b"UPDATE"):
            self._before()
        return await self._conn.execute(query, args)


def add_connections(url: str, sealer: Sealer, count: int) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        house = conn.execute("SELECT id FROM households").fetchone()
        assert house is not None
        for n in range(count):
            conn.execute("INSERT INTO connections (household_id, kind, label, base_url, secret) "
                         "VALUES (%s, 'sure', %s, 'https://x.test', %s)",
                         (house[0], f"extra{n}", sealer.seal("s", bound_to(house[0], "sure"))))


def secret_versions(url: str) -> list[int]:
    with psycopg.connect(url, autocommit=True) as conn:
        return sorted(bytes(r[0])[0] for r in conn.execute("SELECT secret FROM connections").fetchall())


def test_a_pass_cut_short_loses_nothing_and_the_next_one_finishes_what_is_left(db_url: str) -> None:
    plant(db_url)
    add_connections(db_url, FROM_OLD, 4)

    async def scenario() -> None:
        async with on(db_url) as database:
            with pytest.raises(DatabaseUnavailable):
                await reseal.reseal_column(Dies(database, 3), TO_NEW, SEALED[0], batch=1)
            assert secret_versions(db_url) == [1, 1, 2, 2, 2]
            rest = await reseal.reseal_all(database, TO_NEW, batch=1)
            assert rest == reseal.Tally(resealed=len(SEALED) + 4 - 3)
    run(scenario())
    assert secret_versions(db_url) == [2] * 5
    assert_all_current(db_url, TO_NEW)


def test_a_row_another_pod_wrote_first_is_left_as_that_pod_wrote_it(db_url: str) -> None:
    plant(db_url)
    mine = Sealer({1: OLD, 2: NEW}, current=2)
    theirs: list[bytes] = []

    def another_pod() -> None:
        if theirs:
            return
        with psycopg.connect(db_url, autocommit=True) as conn:
            row = conn.execute("SELECT household_id FROM connections").fetchone()
            assert row is not None
            theirs.append(mine.seal("written-meanwhile", bound_to(row[0], "sure")))
            conn.execute("UPDATE connections SET secret = %s", (theirs[0],))

    async def scenario() -> None:
        async with on(db_url) as database:
            got = await reseal.reseal_column(Beaten(database, another_pod), mine, SEALED[0])
            assert got == reseal.Tally(raced=1)
    run(scenario())
    with psycopg.connect(db_url, autocommit=True) as conn:
        assert [bytes(r[0]) for r in conn.execute("SELECT secret FROM connections").fetchall()] == theirs


def test_a_value_under_neither_key_is_left_alone_counted_and_logged_by_row_id(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    ids = plant(db_url)
    foreign = Sealer({1: OTHER})
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute("SELECT household_id FROM connections").fetchone()
        assert row is not None
        kept = foreign.seal("no-key-opens-this", bound_to(row[0], "sure"))
        conn.execute("UPDATE connections SET secret = %s", (kept,))
    caplog.set_level(logging.DEBUG)

    async def scenario() -> None:
        async with on(db_url) as database:
            for _ in range(2):
                assert await reseal.reseal_all(database, TO_NEW) in (
                    reseal.Tally(resealed=len(SEALED) - 1, unsealable=1), reseal.Tally(unsealable=1))
    run(scenario())
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute("SELECT secret FROM connections").fetchone()
        assert row is not None and bytes(row[0]) == kept
    text = "\n".join(logs.Logfmt().format(r) for r in caplog.records)
    unsealable = [ln for ln in text.splitlines() if "event=reseal.unsealable" in ln]
    assert len(unsealable) == 2 and all(f"row={ids['connection']}" in ln and "column=connections.secret" in ln
                                        for ln in unsealable)


def test_a_pass_logs_ids_and_counts_and_never_a_value_a_key_or_a_sealed_byte(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    plant(db_url)
    with psycopg.connect(db_url, autocommit=True) as conn:
        row = conn.execute("SELECT household_id FROM connections").fetchone()
        assert row is not None
        conn.execute("UPDATE connections SET access_token = %s",
                     (Sealer({1: OTHER}).seal("no-key-opens-this", bound_to(row[0], "sure")),))
    caplog.set_level(logging.DEBUG)

    async def scenario() -> None:
        async with on(db_url) as database:
            await reseal.reseal_all(database, TO_NEW)
    run(scenario())
    out = blank_ts("\n".join(logs.Logfmt().format(r) for r in caplog.records))
    for event in ("reseal.start", "reseal.batch", "reseal.unsealable", "reseal.finish"):
        assert f"event={event}" in out, f"control: the pass logged no {event}"
    secrets = [*PLAIN.values(), "no-key-opens-this"]
    keys = [text for k in (OLD, NEW, OTHER) for text in (k.hex(), base64.b64encode(k).decode(),
                                                         hashlib.sha256(k).hexdigest(), hashlib.sha256(k).hexdigest()[:12])]
    sealed = [bytes(r[0]).hex() for c in SEALED for r in stored(db_url, c)]
    for needle in (*secrets, *keys, *sealed):
        assert needle not in out
    assert "row=" in out and "resealed=" in out


class Recording(Lease):
    def __init__(self) -> None:
        self.bodies: dict[str, Body] = {}

    async def run(self, name: str, body: Body) -> None:
        self.bodies[name] = body


def started(**settings: str) -> dict[str, Body]:
    lease = Recording()
    services.register(Lease, lease)

    async def start() -> None:
        tasks = [asyncio.ensure_future(c) for c in singletons(Settings(database_url="x", build_version="t", **settings))]
        await asyncio.wait(tasks, timeout=0.05)
        for task in tasks:
            task.cancel()
    asyncio.run(start())
    return lease.bodies


def test_the_pass_is_a_singleton_under_the_lease_reseal_only_while_a_second_key_is_named() -> None:
    key = base64.b64encode(NEW).decode()
    bodies = started(connections_key=f"2:{key}", connections_key_opens=base64.b64encode(OLD).decode())
    body = bodies[reseal.NAME]
    assert isinstance(body, partial) and body.func is reseal.run
    assert reseal.NAME not in started(connections_key=f"2:{key}")
    assert reseal.NAME not in started()


def test_a_second_key_is_refused_without_a_first_or_at_the_same_version() -> None:
    key = base64.b64encode(NEW).decode()
    with pytest.raises(ValueError, match="needs CONNECTIONS_KEY"):
        Settings(database_url="x", build_version="t", connections_key_opens=key)
    with pytest.raises(ValueError, match="same version"):
        sealer_of(key, base64.b64encode(OLD).decode())


def test_the_env_names_both_keys() -> None:
    got = from_env({"DATABASE_URL": "x", "BUILD_VERSION": "t", "CONNECTIONS_KEY": f"2:{base64.b64encode(NEW).decode()}",
                    "CONNECTIONS_KEY_OPENS": f" {base64.b64encode(OLD).decode()} "})
    sealer = sealer_of(got.connections_key, got.connections_key_opens)
    old = Sealer({1: OLD}).seal("kept", b"b")
    assert sealer.current == 2 and sealer.open(old, b"b") == "kept" and sealer.open(sealer.seal("n", b"b"), b"b") == "n"
