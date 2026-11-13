"""Fakes at the seams the Discord adapter owns, for the blind contract tests: the open session (`Discord`) and the way
to open one (`Connect`), the claim store (`Seen`), People and Devices behind the locator, and a stub for `respond`.
Nothing here imports the library, and the Postgres store only inside `seen_store`; times are fixed so catch-up windows are arithmetic."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module

import hashlib

import psycopg
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.client import Discord, DiscordFailed
from ashley.channels.discord.config import Config
from ashley.channels.discord.message import Message
from ashley.channels.discord.seen import Seen, SeenUnavailable
from ashley.channels.model import Device, DiscordServer, Inbound, Listed, Outbound, Satellite
from ashley.db.pool import PoolDatabase
from ashley.people.model import Account, Household, Person
from ashley.people.people import People

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
EPOCH_MS = 1_420_070_400_000
ME = 4242
GUILD = 900
CHANNEL = 1001            # the household server's home channel
SIDE_CHANNEL = 1003       # another channel in the same server
OTHER_GUILD = 901         # a second household's server ...
OTHER_CHANNEL = 1002      # ... and its home channel
STRANGER_GUILD = 777      # a server that is no device
DM_CHANNEL = 2001
ALANA_ID = 555             # Alana's Discord user id, mapped to ALANA
GUEST_ID = 556            # a Discord user nobody mapped
ALANA = Person(5, 1, "Alana")
FAMILY = Device(7, 1, "family room", "den", "household", "text", "chat")
SECRET = "zqx-plant-4b1d9c7e"   # message content that must never reach a log line


def snowflake(at: datetime, sequence: int = 0) -> int:
    """A Discord snowflake made at `at` (millisecond resolution), `sequence` in its low 22 bits."""
    return ((int(at.timestamp() * 1000) - EPOCH_MS) << 22) | sequence


def message(**changes: object) -> Message:
    """A message that mentions her in the household channel, from Alana, made at NOW; `changes` replace fields."""
    base = Message(id=snowflake(NOW), channel_id=CHANNEL, guild_id=GUILD, author_id=ALANA_ID, author_is_bot=False,
                   content="hello", mentions_me=True, replies_to_me=False)
    return replace(base, **changes)


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


def failed(status: int = 500) -> DiscordFailed:
    error = DiscordFailed(status)
    error.status = status
    return error


@dataclass
class Sent:
    channel_id: int
    text: str
    reply_to: int | None


class FakeDiscord(Discord):
    """One open session. `incoming` feeds `messages()` (None ends it); `backlog` is what `history` can return;
    `send_errors` maps a send's 0-based call index to the failure it raises."""

    def __init__(self, me: int = ME) -> None:
        self.me = me
        self.incoming: asyncio.Queue[Message | None] = asyncio.Queue()
        self.backlog: dict[int, list[Message]] = {}
        self.history_errors: dict[int, DiscordFailed] = {}
        self.send_errors: dict[int, DiscordFailed] = {}
        self.typing_error: DiscordFailed | None = None
        self.unfiltered = False   # history ignores `after`, as a sloppy server might
        self.sends: list[Sent] = []
        self.typed: list[int] = []
        self.asked: list[tuple[int, int, int]] = []

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            item = await self.incoming.get()
            if item is None:
                return
            yield item

    async def send(self, channel_id: int, text: str, reply_to: int | None) -> None:
        index = len(self.sends)
        self.sends.append(Sent(channel_id, text, reply_to))
        if index in self.send_errors:
            raise self.send_errors[index]

    async def typing(self, channel_id: int) -> None:
        self.typed.append(channel_id)
        if self.typing_error is not None:
            raise self.typing_error

    async def history(self, channel_id: int, after: int, limit: int = 50) -> list[Message]:
        self.asked.append((channel_id, after, limit))
        if channel_id in self.history_errors:
            raise self.history_errors[channel_id]
        found = self.backlog.get(channel_id, [])
        return (found if self.unfiltered else [m for m in found if m.id > after])[:limit]

    def texts(self) -> list[str]:
        return [s.text for s in self.sends]


class FakeConnect:
    """`Connect`: opening counts, and so does leaving, cancellation included."""

    def __init__(self, discord: FakeDiscord) -> None:
        self.discord = discord
        self.entered = 0
        self.exited = 0

    def __call__(self) -> AbstractAsyncContextManager[Discord]:
        return self._session()

    @asynccontextmanager
    async def _session(self) -> AsyncGenerator[Discord]:
        self.entered += 1
        try:
            yield self.discord
        finally:
            self.exited += 1


class FakeSeen(Seen):
    """An in-memory claim store: id -> (channel, when claimed); `settled`, the claims settled."""

    def __init__(self, clock: Callable[[], datetime] = lambda: NOW) -> None:
        self.claims: dict[int, tuple[int, datetime]] = {}
        self.clock = clock
        self.unavailable = False
        self.last_asked: list[datetime] = []
        self.pruned: list[datetime] = []
        self.settled: set[int] = set()

    def preclaim(self, message_id: int, channel_id: int, at: datetime, settled: bool = True) -> None:
        self.claims[message_id] = (channel_id, at)
        if settled:
            self.settled.add(message_id)

    async def claim(self, message_id: int, channel_id: int) -> bool:
        if self.unavailable:
            raise SeenUnavailable("down")
        if message_id in self.claims:
            return False
        self.claims[message_id] = (channel_id, self.clock())
        return True

    async def last(self, since: datetime) -> dict[int, int]:
        if self.unavailable:
            raise SeenUnavailable("down")
        self.last_asked.append(since)
        found: dict[int, int] = {}
        for message_id, (channel_id, at) in self.claims.items():
            if at >= since:
                found[channel_id] = max(found.get(channel_id, 0), message_id)
        return found

    async def prune(self, before: datetime) -> int:
        if self.unavailable:
            raise SeenUnavailable("down")
        self.pruned.append(before)
        return 0

    async def settle(self, message_id: int) -> None:
        if self.unavailable:
            raise SeenUnavailable("down")
        if message_id in self.claims:
            self.settled.add(message_id)

    async def unsettled(self, since: datetime) -> dict[int, int]:
        if self.unavailable:
            raise SeenUnavailable("down")
        return {m: c for m, (c, at) in self.claims.items() if at >= since and m not in self.settled}


