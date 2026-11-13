"""Services reached at an address and no key (Wyoming speech-to-text, SearXNG) as connections, on a real database: the
env seeds the first household's row once, by one of several pods at once, and never over a row; the address in force is
the row's, the env's only where there is no row, and neither when both are unset; Wyoming's provider and the web
search follow a row changed in the room with no restart; each kind's check tells a server that answers from one that
does not."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import psycopg
import pytest
from ashley.connections.address_in_force import AddressInForce
from ashley.connections.address_seed import NO_SECRET, Outcome, seed_addresses
from ashley.connections.connections import NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.inference.keyed_providers import KeyedProviders
from ashley.inference.provider_keys import ConnectionProviderKeys
from ashley.inference.wyoming_kind import KIND as WYOMING, NAME as WYOMING_NAME, PROVIDER, check as wyoming_check
from ashley.inference.wyoming_stt import WyomingTranscriber
from ashley.people import admin
from ashley.tools.search_connection import KIND as SEARXNG, ConnectedWebSearch, check as searxng_check
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from search_support import CONFIG, Fake, call, captured
from test_connections_postgres import connections_on

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

STT = "tcp://stt.home.test:10300"
SEARCH = "http://search.home.test:8080"


def first_household(url: str) -> int:
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        assert home == FIRST_HOUSEHOLD
        return admin.add_person(conn, home, "Alana")


def uri(keyed: KeyedProviders) -> str | None:
    found = keyed.current().get(WYOMING_NAME)
    assert found is None or isinstance(found, WyomingTranscriber)
    return None if found is None else found.uri


def test_the_env_seeds_each_row_once_never_over_a_row_and_the_row_then_wins(db_url: str) -> None:
    alana = first_household(db_url)
    wanted = ((WYOMING, STT + "/"), (SEARXNG, SEARCH + "/"))

    async def scenario() -> tuple[list[dict[str, Outcome]], dict[str, Outcome], list[str]]:
        async with connections_on(db_url) as connections:
            first = list(await asyncio.gather(*(seed_addresses(connections, wanted) for _ in range(6))))
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.kind == SEARXNG.name)
            await connections.replace(row.id, FIRST_HOUSEHOLD, alana, "https://edited.test", "x")
            again = await seed_addresses(connections, wanted)
            reading = [await AddressInForce(lambda: connections, kind.name, "http://env.test")() for kind in (WYOMING, SEARXNG)]
            return first, again, reading
    first, again, reading = asyncio.run(scenario())
    assert sorted(o[SEARXNG.name] for o in first) == ["kept"] * 5 + ["seeded"]
    assert sorted(o[WYOMING_NAME] for o in first) == ["kept"] * 5 + ["seeded"]
    assert again == {WYOMING_NAME: "kept", SEARXNG.name: "kept"}
    assert reading == [STT.removesuffix("/"), "https://edited.test"], "the seeded address is stored without a slash; the edit wins"
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind IN ('wyoming', 'searxng')") == 2


def test_unset_seeds_nothing_and_a_bad_address_or_missing_key_writes_nothing() -> None:
    assert asyncio.run(seed_addresses(NullConnections(), ((WYOMING, ""), (SEARXNG, "")))) == {}
    assert asyncio.run(seed_addresses(NullConnections(), ((WYOMING, "http://stt"),))) == {WYOMING_NAME: "bad_address"}
    assert asyncio.run(seed_addresses(NullConnections(), ((SEARXNG, SEARCH),))) == {SEARXNG.name: "no_key"}


def test_the_address_in_force_is_the_row_s_then_the_env_s_then_none(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> list[str]:
        async with connections_on(db_url) as connections:
            seen = [await AddressInForce(lambda: connections, SEARXNG.name, "")(),
                    await AddressInForce(lambda: connections, SEARXNG.name, SEARCH)()]
            await connections.add(FIRST_HOUSEHOLD, SEARXNG.name, "", "https://row.test", NO_SECRET, alana)
            seen.append(await AddressInForce(lambda: connections, SEARXNG.name, SEARCH)())
            seen.append(await AddressInForce(lambda: connections, WYOMING_NAME, "")())
            return seen
    assert asyncio.run(scenario()) == ["", SEARCH, "https://row.test", ""]
    assert asyncio.run(AddressInForce(NullConnections, SEARXNG.name, SEARCH)()) == SEARCH, "no key: the env answers"


def test_wyoming_follows_the_row_with_no_restart_and_unset_leaves_it_unwired(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> list[str | None]:
        async with connections_on(db_url) as connections:
            def keyed(env: str) -> KeyedProviders:
                keys = ConnectionProviderKeys(lambda: connections, (), {}, addressed=(WYOMING_NAME,),
                                              addressed_env={WYOMING_NAME: env})
                return KeyedProviders([], keys, {}, refresh_s=0, addressed=(PROVIDER,), addressed_env={WYOMING_NAME: env})
            off, on = keyed(""), keyed(STT)
            seen = [uri(off), uri(on)]
            await off.refresh()
            await on.refresh()
            seen += [uri(off), uri(on)]
            added = await connections.add(FIRST_HOUSEHOLD, WYOMING_NAME, "", "tcp://row.test:1", NO_SECRET, alana)
            await off.refresh()
            await on.refresh()
            seen += [uri(off), uri(on)]
            await connections.replace(added.id, FIRST_HOUSEHOLD, alana, "tcp://edited.test:2", NO_SECRET)
            await on.refresh()
            seen.append(uri(on))
            await connections.remove(added.id, FIRST_HOUSEHOLD, alana)
            await on.refresh()
            return [*seen, uri(on)]
    assert asyncio.run(scenario()) == [None, STT, None, STT, "tcp://row.test:1", "tcp://row.test:1",
                                       "tcp://edited.test:2", STT]


def test_the_checker_for_wyoming_routes_is_built_with_no_address_set() -> None:
    keyed = KeyedProviders([], ConnectionProviderKeys(NullConnections, (), {}), {}, addressed=(PROVIDER,))
    assert WYOMING_NAME in keyed.names() and WYOMING_NAME in keyed.checkers() and keyed.current() == {}


def test_the_web_search_uses_the_address_in_force_on_each_call_and_is_not_offered_without_one(db_url: str) -> None:
    alana = first_household(db_url)
    fake = Fake(lambda request: httpx2.Response(200, json=captured("searxng")))

    async def scenario() -> tuple[list[str], list[str], str]:
        async with connections_on(db_url) as connections:
            search = ConnectedWebSearch(fake.client(), CONFIG, AddressInForce(lambda: connections, SEARXNG.name, ""))
            before = [s.name for s in (await search.catalogue()).specs]
            refused, _ = await search.numbered(call("search_web", query="x"), 1)
            added = await connections.add(FIRST_HOUSEHOLD, SEARXNG.name, "", "https://one.test", NO_SECRET, alana)
            offered = [s.name for s in (await search.catalogue()).specs]
            await search.numbered(call("search_web", query="x"), 1)
            await connections.replace(added.id, FIRST_HOUSEHOLD, alana, "https://two.test", NO_SECRET)
            await search.numbered(call("search_web", query="x"), 1)
            return before, offered, refused.content
    before, offered, refused = asyncio.run(scenario())
    assert before == [] and offered == ["search_web"] and "not set up" in refused
    assert [r.url.host for r in fake.requests] == ["one.test", "two.test"]


@asynccontextmanager
async def serving(reply: bytes) -> AsyncGenerator[str]:
    """A server on a free port that answers the first line it reads with `reply` and closes; the address it is at."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(reply)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield str(server.sockets[0].getsockname()[1])
    finally:
        server.close()
        await server.wait_closed()


