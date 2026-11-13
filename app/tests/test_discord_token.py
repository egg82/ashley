"""The Discord bot's token as a connection, on a real database: the env seeds the first household's row once, by one of
several pods at once, and never over an edited row; the bot reads the row's token and the env's only where there is no
row; she is off with neither; the session follows a token replaced or removed in the room and is left alone when the rows
cannot be read; the kind's check tells Discord's answer from a refusal."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import psycopg
import pytest
from ashley.channels.discord.following import follow
from ashley.channels.discord.token_in_force import TokenInForce
from ashley.channels.discord.token_kind import KIND, check
from ashley.channels.discord.token_seed import Outcome, seed_token
from ashley.connections.connections import ConnectionsUnavailable, NullConnections
from ashley.connections.kinds import FIRST_HOUSEHOLD
from ashley.people import admin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from test_connections_postgres import connections_on

pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

ENV = "env-token-0001"
ROW = "row-token-0002"


def first_household(url: str) -> int:
    with psycopg.connect(url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        assert home == FIRST_HOUSEHOLD
        return admin.add_person(conn, home, "Alana")


def test_the_env_seeds_the_row_once_never_over_an_edit_and_the_row_then_wins(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> tuple[list[Outcome], Outcome, list[str]]:
        async with connections_on(db_url) as connections:
            first = list(await asyncio.gather(*(seed_token(connections, ENV) for _ in range(6))))
            before = await TokenInForce(lambda: connections, "")()
            row = next(c for c in await connections.of_household(FIRST_HOUSEHOLD) if c.kind == KIND.name)
            await connections.replace(row.id, FIRST_HOUSEHOLD, alana, row.base_url, ROW)
            again = await seed_token(connections, ENV)
            return first, again, [before, await TokenInForce(lambda: connections, "other-env")()]
    first, again, read = asyncio.run(scenario())
    assert sorted(first) == ["kept"] * 5 + ["seeded"]
    assert again == "kept"
    assert read == [ENV, ROW], "the seeded token is the env's; the edit wins over a seed and over the env"
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'discord'") == 1


def test_without_the_apps_key_nothing_is_written_and_the_env_answers() -> None:
    assert asyncio.run(seed_token(NullConnections(), ENV)) == "no_key"
    assert asyncio.run(TokenInForce(NullConnections, ENV)()) == ENV


def test_the_token_in_force_is_the_row_s_then_the_env_s_then_none(db_url: str) -> None:
    alana = first_household(db_url)

    async def scenario() -> list[str]:
        async with connections_on(db_url) as connections:
            seen = [await TokenInForce(lambda: connections, "")(), await TokenInForce(lambda: connections, ENV)()]
            added = await connections.add(FIRST_HOUSEHOLD, KIND.name, "", str(KIND.fixed_address), ROW, alana)
            seen.append(await TokenInForce(lambda: connections, ENV)())
            await connections.remove(added.id, FIRST_HOUSEHOLD, None)
            seen.append(await TokenInForce(lambda: connections, ENV)())
            return seen
    assert asyncio.run(scenario()) == ["", ENV, ROW, ENV]


class Session:
    """Stands in for the bot's session: records the tokens it was started with and which were closed."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.closed: list[str] = []

    async def __call__(self, token: str) -> None:
        self.started.append(token)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.closed.append(token)
            raise


class Reads:
    """A token read that answers what the test last set, or raises ConnectionsUnavailable."""

    def __init__(self) -> None:
        self.token: str | Exception = ""

    async def __call__(self) -> str:
        if isinstance(self.token, Exception):
            raise self.token
        return self.token


async def settled(condition: Callable[[], object]) -> None:
    async with asyncio.timeout(1.0):
        while not condition():
            await asyncio.sleep(0.005)


def test_with_no_token_she_stays_off_and_with_one_she_starts() -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        reads, session = Reads(), Session()
        body = asyncio.create_task(follow(reads, session, 0.005))
        await asyncio.sleep(0.05)
        idle = list(session.started)
        reads.token = ROW
        await settled(lambda: session.started)
        body.cancel()
        await asyncio.gather(body, return_exceptions=True)
        return idle, session.closed
    idle, closed = asyncio.run(scenario())
    assert idle == [], "no token: no session"
    assert closed == [ROW], "cancelling the body closes the session"


def test_a_replaced_or_removed_token_closes_the_session_and_a_new_one_follows() -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        reads, session = Reads(), Session()
        reads.token = ENV
        body = asyncio.create_task(follow(reads, session, 0.005))
        await settled(lambda: session.started == [ENV])
        reads.token = ROW
        await settled(lambda: session.started == [ENV, ROW])
        reads.token = ""
        await settled(lambda: session.closed == [ENV, ROW])
        await asyncio.sleep(0.05)
        body.cancel()
        await asyncio.gather(body, return_exceptions=True)
        return session.started, session.closed
    started, closed = asyncio.run(scenario())
    assert started == [ENV, ROW], "removed: closed, and nothing started after"
    assert closed == [ENV, ROW]


def test_rows_that_cannot_be_read_leave_the_running_session_alone() -> None:
    async def scenario() -> tuple[list[str], list[str]]:
        reads, session = Reads(), Session()
        reads.token = ENV
        body = asyncio.create_task(follow(reads, session, 0.005))
        await settled(lambda: session.started)
        reads.token = ConnectionsUnavailable("down")
        await asyncio.sleep(0.05)
        live = list(session.closed)
        body.cancel()
        await asyncio.gather(body, return_exceptions=True)
        return session.started, live
    started, closed_while_down = asyncio.run(scenario())
    assert started == [ENV] and closed_while_down == []


def test_a_session_that_ends_ends_the_body_so_the_lease_campaigns_again() -> None:
    async def ends(token: str) -> None:
        return None

    async def scenario() -> None:
        reads = Reads()
        reads.token = ENV
        async with asyncio.timeout(1.0):
            await follow(reads, ends, 0.005)
    asyncio.run(scenario())


@asynccontextmanager
async def discord_standing_in(reply: bytes) -> AsyncGenerator[tuple[str, list[bytes]]]:
    """A server on a free port that answers the first request with `reply`, keeping the request's head."""
    heads: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        heads.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(reply)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", heads
    finally:
        server.close()
        await server.wait_closed()


USER = b'{"id": "1", "username": "ashley", "bot": true}'


def json_reply(status: str, body: bytes) -> bytes:
    return (f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body


def test_the_check_reads_the_bot_s_user_with_the_token_and_tells_a_refusal() -> None:
    async def scenario() -> tuple[list[object], bytes]:
        seen: list[object] = []
        async with discord_standing_in(json_reply("200 OK", USER)) as (base, heads):
            seen.append(await check(base, ROW, 1))
            sent = heads[0]
        async with discord_standing_in(json_reply("401 Unauthorized", b'{"message": "401: Unauthorized"}')) as (base, _):
            seen.append(await check(base, "wrong", 1))
        async with discord_standing_in(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n<html>") as (base, _):
            seen.append(await check(base, ROW, 1))
        seen.append(await check("http://127.0.0.1:1", ROW, 1))
        return seen, sent
    seen, sent = asyncio.run(scenario())
    assert seen == [None, "key_refused", "wrong_service", "unreachable"]
    assert sent.startswith(b"GET /v10/users/@me ") and f"Bot {ROW}".encode().lower() in sent.lower()


def test_the_kind_is_the_first_household_s_alone_at_discord_s_address() -> None:
    assert KIND.deployment and KIND.fixed_address == "https://discord.com/api" and KIND.ports == {"chat"}
