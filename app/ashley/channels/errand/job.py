"""The errands job: the singleton that does, once its source answers, what she could not for want of it
(`docs/decisions.md`, "What she could not do for want of a source, she does once it answers, and says so next time").
It runs under the lease, so on one site at a time; replies never wait on it.

Logs `errands.tick` per tick (`swept`, `claimed`, `done`, `released`, `given_up`, `stopped` naming why it ended early,
`duration_ms`) and per errand `errands.done`, `errands.released` or `errands.given_up` (its id, `attempt`, `reason`
where there is one, `calls`, `duration_ms`). Ids, counts and types only."""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from ... import logs, services
from ...conversations.conversations import ConversationsUnavailable
from ...inference.inference import InferenceRefused, InferenceUnavailable
from ...people.people import PeopleUnavailable
from ...tools.tools import Catalogue, Tools, ToolsUnavailable
from .attempt import Ran, Unrunnable, attempt
from ...errands.config import CONFIG, ErrandsConfig
from ...errands.errands import Errands, ErrandsUnavailable
from ...errands.model import Errand

log = logging.getLogger("ashley.errands")

NAME = "errands"

class _Stop(Exception):
    """Ends the tick: what every remaining errand needs is down."""

    def __init__(self, reason: str, outcome: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.outcome = outcome


class ErrandJob:
    """`run` is the lease body: a tick, then `config.tick_s`, until cancelled. A tick sweeps, and when any errand is due
    reads the catalogue and takes up to `config.batch` errands whose source answers, running each in turn; a released errand's source is
    left alone for the rest of the tick, so it is not taken again at once. Inference unavailable releases
    the errand and ends the tick; the database unavailable ends it with whatever it held left to the next sweep.
    Cancellation (the lease lost) stops it wherever it is; the errand it held is called interrupted by a later sweep."""

    def __init__(self, config: ErrandsConfig = CONFIG, now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self._config = config
        self._now = now
        self._clock = clock

    async def run(self) -> None:
        logs.info(log, "errands.policy", **asdict(self._config))
        while True:
            await self.tick()
            await asyncio.sleep(self._config.tick_s)

    async def tick(self) -> Counter[str]:
        """One tick; the counts it logged."""
        started = self._clock()
        counts: Counter[str] = Counter()
        stopped: str | None = None
        try:
            swept = await services.get(Errands).sweep(self._config.claim_s, self._config.max_age_s)
            counts["swept"] = swept.interrupted + swept.expired
            await self._work(counts)
        except _Stop as e:
            stopped = e.reason
        except ErrandsUnavailable:
            stopped = "database_unavailable"
        logs.info(log, "errands.tick", swept=counts["swept"], claimed=counts["claimed"], done=counts["done"],
                  released=counts["released"], given_up=counts["given_up"], stopped=stopped,
                  duration_ms=self._ms(started))
        return counts

    async def _work(self, counts: Counter[str]) -> None:
        due = await services.get(Errands).due_sources(self._config.max_age_s)
        if not due:
            return
        try:
            catalogue = await services.get(Tools).catalogue()
        except ToolsUnavailable:
            return
        answering = sorted(due - set(catalogue.unreachable))
        for _ in range(self._config.batch):
            if not answering:
                return
            errand = await services.get(Errands).claim(answering, self._config.max_age_s)
            if errand is None:
                return
            counts["claimed"] += 1
            try:
                outcome = await self._one(errand, catalogue)
            except _Stop as e:
                counts[e.outcome] += 1
                raise
            counts[outcome] += 1
            if outcome == "released" and errand.source in answering:
                answering.remove(errand.source)

    async def _one(self, errand: Errand, catalogue: Catalogue) -> str:
        """Runs one claimed errand and settles it: `done`, `released` or `given_up`. Raises _Stop."""
        started = self._clock()
        store = services.get(Errands)
        try:
            ran = await attempt(errand, catalogue, self._config, self._now())
        except InferenceUnavailable as e:
            outcome = await self._release(errand, "inference_unavailable", 0, started)
            raise _Stop("inference_unavailable", outcome) from e
        except InferenceRefused:
            await store.give_up(errand.id, errand.attempt, "refused")
            return self._ended("given_up", errand, started, reason="refused")
        except (Unrunnable, ConversationsUnavailable, PeopleUnavailable) as e:
            return await self._release(errand, type(e).__name__, 0, started)
        return await self._settled(errand, ran, started)

    async def _settled(self, errand: Errand, ran: Ran, started: float) -> str:
        if ran.owed is not None:
            return await self._release(errand, "owed", ran.calls, started)
        await services.get(Errands).finish(errand.id, errand.attempt, ran.text)
        return self._ended("done", errand, started, calls=ran.calls)

    async def _release(self, errand: Errand, why: str, calls: int, started: float) -> str:
        state = await services.get(Errands).release(errand.id, errand.attempt, self._config.max_attempts)
        if state == "given_up":
            return self._ended("given_up", errand, started, reason="attempts", calls=calls)
        return self._ended("released", errand, started, reason=why, calls=calls)

    def _ended(self, outcome: str, errand: Errand, started: float, reason: str | None = None, calls: int = 0) -> str:
        fields: dict[str, object] = {"errand": errand.id, "attempt": errand.attempt, "calls": calls,
                                     "duration_ms": self._ms(started)}
        if reason is not None:
            fields["reason"] = reason
        logs.info(log, f"errands.{outcome}", **fields)
        return outcome

    def _ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)