class FakePeople(People):
    def __init__(self, accounts: dict[tuple[str, str], Person]) -> None:
        self.accounts_by_id = accounts
        self.error: Exception | None = None
        self.asked: list[tuple[str, str]] = []

    async def person_for(self, system: str, external_id: str) -> Person | None:
        self.asked.append((system, external_id))
        if self.error is not None:
            raise self.error
        return self.accounts_by_id.get((system, external_id))

    async def household(self, household_id: int) -> Household | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class FakeDevices(Devices):
    def __init__(self, servers: list[DiscordServer]) -> None:
        self.servers = servers
        self.error: Exception | None = None

    async def discord_servers(self) -> list[DiscordServer]:
        if self.error is not None:
            raise self.error
        return list(self.servers)

    async def of_household(self, household_id: int) -> list[Listed]:
        return []

    async def by_token(self, token: str) -> Device | None:
        return None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []


class Replies:
    """The stub for `respond`: records each Inbound, answers `body` (conversation `conversation_id`) or raises
    `error`. Texts in `blocking` wait for `gate`; a cancelled wait is counted."""

    def __init__(self, body: str = "hi back", conversation_id: int = 77) -> None:
        self.inbounds: list[Inbound] = []
        self.body = body
        self.conversation_id = conversation_id
        self.error: Exception | None = None
        self.blocking: set[str] = set()
        self.gate = asyncio.Event()
        self.cancelled = 0

    async def __call__(self, inbound: Inbound) -> Outbound:
        self.inbounds.append(inbound)
        if inbound.text in self.blocking:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.error is not None:
            raise self.error
        return Outbound(self.conversation_id, "text", self.body)


@dataclass
class Rig:
    discord: FakeDiscord
    connect: FakeConnect
    seen: FakeSeen
    replies: Replies
    people: FakePeople
    devices: FakeDevices
    config: Config
    bot: Bot
    servers: list[DiscordServer] = field(default_factory=list[DiscordServer])


def config(**changes: object) -> Config:
    base = Config(max_messages=4, catch_up_s=600, seen_retention_days=30, typing_refresh_s=0.01,
                  token_poll_s=30,
                  unavailable_text="I cannot answer right now.", refused_text="I would rather not.",
                  held_footer="Answer yes to go ahead.")
    return replace(base, **changes)


def rig(servers: list[DiscordServer] | None = None, **config_changes: object) -> Rig:
    """A Bot over fakes, with People (Alana mapped) and Devices registered. Callers unregister them (`unwire`)."""
    made = [DiscordServer(FAMILY, GUILD, CHANNEL)] if servers is None else servers
    discord = FakeDiscord()
    connect, seen, replies = FakeConnect(discord), FakeSeen(), Replies()
    people = FakePeople({("discord", str(ALANA_ID)): ALANA})
    devices = FakeDevices(made)
    services.register(People, people)
    services.register(Devices, devices)
    cfg = config(**config_changes)
    return Rig(discord, connect, seen, replies, people, devices, cfg,
               Bot(connect, seen, cfg, respond=replies, now=lambda: NOW), made)


def unwire() -> None:
    services.unregister(People)
    services.unregister(Devices)


async def until(condition: Callable[[], object], timeout: float = 3.0) -> None:
    """Wait on the loop for `condition`; fails when it never holds."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "the awaited condition never held"
        await asyncio.sleep(0.005)


async def quiet() -> None:
    """Let every ready task run and a few typing refreshes pass, to check that something did not happen."""
    await asyncio.sleep(0.06)


@asynccontextmanager
async def running(r: Rig) -> AsyncGenerator[asyncio.Task[None]]:
    """Run the bot's lease body; on exit end the session's message stream and wait for the body to return."""
    task = asyncio.create_task(r.bot.run())
    try:
        yield task
    finally:
        if not task.done():
            r.discord.incoming.put_nowait(None)
        await asyncio.wait_for(task, 3.0)



@asynccontextmanager
async def seen_store(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[Seen]:
    """The Postgres claim store over its own pool (`ashley.channels.discord.postgres_seen.PostgresSeen`, assumed to take
    the `Database` as its one argument, like its siblings); imported here so the other suites collect without it."""
    database = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await database.open()
    try:
        made = getattr(import_module("ashley.channels.discord.postgres_seen"), "PostgresSeen")(database)
        assert isinstance(made, Seen)
        yield made
    finally:
        await database.close()


def execute(url: str, query: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode(), params)


def device_row(url: str, household_id: int, name: str, place: str = "den", audience: str = "household",
               medium: str = "text", kind: str = "chat") -> int:
    """An unrevoked device row (token = its name) and its id."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(
            b"INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
            b"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (household_id, name, place, audience, medium, kind, hashlib.sha256(name.encode()).digest())).fetchone()
    assert row is not None
    return int(row[0])
