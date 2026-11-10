"""Who holds a connection and what it reaches, on a real database: a hand-over seals the secret again bound to the
household and flags every resource shared; a take-back is the adder's alone and flags them kept; a move that would
collide on label or pass `most` writes nothing; the resource gate offers a kept resource only where the reply reaches
its owner alone and a shared one to the household, changes only on a channel that names a speaker; listing what a
service names keeps a flag, renames, drops what vanished, and sharing is the owner's."""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg
import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable, LabelTaken, NotAdder, TooMany
from ashley.connections.model import Connection, Holder, Listed
from ashley.connections.postgres import PostgresConnections
from ashley.connections.resources import ConnectionResources, HeldByHousehold, Use
from ashley.connections.resources_postgres import PostgresConnectionResources
from ashley.connections.sealing import VERSION, Sealer, Unsealable, bound_to
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

KEY = os.urandom(32)
SEALER = Sealer({VERSION: KEY})
BOX = Listed("alana@gmail.test", "mailbox", "alana@gmail.test")


@dataclass(frozen=True)
class Home:
    household: int
    alana: int
    sam: int
    kim: int
    other: int


@asynccontextmanager
async def stores(url: str) -> AsyncGenerator[tuple[Connections, ConnectionResources]]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresConnections(database, SEALER), PostgresConnectionResources(database)
    finally:
        await database.close()


@pytest.fixture
def home(db_url: str) -> Home:
    with psycopg.connect(db_url) as conn:
        one, two = admin.add_household(conn, "one", "UTC"), admin.add_household(conn, "two", "UTC")
        return Home(one, admin.add_person(conn, one, "Alana"), admin.add_person(conn, one, "Sam"),
                    admin.add_person(conn, two, "Kim"), two)


async def google(connections: Connections, resources: ConnectionResources, home: Home, label: str = "",
                 holder: Holder | None = None, who: int | None = None) -> Connection:
    made = await connections.add(home.household, "google", label, "https://www.googleapis.com", "refresh-token",
                                 who or home.alana, holder)
    await resources.listed(made.id, home.household, [BOX])
    return made


def flags(url: str, connection: int) -> list[bool]:
    with psycopg.connect(url) as conn:
        return [bool(r[0]) for r in conn.execute("SELECT shared FROM connection_resources WHERE connection_id = %s",
                                                 (connection,)).fetchall()]


def test_a_hand_over_reseals_to_the_household_and_shares_every_resource(db_url: str, home: Home) -> None:
    async def scenario() -> int:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            assert flags(db_url, made.id) == [False]
            moved = await connections.move(made.id, home.household, home.alana, "household")
            assert moved is not None and moved.person_id is None
            opened = await connections.opened(made.id, home.household, home.sam)
            assert opened is not None and opened.secret == "refresh-token"
            return made.id

    connection = asyncio.run(scenario())
    assert flags(db_url, connection) == [True]
    sealed = bytes(scalar(db_url, "SELECT secret FROM connections WHERE id = %s", (connection,)))
    SEALER.open(sealed, bound_to(home.household, "google", None))
    with pytest.raises(Unsealable):
        SEALER.open(sealed, bound_to(home.household, "google", home.alana))
    assert scalar(db_url, "SELECT secret_version FROM connections WHERE id = %s", (connection,)) == 2