def test_wyoming_s_check_tells_a_wyoming_server_from_other_things() -> None:
    async def scenario() -> list[object]:
        seen: list[object] = []
        async with serving(b'{"type": "info", "data": {}}\n') as port:
            seen.append(await wyoming_check(f"tcp://127.0.0.1:{port}", NO_SECRET, 1))
        async with serving(b"HTTP/1.1 200 OK\r\n\r\n") as port:
            seen.append(await wyoming_check(f"tcp://127.0.0.1:{port}", NO_SECRET, 1))
        async with serving(b'{"type": "pong"}\n') as port:
            seen.append(await wyoming_check(f"tcp://127.0.0.1:{port}", NO_SECRET, 1))
        seen.append(await wyoming_check("tcp://127.0.0.1:1", NO_SECRET, 1))
        return seen
    assert asyncio.run(scenario()) == [None, "wrong_service", "wrong_service", "unreachable"]


def test_searxng_s_check_wants_json_from_its_search() -> None:
    async def scenario() -> list[object]:
        seen: list[object] = []
        async with serving(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 17\r\n\r\n{"results": []}\n ') as port:
            seen.append(await searxng_check(f"http://127.0.0.1:{port}", NO_SECRET, 1))
        async with serving(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n") as port:
            seen.append(await searxng_check(f"http://127.0.0.1:{port}", NO_SECRET, 1))
        seen.append(await searxng_check("http://127.0.0.1:1", NO_SECRET, 1))
        return seen
    assert asyncio.run(scenario()) == [None, "key_refused", "unreachable"]


def test_both_kinds_are_the_first_household_s_alone() -> None:
    assert WYOMING.deployment and SEARXNG.deployment and WYOMING.schemes == {"tcp"} and "search" in SEARXNG.ports
