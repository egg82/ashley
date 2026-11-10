"""One satellite held connected: connect, take its wake-word runs, and reconnect with backoff when the session ends.

Logs `voice.connected` (device, `reconnect` true after an earlier session) and `voice.disconnected` once per session,
and `voice.connect_failed` (device, the error's type) once per run of failed attempts."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aioesphomeapi.core import APIConnectionError

from ... import logs
from ..model import Satellite
from .config import Config
from .connection import Announcer, Connection
from .run import Pipeline, Run

log = logging.getLogger("ashley.channels.voice")

Connect = Callable[[Satellite], Connection]
Sleep = Callable[[float], Awaitable[None]]


class Wakes:
    """The runs of one session, at most one at a time: a new wake abandons the run before it, as Home Assistant does."""

    def __init__(self, satellite: Satellite, connection: Connection, pipeline: Pipeline) -> None:
        self._satellite = satellite
        self._connection = connection
        self._pipeline = pipeline
        self._run: Run | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.cancel()
        self._run = Run(self._satellite, self._connection, self._pipeline)
        # started eagerly, so a run aborted at once still reaches its `voice.run` line
        self._task = asyncio.Task(self._run.go(), loop=asyncio.get_running_loop(), eager_start=True)

    async def audio(self, data: bytes) -> None:
        if self._run is not None:
            self._run.audio(data)

    async def stop(self, abort: bool) -> None:
        if abort:
            self.cancel()
        elif self._run is not None:
            self._run.end_audio()

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self._run = self._task = None


Links = dict[int, tuple[Satellite, Announcer]]
"""Each connected satellite's device id, to it and its session."""


async def hold(satellite: Satellite, connect: Connect, pipeline: Pipeline, config: Config,
               sleep: Sleep = asyncio.sleep, links: Links | None = None) -> None:
    """Keep `satellite` connected until cancelled, in `links` while a session is up."""
    device = satellite.device.id
    delay, failing, sessions = config.reconnect_first_s, False, 0
    while True:
        connection = connect(satellite)
        lost = asyncio.Event()

        async def on_lost() -> None:
            lost.set()

        try:
            await asyncio.wait_for(connection.connect(on_lost), config.connect_timeout_s)
        except (APIConnectionError, OSError, TimeoutError) as e:
            if not failing:
                logs.warning(log, "voice.connect_failed", device=device, error=type(e).__name__)
            failing = True
            await sleep(delay)
            delay = min(delay * 2, config.reconnect_max_s)
            continue
        logs.info(log, "voice.connected", device=device, reconnect=sessions > 0)
        delay, failing, sessions = config.reconnect_first_s, False, sessions + 1
        await _session(satellite, connection, pipeline, lost, {} if links is None else links)
        logs.info(log, "voice.disconnected", device=device)


async def _session(satellite: Satellite, connection: Connection, pipeline: Pipeline, lost: asyncio.Event,
                   links: Links) -> None:
    wakes = Wakes(satellite, connection, pipeline)
    connection.subscribe_voice(wakes.start, wakes.audio, wakes.stop)
    links[satellite.device.id] = (satellite, connection)
    try:
        await lost.wait()
    finally:
        if links.get(satellite.device.id, (None,))[0] == satellite:
            del links[satellite.device.id]
        wakes.cancel()
        if not lost.is_set():
            await connection.disconnect()
