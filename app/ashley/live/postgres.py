"""Live over Postgres LISTEN/NOTIFY. Every pod on both sites reaches the one writable primary, so a NOTIFY from any of
them reaches every pod's listener. Each process holds one listening connection, opened with its first subscriber and
reopened after a failover, and fans what it hears out to its own screens (`fanout.Fanout`). Publishing goes through a
queue drained by one task over the pooled connection, so a publisher never waits on the database.

Logs `live.listening` when the listener connects (`reconnect` true after a loss, when every screen is told to
resync), `live.listen_lost` with the wait before trying again, `live.publish_failed` and `live.publish_dropped` with
the count of events lost, and `live.malformed` for a notification it cannot read."""

import asyncio
import logging

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .events import Event, Watcher, decode, encode
from .fanout import Fanout, Subscription
from .live import Config, Live

log = logging.getLogger("ashley.live")

CHANNEL = "ashley_live"
_FIRST_WAIT_S = 0.5
# A listener on a link that died without a reset hears nothing forever; keepalives notice within about 25 s.
_KEEPALIVES = {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3}


class PostgresLive(Live):
    def __init__(self, conninfo: str, database: Database, config: Config, channel: str = CHANNEL) -> None:
        self._conninfo = conninfo
        self._database = database
        self._config = config
        self._channel = channel
        self._fanout = Fanout(config.queue_size)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: asyncio.Queue[Event] | None = None
        self._sender: asyncio.Task[None] | None = None
        self._listener: asyncio.Task[None] | None = None

    def publish(self, event: Event) -> None:
        pending = self._started()
        try:
            pending.put_nowait(event)
        except asyncio.QueueFull:
            logs.warning(log, "live.publish_dropped", events=1)

    def subscribe(self, viewer: Watcher) -> Subscription:
        self._started()
        if self._listener is None:
            self._listener = asyncio.create_task(self._listen())
        return self._fanout.subscription(viewer)

    async def close(self) -> None:
        """Stop sending and listening, and return once both have ended, so none is left holding a pooled connection
        when the database closes; what was still unsent is lost."""
        tasks = [t for t in (self._sender, self._listener) if t is not None]
        self._loop = self._sender = self._listener = self._pending = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _started(self) -> asyncio.Queue[Event]:
        """The sender started on the running loop. A new loop (a test client's) starts afresh."""
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._pending is None:
            self._loop = loop
            self._pending = asyncio.Queue(self._config.pending_size)
            self._sender = asyncio.create_task(self._send(self._pending))
            self._listener = None
        return self._pending

    async def _send(self, pending: asyncio.Queue[Event]) -> None:
        while True:
            batch = [await pending.get()]
            while not pending.empty():
                batch.append(pending.get_nowait())
            try:
                async with self._database.connection() as conn, conn.cursor() as cur:
                    await cur.executemany("SELECT pg_notify(%s, %s)", [(self._channel, encode(e)) for e in batch])
            except (DatabaseUnavailable, psycopg.Error):
                logs.warning(log, "live.publish_failed", events=len(batch))

    async def _listen(self) -> None:
        wait, heard_before = _FIRST_WAIT_S, False
        while True:
            try:
                conninfo = make_conninfo(self._conninfo, **_KEEPALIVES)
                async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
                    await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
                    logs.info(log, "live.listening", reconnect=heard_before)
                    if heard_before:
                        self._fanout.resync()
                    wait, heard_before = _FIRST_WAIT_S, True
                    async for note in conn.notifies():
                        self._hear(note.payload)
            except (psycopg.Error, OSError):
                logs.warning(log, "live.listen_lost", retry_s=wait)
            await asyncio.sleep(wait)
            wait = min(wait * 2, self._config.reconnect_max_s)

    def _hear(self, payload: str) -> None:
        event = decode(payload)
        if event is None:
            logs.warning(log, "live.malformed")
            return
        self._fanout.deliver(event)
