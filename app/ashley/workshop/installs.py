"""The Installs record (`ashley.services`): what an Install, or the Undo of one, did to the house, written before its
first write to Home Assistant and again when it ends, so nothing is written to the house unrecorded and nothing is
written twice. Keyed by the bench command that asked (`bench_id`, `seq`). Callers import only this module;
`installs_postgres.PostgresInstalls` implements it. Configs are the household's data and are never logged."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ..services import Service

Action = Literal["install", "uninstall"]
Ending = Literal["done", "refused", "failed"]
"""How it ended: `done`; `refused` (HA refused the config; nothing was written); `failed` (HA could not be reached or
stopped answering part way: `note` says from which step, and what may have changed)."""


class InstallsUnavailable(Exception):
    """The record could not be read or written. Nothing is written to the house whose start was not recorded."""


@dataclass(frozen=True)
class Before:
    """The house as it was before an install wrote to it: `config`, what HA held under the install's id (None for
    nothing), and whether it was `enabled`; and whether the automation it was to turn off was on (`turn_off_was_on`,
    None when it named none or HA had none by that entity id)."""

    config: Mapping[str, Any] | None
    enabled: bool | None
    turn_off_was_on: bool | None


@dataclass(frozen=True)
class NewInstall:
    """An install or uninstall about to start: the household, the bench command `seq` that asked, the piece, the
    automation id, `enabled` (an install's choice; None for an uninstall), `turn_off` (the entity it turns off, or for
    an uninstall back on; None for none), `before` (an install's reading of the house; None for an uninstall) and
    `touched`, whether writing to the house may begin (False for one recorded only to say it could not, or that
    there was nothing to take back)."""

    household_id: int
    bench_id: int
    seq: int
    piece_id: int
    action: Action
    automation_id: str
    enabled: bool | None
    turn_off: str | None
    before: Before | None
    touched: bool


@dataclass(frozen=True)
class InstallRecord:
    """A recorded install or uninstall: what started, and `ending` and `note` once it ended, None while it runs and for
    good when its runner stopped part way (it is never carried out again)."""

    started: NewInstall
    started_at: datetime
    ending: Ending | None
    note: str | None
    finished_at: datetime | None


class Installs(Service):
    @classmethod
    def null(cls) -> "Installs":
        return NullInstalls()

    @abstractmethod
    async def start(self, install: NewInstall) -> None:
        """Record `install` as started. Raises InstallsUnavailable; ValueError when command `seq` of that bench already
        has a record, or for text Postgres cannot store (a NUL)."""

    @abstractmethod
    async def finish(self, bench_id: int, seq: int, ending: Ending, note: str | None) -> None:
        """Record how the install of command `seq` ended. Raises InstallsUnavailable; KeyError when none was started;
        ValueError when it has already ended."""

    @abstractmethod
    async def of(self, household_id: int, bench_id: int, seq: int) -> InstallRecord | None:
        """The record of bench command `seq`, None when it has none. Raises InstallsUnavailable."""

    @abstractmethod
    async def wrote_before(self, household_id: int, bench_id: int, piece_id: int) -> bool:
        """Whether any install or uninstall of that piece recorded so far may have written to the house: it began
        writing (`touched`) and HA did not refuse it. Raises InstallsUnavailable."""

    @abstractmethod
    async def latest_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, InstallRecord]:
        """The latest install or uninstall of each piece of the bench that has one, by piece id; empty for a bench of
        another household. Raises InstallsUnavailable."""


class NullInstalls(Installs):
    """Records nothing, so nothing is written to the house: what an unwired process sees."""

    async def start(self, install: NewInstall) -> None:
        raise InstallsUnavailable("Installs is not wired")

    async def finish(self, bench_id: int, seq: int, ending: Ending, note: str | None) -> None:
        raise InstallsUnavailable("Installs is not wired")

    async def of(self, household_id: int, bench_id: int, seq: int) -> InstallRecord | None:
        raise InstallsUnavailable("Installs is not wired")

    async def wrote_before(self, household_id: int, bench_id: int, piece_id: int) -> bool:
        raise InstallsUnavailable("Installs is not wired")

    async def latest_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, InstallRecord]:
        raise InstallsUnavailable("Installs is not wired")