def test_a_take_back_is_the_adders_alone_and_keeps_every_resource_again(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            await connections.move(made.id, home.household, home.alana, "household")
            with pytest.raises(NotAdder):
                await connections.move(made.id, home.household, home.sam, "person")
            assert flags(db_url, made.id) == [True]
            back = await connections.move(made.id, home.household, home.alana, "person")
            assert back is not None and back.person_id == home.alana
            assert await connections.opened(made.id, home.household, home.sam) is None
            opened = await connections.opened(made.id, home.household, home.alana)
            assert opened is not None and opened.secret == "refresh-token"
            assert flags(db_url, made.id) == [False]

    asyncio.run(scenario())


def test_a_move_to_the_holder_it_has_changes_nothing_and_a_stranger_cannot_move_it(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            same = await connections.move(made.id, home.household, home.alana, "person")
            assert same == made
            assert await connections.move(made.id, home.household, home.sam, "household") is None
            assert await connections.move(made.id, home.other, home.kim, "household") is None

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT secret_version FROM connections") == 1


def test_a_move_onto_a_label_or_past_most_writes_nothing(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            await google(connections, resources, home, "main", "household", home.sam)
            same = await google(connections, resources, home, "main")
            with pytest.raises(LabelTaken):
                await connections.move(same.id, home.household, home.alana, "household")
            renamed = await connections.relabel(same.id, home.household, home.alana, "mine")
            assert renamed is not None
            with pytest.raises(TooMany):
                await connections.move(same.id, home.household, home.alana, "household")
            assert flags(db_url, same.id) == [False]

    asyncio.run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE person_id IS NULL") == 1


def test_a_kind_is_held_only_by_who_it_allows(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, _):
            with pytest.raises(ValueError):
                await connections.add(home.household, "gitlab", "", "https://git.test", "t", home.alana, "household")
            with pytest.raises(ValueError):
                await connections.add(home.household, "sure", "", "https://money.test", "t", home.alana, "person")
            made = await connections.add(home.household, "gitlab", "", "https://git.test", "t", home.alana)
            with pytest.raises(ValueError):
                await connections.move(made.id, home.household, home.alana, "household")

    asyncio.run(scenario())


def use(home: Home, who: int | None, alone: bool) -> Use:
    return Use(home.household, who, alone)


def test_a_kept_resource_is_usable_only_where_the_reply_reaches_its_owner_alone(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            for changing in (False, True):
                got = await resources.usable(use(home, home.alana, True), changing)
                assert [u.connection.id for u in got] == [made.id] and got[0].opens_for == home.alana
                assert await resources.usable(use(home, home.alana, False), changing) == ()
                assert await resources.usable(use(home, home.sam, True), changing) == ()
                assert await resources.usable(use(home, None, True), changing) == ()
                assert await resources.usable(Use(home.other, home.kim, True), changing) == ()

    asyncio.run(scenario())


def test_a_shared_resource_is_read_by_any_turn_of_the_household_and_changed_where_a_member_speaks(
        db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            assert await resources.share(made.id, home.household, home.alana, BOX.ref, True) is not None
            for who, alone in ((home.sam, False), (home.alana, False), (None, False), (home.sam, True)):
                got = await resources.usable(use(home, who, alone), False)
                assert [u.connection.id for u in got] == [made.id] and got[0].opens_for == home.alana
            assert await resources.usable(use(home, None, False), True) == ()
            assert len(await resources.usable(use(home, home.sam, False), True)) == 1
            assert await resources.usable(Use(home.other, home.kim, True), False) == ()

    asyncio.run(scenario())


def test_a_household_connections_resource_is_shared_whoever_listed_it(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home, holder="household")
            assert flags(db_url, made.id) == [True]
            got = await resources.usable(use(home, None, False), False)
            assert [(u.connection.id, u.opens_for) for u in got] == [(made.id, None)]
            with pytest.raises(HeldByHousehold):
                await resources.share(made.id, home.household, home.sam, BOX.ref, False)
            kept = await resources.share(made.id, home.household, home.sam, BOX.ref, True)
            assert kept is not None and kept.shared

    asyncio.run(scenario())


def test_only_the_owner_shares_a_kept_resource_and_it_can_be_kept_again(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            assert await resources.share(made.id, home.household, home.sam, BOX.ref, True) is None
            assert await resources.share(made.id, home.household, home.alana, "nobody@gmail.test", True) is None
            assert flags(db_url, made.id) == [False]
            shared = await resources.share(made.id, home.household, home.alana, BOX.ref, True)
            assert shared is not None and shared.shared
            kept = await resources.share(made.id, home.household, home.alana, BOX.ref, False)
            assert kept is not None and not kept.shared

    asyncio.run(scenario())


def test_listing_keeps_a_flag_renames_and_drops_what_the_service_no_longer_names(db_url: str, home: Home) -> None:
    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await google(connections, resources, home)
            await resources.share(made.id, home.household, home.alana, BOX.ref, True)
            other = Listed("alana@work.test", "mailbox", "work")
            listed = await resources.listed(made.id, home.household, [Listed(BOX.ref, "mailbox", "personal"), other])
            assert [(r.ref, r.name, r.shared) for r in listed] == [(BOX.ref, "personal", True), (other.ref, "work", False)]
            only = await resources.listed(made.id, home.household, [other])
            assert [r.ref for r in only] == [other.ref]
            assert await resources.listed(made.id, home.other, [BOX]) == ()
            assert dict(await resources.of_household(home.household, home.alana)).keys() == {made.id}
            assert await resources.of_household(home.household, home.sam) == {}

    asyncio.run(scenario())


def test_the_unwired_gate_is_unavailable_and_never_offers_a_resource() -> None:
    with pytest.raises(ConnectionsUnavailable):
        asyncio.run(ConnectionResources.null().usable(Use(1, 1, True), False))


def test_a_turn_that_is_not_the_owners_reaches_only_the_shared_resource_of_a_connection_and_never_its_kept_one(
        db_url: str, home: Home) -> None:
    kept = Listed("kept@gmail.test", "mailbox", "kept@gmail.test")

    async def scenario() -> None:
        async with stores(db_url) as (connections, resources):
            made = await connections.add(home.household, "google", "", "https://www.googleapis.com", "refresh-token",
                                         home.alana, None)
            await resources.listed(made.id, home.household, [BOX, kept])
            assert await resources.share(made.id, home.household, home.alana, BOX.ref, True) is not None
            others = ((home.sam, True), (home.sam, False), (None, False), (home.alana, False))
            for who, alone in others:
                for changing in (False, True):
                    got = await resources.usable(use(home, who, alone), changing)
                    seen = {(u.connection.id, u.resource.ref, u.opens_for) for u in got}
                    assert seen <= {(made.id, BOX.ref, home.alana)}, (who, alone, changing, seen)
            assert {u.resource.ref for u in await resources.usable(use(home, home.alana, True), True)} == {BOX.ref, kept.ref}

    asyncio.run(scenario())
