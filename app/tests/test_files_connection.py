"""The object store as the deployment's connection, on a real database: the env seeds the first household's row once, by
one of several pods at once, and never over a row; the store in force is the row's, the env's only where there is no row,
and none when both are absent; a row changed in the room is followed with no restart; a row that cannot be read or
opened leaves what was wired; the kind's address takes several endpoints and its check tells a bucket that answers
from one that does not; the sweep and repair idle while no store is connected."""

import asyncio
from collections.abc import Callable

import httpx2
import psycopg
import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable, NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.files import config as files_config, repair, sweep
from ashley.files.connected_store import REFRESH_S, ConnectedStore
from ashley.files.mirror import MirroredStore
from ashley.files.s3 import S3Store
from ashley.files.store import StoreUnavailable
from ashley.files.store_kind import KIND, NAME, Keys, check, keys_of
from ashley.files.store_seed import Outcome, seed_store
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from files_support import FakeS3, sync
from test_address_connections import serving
from test_connections_postgres import connections_on

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

ENV = Keys("http://env.test:1", "ashley", "env-access", "env-secret")
ROW = Keys("http://row.test:1,http://row2.test:1", "ashley", "row-access", "row-secret")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class NoCandidates:
    async def load(self) -> frozenset[str]:
        raise AssertionError("nothing to judge")

    async def save(self, keys: frozenset[str]) -> None:
        raise AssertionError("nothing to keep")


class Unreadable(NullConnections):
    def can_open(self) -> bool:
        return True

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[()]:
        raise ConnectionsUnavailable()


def first_household(url: str) -> int:
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        assert home == FIRST_HOUSEHOLD
        return admin.add_person(conn, home, "Alana")


def stored(env: Keys | None, connections: Callable[[], Connections], clock: Clock) -> ConnectedStore:
    return ConnectedStore(connections, env, httpx2.AsyncClient(transport=FakeS3().transport()), clock)


def test_the_env_seeds_one_row_once_never_over_a_row_and_a_bad_address_or_missing_key_writes_nothing(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> tuple[list[Outcome], Outcome, Keys | None]:
        async with connections_on(db_url) as connections:
            first = list(await asyncio.gather(*(seed_store(connections, ENV) for _ in range(6))))
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.kind == NAME)
            await connections.replace(row.id, FIRST_HOUSEHOLD, alana, ROW.endpoints, ROW.secret())
            again = await seed_store(connections, ENV)
            opened = await connections.opened(row.id, FIRST_HOUSEHOLD)
            assert opened is not None
            return first, again, keys_of(opened.connection.base_url, opened.secret)
    first, again, in_force = asyncio.run(scenario())
    assert sorted(first) == ["kept"] * 5 + ["seeded"] and again == "kept"
    assert in_force == ROW, "the edit wins over a later seed"
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'files'") == 1
    assert asyncio.run(seed_store(NullConnections(), ENV)) == "no_key"
    assert asyncio.run(seed_store(NullConnections(), Keys("ftp://nas", "b", "a", "s"))) == "bad_address"


