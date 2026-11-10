"""The port to Discord, and its one implementation over hikari: the only module that imports the library
(`test_boundaries.py`). A session is one Gateway connection, identified with the bot token, plus the REST calls made
with the same token. The token is never logged."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TypeVar

import hikari
from hikari.api import CacheComponents
from hikari.impl import CacheSettings
from hikari.messages import MessageSnapshot

from .message import Message

T = TypeVar("T")
_INTENTS = hikari.Intents.GUILD_MESSAGES | hikari.Intents.DM_MESSAGES | hikari.Intents.MESSAGE_CONTENT


class DiscordFailed(Exception):
    """A REST call failed (`status` the HTTP status, 0 when none arrived)."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class Discord(ABC):
    """One open Gateway session and the REST calls made with the same token."""

    me: int
    """Her own user id, known once connected."""

    @abstractmethod
    def messages(self) -> AsyncIterator[Message]:
        """Every MESSAGE_CREATE the session receives, in arrival order, until the session closes."""

    @abstractmethod
    async def send(self, channel_id: int, text: str, reply_to: int | None) -> None:
        """Post `text` (≤ 2000 chars) with `allowed_mentions` parsing nothing; as a reply to `reply_to` when given.
        Raises DiscordFailed."""

    @abstractmethod
    async def typing(self, channel_id: int) -> None:
        """Show her typing for ~10 s. Raises DiscordFailed."""

    @abstractmethod
    async def history(self, channel_id: int, after: int, limit: int = 50) -> list[Message]:
        """Up to `limit` messages after the id `after`, oldest first. Raises DiscordFailed."""


Connect = Callable[[], AbstractAsyncContextManager[Discord]]
"""Opens a session on enter (returns once READY) and closes it on exit, cancellation included."""


def connect(token: str) -> Connect:
    """Sessions identified with `token`, every cache off. Each enter spends one IDENTIFY of Discord's daily allowance."""

    @asynccontextmanager
    async def session() -> AsyncGenerator[Discord]:
        bot = hikari.GatewayBot(token, intents=_INTENTS, banner=None, logs=None, suppress_optimization_warning=True,
                                cache_settings=CacheSettings(components=CacheComponents.NONE))
        arrived: asyncio.Queue[hikari.Message | None] = asyncio.Queue()

        async def on_create(event: hikari.MessageCreateEvent) -> None:
            arrived.put_nowait(event.message)

        bot.subscribe(hikari.MessageCreateEvent, on_create)
        ended: asyncio.Task[None] | None = None
        try:
            await bot.start(check_for_updates=False)
            me = await _rest(bot.rest.fetch_my_user())
            ended = asyncio.create_task(_until_closed(bot, arrived))
            yield HikariDiscord(bot, me.id, arrived)
        finally:
            if ended is not None:
                ended.cancel()
            if bot.is_alive:
                # start() is not cancel-safe: shards it opened keep running unless closed, cancelled or not.
                await asyncio.shield(bot.close())

    return session


async def _until_closed(bot: hikari.GatewayBot, arrived: "asyncio.Queue[hikari.Message | None]") -> None:
    """Ends `messages()` once the session stops for good (closed, or a shard gave up)."""
    await bot.join()
    arrived.put_nowait(None)


class HikariDiscord(Discord):
    def __init__(self, bot: hikari.GatewayBot, me: int, arrived: "asyncio.Queue[hikari.Message | None]") -> None:
        self._bot = bot
        self.me = me
        self._arrived = arrived

    async def messages(self) -> AsyncIterator[Message]:
        while (message := await self._arrived.get()) is not None:
            yield _message(message, self.me)

    async def send(self, channel_id: int, text: str, reply_to: int | None) -> None:
        await _rest(self._bot.rest.create_message(
            channel_id, text, reply=hikari.UNDEFINED if reply_to is None else reply_to, reply_must_exist=False,
            mentions_everyone=False, user_mentions=False, role_mentions=False, mentions_reply=False))

    async def typing(self, channel_id: int) -> None:
        await _rest(self._bot.rest.trigger_typing(channel_id))

    async def history(self, channel_id: int, after: int, limit: int = 50) -> list[Message]:
        # Discord returns each page newest first; hikari reverses pages fetched `after`, so this is oldest first.
        found = await _rest(self._bot.rest.fetch_messages(channel_id, after=after).limit(limit).collect(list))
        return [_message(m, self.me) for m in found]


async def _rest(call: Awaitable[T]) -> T:
    try:
        return await call
    except hikari.HTTPResponseError as e:
        raise DiscordFailed(int(e.status)) from e
    except hikari.HTTPError as e:
        raise DiscordFailed(0) from e


def _message(m: hikari.Message, me: int) -> Message:
    ref = m.referenced_message
    replies = ref is not None and isinstance(ref.author, hikari.User) and ref.author.id == me
    return Message(id=int(m.id), channel_id=int(m.channel_id), guild_id=None if m.guild_id is None else int(m.guild_id),
                   author_id=int(m.author.id), author_is_bot=m.author.is_bot, content=m.content or "",
                   mentions_me=me in (m.user_mentions_ids or ()), replies_to_me=replies, forwarded=forwarded_text(m.message_snapshots))


def forwarded_text(snapshots: Sequence[MessageSnapshot] | None) -> str:
    """The text of the forwarded messages `snapshots`, those with text, joined by a blank line."""
    return "\n\n".join(s.content for s in snapshots or () if s.content)
