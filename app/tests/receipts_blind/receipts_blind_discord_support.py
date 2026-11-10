"""Support for the blind Discord receipts tests: the bot over `discord_support`'s fakes answering with a given `Outbound`,
and `later.post` over the same fakes.

G9  `later.post` is given the loaded Discord `Config` where it was given `max_messages` (it needs `held_footer`);
    `post_later` is the one place that call is made."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.discord import config as discord_config
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.later import post
from ashley.channels.model import DiscordServer, Inbound, Outbound
from ashley.channels.outbox import Later
from ashley.people.people import People
from discord_support import (ALANA, ALANA_ID, CHANNEL, FAMILY, GUILD, NOW, FakeConnect, FakeDevices, FakeDiscord,
                             FakePeople, FakeSeen, message, quiet, until)

config = discord_config.load()


@dataclass
class Bench:
    bot: Bot
    discord: FakeDiscord


def bench(outbound: Outbound, max_messages: int = 4) -> Bench:
    discord = FakeDiscord()
    services.register(People, FakePeople({("discord", str(ALANA_ID)): ALANA}))
    services.register(Devices, FakeDevices([DiscordServer(FAMILY, GUILD, CHANNEL)]))

    async def respond(inbound: Inbound) -> Outbound:
        return outbound

    made = replace(config, max_messages=max_messages, typing_refresh_s=0.01)
    return Bench(Bot(FakeConnect(discord), FakeSeen(), made, respond=respond, now=lambda: NOW), discord)


async def answered(outbound: Outbound, max_messages: int = 4) -> list[str]:
    """The texts the bot posts for one message it answers with `outbound`, in order."""
    b = bench(outbound, max_messages)
    async with running(b):
        b.discord.incoming.put_nowait(message(content="<@4242> turn on the lamp"))
        await until(lambda: b.discord.sends)
        await quiet()
    return b.discord.texts()


@asynccontextmanager
async def running(b: Bench) -> AsyncGenerator[asyncio.Task[None]]:
    task = asyncio.create_task(b.bot.run())
    try:
        yield task
    finally:
        if not task.done():
            b.discord.incoming.put_nowait(None)
        await asyncio.wait_for(task, 3.0)


async def post_later(outbound: Outbound, max_messages: int = 4) -> list[str]:
    """The texts `later.post` posts for a reply the outbox holds for a Discord thread."""
    discord = FakeDiscord()
    await post(discord, Later(1, 1, f"discord:{CHANNEL}", outbound, 100), replace(config, max_messages=max_messages))
    return discord.texts()
