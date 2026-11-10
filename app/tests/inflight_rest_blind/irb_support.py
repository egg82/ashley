"""The Discord bot over the real turn loop, Conversations, InFlight, Outbox and claim store on one database, with a
fake model, tools and Discord. A pod is a Bot over its own FakeDiscord and the model and tools `World.as_pod` selects;
a kill cancels the bot's task with no cleanup of our own."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.message import Message
from ashley.channels.discord.postgres_seen import PostgresSeen
from ashley.channels.discord.seen import Seen
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.people.model import Household, Person
from ashley.people.people import People
from contract.conversations_support import POLICY, ascalar
from contract.test_inflight_resume import OnePerson, World, database
from discord_support import (ALANA_ID, DM_CHANNEL, NOW, FakeConnect, FakeDevices, FakeDiscord, config, message,
                             snowflake, until)

Replier = Callable[[Inbound], Awaitable[Outbound]]
ASKED = "turn on the lamp"


@dataclass
class Linked(OnePerson):
    """Alana's Discord account is mapped to the world's person."""

    who: Person | None = None
    error: Exception | None = None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        if self.error is not None:
            raise self.error
        return self.who if (system, external_id) == ("discord", str(ALANA_ID)) else None


def dm(sequence: int = 1) -> Message:
    return message(id=snowflake(NOW, sequence), channel_id=DM_CHANNEL, guild_id=None, mentions_me=False, content=ASKED)


@dataclass
class Pod:
    discord: FakeDiscord = field(default_factory=FakeDiscord)
    task: asyncio.Task[None] | None = None


@dataclass
class Stack:
    world: World
    seen: Seen
    outbox: Outbox
    people: Linked

    def bot(self, pod: Pod, seen: Seen | None = None, respond: Replier | None = None) -> Bot:
        if respond is None:
            return Bot(FakeConnect(pod.discord), seen or self.seen, config(), now=lambda: NOW, later_poll_s=0.02)
        return Bot(FakeConnect(pod.discord), seen or self.seen, config(), respond, now=lambda: NOW, later_poll_s=0.02)

    async def start(self, pod: Pod, seen: Seen | None = None, respond: Replier | None = None) -> None:
        pod.task = asyncio.create_task(self.bot(pod, seen, respond).run())

    async def kill(self, pod: Pod) -> None:
        assert pod.task is not None
        pod.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pod.task

    async def stop(self, pod: Pod) -> None:
        """End the session and let the replies in flight finish."""
        assert pod.task is not None
        if not pod.task.done():
            pod.discord.incoming.put_nowait(None)
        await asyncio.wait_for(pod.task, 5)

    async def counts(self) -> tuple[int, int]:
        """Person turns and turns of hers stored."""
        url = self.world.url
        return (int(await ascalar(url, "SELECT count(*) FROM turns WHERE author = 'person'")),
                int(await ascalar(url, "SELECT count(*) FROM turns WHERE author = 'ashley'")))

    async def unsettled(self) -> dict[int, int]:
        return await self.seen.unsettled(datetime(2000, 1, 1, tzinfo=UTC))


@asynccontextmanager
async def stack(world: World) -> AsyncGenerator[Stack]:
    async with database(world) as db:
        outbox = PostgresOutbox(db, 600.0, POLICY)
        seen = PostgresSeen(db)
        services.register(Outbox, outbox)
        people = Linked(Household(world.who.household_id, "home", "America/Denver", "", (world.who,)), who=world.who)
        services.register(People, people)
        services.register(Devices, FakeDevices([]))
        try:
            yield Stack(world, seen, outbox, people)
        finally:
            for interface in (Outbox, Devices):
                services.unregister(interface)


async def settle_for(seconds: float = 0.08) -> None:
    await asyncio.sleep(seconds)


async def sends(pod: Pod, count: int) -> None:
    await until(lambda: len(pod.discord.sends) >= count, 5.0)
