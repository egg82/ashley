"""The satellite connections singleton (`decisions.md`, "A satellite connection is a singleton"): under the lease
`satellites`, one held connection per satellite of every household, re-read from `Devices.satellites` every
`satellites_poll_s` so one added, changed or revoked by the admin CLI is picked up without a restart; and the replies
the outbox holds for them, said every `later_poll_s` (`later.drain`).

Logs `voice.satellites` (count) when the set changes and `voice.devices_unavailable` once per run of failed reads,
keeping the connections it has meanwhile."""

import asyncio
import logging

from ... import logs, services
from ..devices import Devices, DevicesUnavailable
from ..model import Satellite
from .config import Config
from . import later
from .run import Pipeline
from .session import Connect, Links, Sleep, hold

log = logging.getLogger("ashley.channels.voice")

NAME = "satellites"


class Satellites:
    """`run` is the lease body; cancelling it closes every connection."""

    def __init__(self, connect: Connect, pipeline: Pipeline, config: Config, sleep: Sleep = asyncio.sleep,
                 later_poll_s: float = 0.25) -> None:
        self._connect = connect
        self._pipeline = pipeline
        self._config = config
        self._sleep = sleep
        self._later_poll_s = later_poll_s
        self._links: Links = {}

    async def run(self) -> None:
        held: dict[Satellite, asyncio.Task[None]] = {}
        failing = False
        saying = asyncio.create_task(later.drain(self._links, self._pipeline, self._later_poll_s, asyncio.sleep))
        try:
            while True:
                try:
                    wanted = set(await services.get(Devices).satellites())
                except DevicesUnavailable:
                    if not failing:
                        logs.warning(log, "voice.devices_unavailable")
                    failing = True
                else:
                    failing = False
                    self._reconcile(held, wanted)
                await self._sleep(self._config.satellites_poll_s)
        finally:
            for task in (saying, *held.values()):
                task.cancel()
            await asyncio.gather(saying, *held.values(), return_exceptions=True)

    def _reconcile(self, held: dict[Satellite, asyncio.Task[None]], wanted: set[Satellite]) -> None:
        """Drop the connections no longer wanted (a changed host or speaker is another `Satellite`); start the new."""
        if set(held) == wanted:
            return
        for gone in set(held) - wanted:
            held.pop(gone).cancel()
        for new in wanted - set(held):
            held[new] = asyncio.create_task(hold(new, self._connect, self._pipeline, self._config, self._sleep,
                                                 self._links))
        logs.info(log, "voice.satellites", count=len(held))
