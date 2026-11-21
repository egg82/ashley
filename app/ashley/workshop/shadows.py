"""The Shadows record (`ashley.services`): each shadow run of an automation piece (`shadow`) and what was recorded in it,
which Home Assistant's event stream tells (`shadow_job`): a `would` firing each time the shadow automation fires its
event, a `did` firing each time the automation the piece would replace (`NewShadow.mirrors`) is triggered. A run is
recorded before its first write to the house, so the job that ends it knows it. Retention is the writer's: a run keeps
its newest `Settings.max_events` firings and `prune` drops firings past `Settings.keep_s`. Callers import only this
module; `shadows_postgres.PostgresShadows` implements it. Entity ids and event data are never logged."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..services import Service

Kind = Literal["would", "did"]


class ShadowsUnavailable(Exception):
    """The record could not be read or written."""


@dataclass(frozen=True)
class NewShadow:
    """A run about to begin by Install command `install_seq` of `piece_id` at `version`, approved by `person_id`, to end
    at `ends_at`; `mirrors` is the entity id of the automation it would replace (None for none)."""

    household_id: int
    bench_id: int
    install_seq: int
    piece_id: int
    version: int
    person_id: int
    mirrors: str | None
    started_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Firing:
    kind: Kind
    at: datetime


@dataclass(frozen=True)
class ShadowRun:
    """A run as a bench shows it: `ended_at` is None while it runs; `would` and `did` count the firings kept and
    `firings` lists the newest of them, newest first."""

    started: NewShadow
    ended_at: datetime | None
    would: int
    did: int
    firings: tuple[Firing, ...]


class Shadows(Service):
    @classmethod
    def null(cls) -> "Shadows":
        return NullShadows()

    @abstractmethod
    async def begin(self, run: NewShadow) -> None:
        """Record `run`. Raises ShadowsUnavailable; ValueError when that Install already has a run."""

    @abstractmethod
    async def end(self, bench_id: int, install_seq: int, now: datetime) -> bool:
        """End the run at `now`; False, changing nothing, when it is not running. Raises ShadowsUnavailable."""

    @abstractmethod
    async def would(self, household_id: int, bench_id: int, piece_id: int, at: datetime, context: str) -> bool:
        """Record that the piece's shadow fired at `at`, in the run of that piece still running (event `context` id, so
        a told-twice event counts once); False when none runs. Raises ShadowsUnavailable."""

    @abstractmethod
    async def did(self, household_id: int, entity_id: str, at: datetime, context: str) -> int:
        """Record that automation `entity_id` was triggered at `at`, in every run of the household still running that
        names it; how many runs recorded it. Raises ShadowsUnavailable."""

    @abstractmethod
    async def households(self) -> tuple[int, ...]:
        """The households with a run still running. Raises ShadowsUnavailable."""

    @abstractmethod
    async def due(self, now: datetime) -> tuple[NewShadow, ...]:
        """The runs still running whose end has come by `now`, oldest end first. Raises ShadowsUnavailable."""

    @abstractmethod
    async def of_bench(self, household_id: int, bench_id: int) -> Mapping[int, ShadowRun]:
        """The latest run of each piece of the bench that has one, by piece id. Raises ShadowsUnavailable."""

    @abstractmethod
    async def prune(self, now: datetime) -> int:
        """Delete firings older than `keep_s` before `now`, and runs ended before then with none left; how many
        firings went. Raises ShadowsUnavailable."""


class NullShadows(Shadows):
    """Records nothing, so no shadow is installed: what an unwired process sees."""

    async def begin(self, run: NewShadow) -> None:
        raise ShadowsUnavailable("Shadows is not wired")

    async def end(self, bench_id: int, install_seq: int, now: datetime) -> bool:
        raise ShadowsUnavailable("Shadows is not wired")

    async def would(self, household_id: int, bench_id: int, piece_id: int, at: datetime, context: str) -> bool:
        raise ShadowsUnavailable("Shadows is not wired")

    async def did(self, household_id: int, entity_id: str, at: datetime, context: str) -> int:
        raise ShadowsUnavailable("Shadows is not wired")

    async def households(self) -> tuple[int, ...]:
        raise ShadowsUnavailable("Shadows is not wired")

    async def due(self, now: datetime) -> tuple[NewShadow, ...]:
        raise ShadowsUnavailable("Shadows is not wired")

    async def of_bench(self, household_id: int, bench_id: int) -> Mapping[int, ShadowRun]:
        raise ShadowsUnavailable("Shadows is not wired")

    async def prune(self, now: datetime) -> int:
        raise ShadowsUnavailable("Shadows is not wired")
