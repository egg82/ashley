"""The Discord singleton (`decisions.md`, "Discord is a bot, its Gateway a singleton"): under the lease `discord`, one
Gateway session that answers DMs from mapped accounts and, in any channel of a household's server, messages that
mention her or reply to her; on any other message there from a household member she may make a remark (`remark`);
and she tends her home channel when `Initiative` allows it a slot of time (`home`).

Logs `discord.connected` (servers), `discord.disconnected` (reason), `discord.caught_up` (messages, channels, pruned,
unsettled),
`discord.ignored` (message, reason), `discord.unmapped` (user, message), `discord.claimed_elsewhere` (message),
`discord.replied` (message, conversation, chunks, duration_ms), `discord.failed` (message, reason) and
`discord.send_failed` (message, status), and `discord.remarked` (message, conversation, says). Never content."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from ... import logs, services
from ...people.model import Person
from ...people.people import People, PeopleUnavailable
from ..devices import Devices, DevicesUnavailable
from ..model import DiscordServer, Inbound, Outbound
from ..respond import RespondRefused, RespondUnavailable, respond as turn
from . import home, later, remark
from .chunks import chunks
from .receipts import receipt_lines
from .client import Connect, Discord, DiscordFailed
from .config import Config
from .message import Message, sent_at, snowflake_at
from .route import decide
from .seen import Seen, SeenUnavailable

log = logging.getLogger("ashley.channels.discord")

NAME = "discord"
_LIMIT = 2000


class Bot:
    """`run` is the lease body; cancelling it cancels in-flight replies and closes the session."""

    def __init__(self, connect: Connect, seen: Seen, config: Config,
                 respond: Callable[[Inbound], Awaitable[Outbound]] = turn,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC), later_poll_s: float = 0.25) -> None:
        self._connect = connect
        self._seen = seen
        self._config = config
        self._respond = respond
        self._now = now
        self._later_poll_s = later_poll_s

    async def run(self) -> None:
        """The lease body. Reads `Devices.discord_servers()` (DevicesUnavailable propagates: the lease releases and
        campaigns again after its pause), opens a session with `connect()`, prunes claims older than
        `seen_retention_days`, catches up, then handles each message from `messages()` as it arrives, each in its own
        task, until cancelled or the session ends. When the session ends it waits for the replies in flight, whose
        messages are claimed and so answered by no one else, then returns. Cancelling cancels in-flight replies and
        closes the session. The servers read at the start are what catch-up covers.
        Catch-up: for each server's home channel and each channel in `Seen.last(now - catch_up_s)` or
        `Seen.unsettled(now - catch_up_s)`, `history(channel, after=<last claimed id there, else the snowflake of now -
        catch_up_s; before the earliest unsettled claim there when there is one>)`, keeping messages whose `sent_at` is
        within `catch_up_s`; each handled as below, an unsettled one without claiming it again, and settled at once when
        she would not answer it now (route declines it, or the person or servers cannot be read). A DiscordFailed on one channel is logged and the others go on.
        Per message: `People.person_for("discord", str(author_id))` (PeopleUnavailable → `discord.failed`, dropped),
        in a guild channel the household servers from `Devices.discord_servers()`, read for each message so a server
        added with the CLI is answered at once (DevicesUnavailable → `discord.failed`, dropped), `route` (None →
        dropped, logged), `Seen.claim` (False or SeenUnavailable → dropped), typing every
        `typing_refresh_s` until sent, `respond`, `Seen.settle` once it returns or raises anything but cancellation (a
        cut-off reply stays unsettled for the next catch-up; SeenUnavailable logged), then
        `send` each of `chunks(out.body, 2000, max_messages)` in order (none for a reply with no words, pending), then the
        message for `out.receipts` when it has any (`receipts.receipt_lines`, not counted in `max_messages`),
        the first with `reply_to` the message id in a guild channel and None in a DM. RespondUnavailable → send
        `unavailable_text`; RespondRefused → `refused_text` (same reply_to rule). A DiscordFailed on send stops that
        reply's remaining chunks and is logged; a DiscordFailed on typing is ignored.
        While the session is open, the replies the outbox holds for Discord threads are posted every `later_poll_s`
        (`later.drain`), and she tends each server's home channel on her own initiative (`home.tend`), each such turn
        in flight like a reply."""
        servers = await services.get(Devices).discord_servers()
        async with self._connect() as discord:
            logs.info(log, "discord.connected", servers=len(servers))
            replies = _Replies()
            reason = "error"
            posting = asyncio.create_task(later.drain(discord, self._config, self._later_poll_s,
                                                      asyncio.sleep))
            tending = asyncio.create_task(home.tend(discord.me, replies.start, self._respond, self._now,
                                                    asyncio.sleep))
            try:
                await self._catch_up(discord, {s.home_channel_id for s in servers}, replies)
                async for message in discord.messages():
                    replies.start(self._handle(discord, message))
                reason = "ended"
                await replies.wait()
            except asyncio.CancelledError:
                reason = "cancelled"
                raise
            finally:
                posting.cancel()
                tending.cancel()
                await asyncio.gather(posting, tending, return_exceptions=True)
                await replies.cancel()
                logs.info(log, "discord.disconnected", reason=reason)

    async def _catch_up(self, discord: Discord, homes: set[int], replies: "_Replies") -> None:
        now = self._now()
        pruned = await self._prune(now)
        await remark.prune(now)
        since = now - timedelta(seconds=self._config.catch_up_s)
        last = await self._last(since)
        stranded = await self._unsettled(since)
        targets = sorted(homes | set(last) | set(stranded.values()))
        found = 0
        for channel in targets:
            after = min([last.get(channel, snowflake_at(since))] + [m - 1 for m, c in stranded.items() if c == channel])
            try:
                missed = await discord.history(channel, after=after)
            except DiscordFailed as e:
                logs.warning(log, "discord.failed", reason="history", channel=channel, status=e.status)
                continue
            for message in missed:
                if sent_at(message.id) >= since:
                    found += 1
                    replies.start(self._handle(discord, message, claimed=message.id in stranded))
        logs.info(log, "discord.caught_up", messages=found, channels=len(targets), pruned=pruned,
                  unsettled=len(stranded))

    async def _prune(self, now: datetime) -> int | None:
        try:
            return await self._seen.prune(now - timedelta(days=self._config.seen_retention_days))
        except SeenUnavailable:
            logs.warning(log, "discord.failed", reason="prune_unavailable")
            return None

    async def _unsettled(self, since: datetime) -> dict[int, int]:
        try:
            return await self._seen.unsettled(since)
        except SeenUnavailable:
            logs.warning(log, "discord.failed", reason="unsettled_unavailable")
            return {}

    async def _last(self, since: datetime) -> dict[int, int]:
        try:
            return await self._seen.last(since)
        except SeenUnavailable:
            logs.warning(log, "discord.failed", reason="last_unavailable")
            return {}

    async def _handle(self, discord: Discord, message: Message, claimed: bool = False) -> None:
        """`claimed`: the message's claim is already this bot's to hand in (one never settled)."""
        inbound = await self._inbound(discord, message)
        if inbound is None:
            if claimed:
                await self._settle(message)
            return
        if inbound.remark is not None:
            if claimed:
                await self._settle(message)
            await self._remark(message, inbound)
            return
        if not (claimed or await self._claim(message)):
            return
        started = time.perf_counter()
        typing = asyncio.create_task(self._typing(discord, message.channel_id))
        try:
            texts, conversation = await self._answer(message, inbound)
        except Exception:
            await self._settle(message)
            raise
        finally:
            typing.cancel()
        await self._settle(message)
        reply_to = None if message.guild_id is None else message.id
        sent = await self._send(discord, message, texts, reply_to)
        if conversation is not None:
            logs.info(log, "discord.replied", message=message.id, conversation=conversation, chunks=sent,
                      duration_ms=int((time.perf_counter() - started) * 1000))

    async def _inbound(self, discord: Discord, message: Message) -> Inbound | None:
        """The message as the turn loop takes it, or None (logged) when she does not answer it. A bot's message needs
        no person or servers to be ignored, so neither is looked up for it."""
        person: Person | None = None
        servers: dict[int, DiscordServer] = {}
        if not message.author_is_bot:
            try:
                person = await services.get(People).person_for("discord", str(message.author_id))
                if message.guild_id is not None:
                    servers = {s.guild_id: s for s in await services.get(Devices).discord_servers()}
            except PeopleUnavailable:
                logs.warning(log, "discord.failed", message=message.id, reason="people_unavailable")
                return None
            except DevicesUnavailable:
                logs.warning(log, "discord.failed", message=message.id, reason="devices_unavailable")
                return None
        got = decide(message, discord.me, servers, person)
        if got == "unmapped":
            logs.info(log, "discord.unmapped", user=message.author_id, message=message.id)
        elif isinstance(got, str):
            logs.info(log, "discord.ignored", message=message.id, reason=got)
        if got == "not_addressed":
            return await remark.offered(message, servers, person, self._now())
        return got if isinstance(got, Inbound) else None

    async def _remark(self, message: Message, inbound: Inbound) -> None:
        """Her remark's turn, claimed in `Remarks` and settled with what went out. What goes out is queued in the outbox
        by the turn and posted by `later.drain`, never here. A turn another runner finishes stays unsettled, so it is
        counted toward the day's cap."""
        source = inbound.source or ""
        try:
            out = await self._respond(inbound)
        except (RespondUnavailable, RespondRefused):
            logs.warning(log, "discord.failed", message=message.id, reason="remark_turn")
            await remark.settle(inbound.household_id, source, None)
            return
        if out.follows:
            return
        await remark.settle(inbound.household_id, source, None if out.says == "none" else out.body)
        logs.info(log, "discord.remarked", message=message.id, conversation=out.conversation_id, says=out.says)

    async def _claim(self, message: Message) -> bool:
        try:
            claimed = await self._seen.claim(message.id, message.channel_id)
        except SeenUnavailable:
            logs.warning(log, "discord.failed", message=message.id, reason="seen_unavailable")
            return False
        if not claimed:
            logs.info(log, "discord.claimed_elsewhere", message=message.id)
        return claimed

    async def _settle(self, message: Message) -> None:
        try:
            await self._seen.settle(message.id)
        except SeenUnavailable:
            logs.warning(log, "discord.failed", message=message.id, reason="settle_unavailable")

    async def _answer(self, message: Message, inbound: Inbound) -> tuple[list[str], int | None]:
        """What to post, and the conversation it belongs to (None for a fallback line)."""
        try:
            out = await self._respond(inbound)
        except RespondUnavailable:
            logs.warning(log, "discord.failed", message=message.id, reason="respond_unavailable")
            return [self._config.unavailable_text], None
        except RespondRefused:
            logs.info(log, "discord.failed", message=message.id, reason="refused")
            return [self._config.refused_text], None
        under = receipt_lines(out.receipts, self._config)
        return [*chunks(out.body, _LIMIT, self._config.max_messages), *(() if under is None else (under,))], out.conversation_id

    async def _typing(self, discord: Discord, channel_id: int) -> None:
        while True:
            try:
                await discord.typing(channel_id)
            except DiscordFailed:
                pass
            await asyncio.sleep(self._config.typing_refresh_s)

    async def _send(self, discord: Discord, message: Message, texts: list[str], reply_to: int | None) -> int:
        """Post each piece in order, the first as a reply to `reply_to`; how many were sent."""
        for i, text in enumerate(texts):
            try:
                await discord.send(message.channel_id, text, reply_to if i == 0 else None)
            except DiscordFailed as e:
                logs.warning(log, "discord.send_failed", message=message.id, status=e.status)
                return i
        return len(texts)


class _Replies:
    """The replies in flight, each its own task; one that fails unexpectedly is logged, never lost."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, reply: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(_logged(reply))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait(self) -> None:
        """Until every reply in flight, and any it started meanwhile, has finished."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _logged(reply: Coroutine[Any, Any, None]) -> None:
    try:
        await reply
    except Exception:
        logs.error(log, "discord.failed", exc=True, reason="error")
