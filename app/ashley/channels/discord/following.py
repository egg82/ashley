"""The Discord singleton's lease body: runs her bot on the token in force and follows it. Logs `discord.token_changed`
(to: `set` or `none`), `discord.token_unreadable`; never the token."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from ... import logs
from ...connections.connections import ConnectionsUnavailable

log = logging.getLogger("ashley.channels.discord")


async def follow(token: Callable[[], Awaitable[str]], start: Callable[[str], Coroutine[Any, Any, None]], poll_s: float) -> None:
    """Reads `token` every `poll_s`. With none, it waits: she is off Discord. With one, it runs `start(token)` (the bot's
    session) until it returns or raises, which ends this body so the lease campaigns again after its pause, as for a
    session that ends on its own. When the token read differs from the one running (replaced, or removed in the room) the
    session is cancelled, which closes it, and a new one starts on the next read with the new token, so a change needs no
    restart. A token that cannot be read (ConnectionsUnavailable, logged) leaves the session as it is. Cancelling this
    body cancels the session."""
    running: tuple[str, asyncio.Task[None]] | None = None
    try:
        while True:
            try:
                wanted = await token()
            except ConnectionsUnavailable:
                logs.warning(log, "discord.token_unreadable")
                wanted = running[0] if running else ""
            if running is not None and wanted != running[0]:
                logs.info(log, "discord.token_changed", to="set" if wanted else "none")
                await _stop(running[1])
                running = None
            if running is None and wanted:
                running = (wanted, asyncio.create_task(start(wanted)))
            if running is None:
                await asyncio.sleep(poll_s)
                continue
            done, _ = await asyncio.wait({running[1]}, timeout=poll_s)
            if done:
                await running[1]
                return
    finally:
        if running is not None:
            await _stop(running[1])


async def _stop(session: asyncio.Task[None]) -> None:
    session.cancel()
    await asyncio.gather(session, return_exceptions=True)
