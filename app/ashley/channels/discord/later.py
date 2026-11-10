"""Replies the `Outbox` holds for Discord threads (`discord:<channel_id>`), posted by the Discord singleton in that
channel, split as any reply is, the first replying to nothing, then the message for its receipts when it has any
(`receipts.receipt_lines`), not counted in `max_messages`.

Logs `discord.later` per reply taken: channel, conversation, chunks sent and `age_ms`, how long it waited;
`discord.send_failed` (channel, status) when a send fails, which stops that reply; and `discord.outbox_unavailable` once
per run of failed takes. Never content."""

import logging
from collections.abc import Awaitable, Callable

from ... import logs, services
from ..outbox import Later, Outbox, OutboxUnavailable
from .chunks import chunks
from .client import Discord, DiscordFailed
from .config import Config
from .receipts import receipt_lines

log = logging.getLogger("ashley.channels.discord")

PREFIX = "discord:"
_LIMIT = 2000


async def drain(discord: Discord, config: Config, poll_s: float,
                sleep: Callable[[float], Awaitable[None]]) -> None:
    """Every `poll_s` until cancelled, post each reply waiting for a Discord thread."""
    failing = False
    while True:
        try:
            waiting = await services.get(Outbox).take(PREFIX)
        except OutboxUnavailable:
            if not failing:
                logs.warning(log, "discord.outbox_unavailable")
            failing = True
        else:
            failing = False
            for later in waiting:
                await post(discord, later, config)
        await sleep(poll_s)


async def post(discord: Discord, later: Later, config: Config) -> None:
    channel = int(later.thread.removeprefix(PREFIX))
    sent = 0
    under = receipt_lines(later.outbound.receipts, config)
    for text in (*chunks(later.outbound.body, _LIMIT, config.max_messages), *(() if under is None else (under,))):
        try:
            await discord.send(channel, text, None)
        except DiscordFailed as e:
            logs.warning(log, "discord.send_failed", channel=channel, status=e.status)
            break
        sent += 1
    logs.info(log, "discord.later", channel=channel, conversation=later.outbound.conversation_id, chunks=sent,
              age_ms=later.age_ms)