def test_the_store_in_force_is_the_row_s_then_the_env_s_then_none_and_follows_the_room(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> list[object]:
        clock = Clock()
        async with connections_on(db_url) as connections:
            bare, with_env = stored(None, lambda: connections, clock), stored(ENV, lambda: connections, clock)
            seen: list[object] = []
            try:
                await bare.current()
            except StoreUnavailable:
                seen.append("none")
            seen.append(type(await with_env.current()))
            added = await connections.add(FIRST_HOUSEHOLD, NAME, "", ROW.endpoints, ROW.secret(), alana)
            seen.append(type(await with_env.current()))
            clock.now += REFRESH_S
            seen += [type(await with_env.current()), type(await bare.current())]
            await connections.replace(added.id, FIRST_HOUSEHOLD, alana, "http://one.test:1", ROW.secret())
            clock.now += REFRESH_S
            seen.append(type(await with_env.current()))
            await connections.remove(added.id, FIRST_HOUSEHOLD, alana)
            clock.now += REFRESH_S
            seen.append(type(await with_env.current()))
            try:
                await bare.current()
            except StoreUnavailable:
                seen.append("none")
            return seen
    assert asyncio.run(scenario()) == ["none", S3Store, S3Store, MirroredStore, MirroredStore, S3Store, S3Store, "none"]


@sync
async def test_a_row_is_not_read_again_within_the_refresh_bound() -> None:
    clock = Clock()
    reads: list[int] = []

    class Counting(Unreadable):
        async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[()]:
            reads.append(1)
            raise ConnectionsUnavailable()
    store = stored(ENV, Counting, clock)
    first = await store.current()
    clock.now += REFRESH_S - 1
    assert await store.current() is first and reads == [1]
    clock.now += 1
    assert await store.current() is first and reads == [1, 1], "an unreadable row leaves the env's store, tried again after the bound"


@sync
async def test_the_env_s_store_answers_with_no_connections_key_and_calls_reach_the_store() -> None:
    fake = FakeS3()
    store = ConnectedStore(NullConnections, ENV, httpx2.AsyncClient(transport=fake.transport()), Clock())
    assert await store.put("bench/1/k", b"x") == 1
    assert await store.get("bench/1/k") == b"x" and fake.objects == {"bench/1/k": b"x"}
    assert await store.keys("bench/") == frozenset({"bench/1/k"})
    await store.delete("bench/1/k")
    assert fake.objects == {}


def test_a_row_that_does_not_open_as_keys_leaves_the_env_s_store(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> type:
        async with connections_on(db_url) as connections:
            await connections.add(FIRST_HOUSEHOLD, NAME, "", "http://row.test:1,http://row2.test:1", "not json", alana)
            return type(await stored(ENV, lambda: connections, Clock()).current())
    assert asyncio.run(scenario()) is S3Store


def test_the_kind_takes_several_endpoints_in_order_and_refuses_any_bad_one() -> None:
    assert KIND.base_url("http://a.test:1/, https://b.test") == "http://a.test:1,https://b.test"
    assert KIND.base_url("http://a.test:1,ftp://b.test") is None
    assert KIND.base_url("http://a.test:1,") is None
    assert KIND.deployment and KIND.addresses and "files" in KIND.ports


def test_a_secret_is_the_bucket_and_both_keys_or_none() -> None:
    assert keys_of(ROW.endpoints, ROW.secret()) == ROW
    for bad in ("", "[]", "{}", '{"bucket": "b", "access_key": "a"}', '{"bucket": "b", "access_key": "a", "secret_key": 1}'):
        assert keys_of(ROW.endpoints, bad) is None
    assert "row-secret" not in repr(ROW)


@sync
async def test_the_check_tells_a_bucket_that_answers_from_one_that_does_not() -> None:
    secret = ENV.secret()
    seen: list[object] = []
    for status in (b"200 OK", b"403 Forbidden", b"404 Not Found", b"500 Oops"):
        async with serving(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n\r\n") as port:
            seen.append(await check(f"http://127.0.0.1:{port}", secret, 1))
    seen.append(await check("http://127.0.0.1:1", secret, 1))
    seen.append(await check("http://127.0.0.1:1", "not json", 1))
    assert seen == [None, "key_refused", "wrong_service", "unreachable", "unreachable", "key_refused"]


@sync
async def test_the_check_asks_every_endpoint() -> None:
    async with serving(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n") as up:
        assert await check(f"http://127.0.0.1:{up},http://127.0.0.1:1", ENV.secret(), 1) == "unreachable"


@sync
async def test_the_sweep_and_repair_idle_while_no_store_is_connected_and_repair_waits_for_two_sites() -> None:
    none = stored(None, NullConnections, Clock())

    async def referenced() -> frozenset[str]:
        raise AssertionError("nothing to judge")
    assert await sweep.run_once(none, referenced, NoCandidates(), files_config.load()) is None
    assert await repair.run_once(none, ("bench/",)) == 0
    assert await repair.run_once(stored(ENV, NullConnections, Clock()), ("bench/",)) == 0
