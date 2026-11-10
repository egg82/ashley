"""The Runs service (`ashley.services`): the record of every code run, written before it starts and again when it
ends, so a run is never repeated and its result outlives the pod that ran it. Callers import only this module;
`postgres.PostgresRuns` implements it. Scripts, input, output and files are people's data and are never logged."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence

from ..services import Service
from .model import Artifact, NewRun, Output, Run


class RunsUnavailable(Exception):
    """The record could not be read or written. A run whose start cannot be recorded is not run."""


class Runs(Service):
    @classmethod
    def null(cls) -> "Runs":
        return NullRuns()

    @abstractmethod
    async def start(self, run: NewRun) -> int:
        """Record `run` as started and return its id. Raises RunsUnavailable; ValueError for text Postgres cannot
        store (a NUL)."""

    @abstractmethod
    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        """Record what `run_id` gave back, and the `artifacts` of it that were kept in the object store (the output's own
        bytes are not recorded). Raises RunsUnavailable; KeyError when no such run was started; ValueError
        when it already has an output, or for text Postgres cannot store (a NUL). Finishing a bench run deletes, in the
        same transaction, the piece's older finished runs but for its latest, its latest that ran to its end and this one, and logs
        `runs.pruned` with the count; a chat turn's runs are never deleted this way."""

    @abstractmethod
    async def get(self, household_id: int, run_id: int) -> Run | None:
        """The run, or None when the household has none by that id. Raises RunsUnavailable."""

    @abstractmethod
    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        """Every run the household's conversation asked for, oldest first (by id), in one read; none when it asked for
        none or is not the household's. A run made by a bench's Run command is its piece's, not the turn's, and is
        left out even when her turn asked for it. Raises RunsUnavailable."""

    @abstractmethod
    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        """The latest `latest` runs (by id) the household's person turns `turn_ids` asked for, oldest first, in one
        read; none when `latest` is 0 or no turn asked for one. A run made by a bench's Run command is left out, as in
        `in_conversation`. Raises RunsUnavailable."""

    async def bench_runs_in_turn(self, household_id: int, turn_id: int) -> int:
        """How many runs made by a bench's Run command are recorded against the household's person turn `turn_id`;
        0 for an implementation that keeps no record of them. Raises RunsUnavailable."""
        return 0

    @abstractmethod
    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        """The latest run of each piece of bench `bench_id` that has one, by piece id, finished or not; empty for a
        bench of another household. Raises RunsUnavailable."""

    @abstractmethod
    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        """The files left by the latest run of that piece that ran to its end (outcome `ran`, any exit code), which its
        next run starts with; empty when none has. A run stopped, killed or lost part way may have left its files half
        written, so it passes nothing on and the one before it still does. Raises RunsUnavailable."""


class NullRuns(Runs):
    """Records nothing, so nothing is run: what an unwired process sees."""

    async def start(self, run: NewRun) -> int:
        raise RunsUnavailable("Runs is not wired")

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        raise RunsUnavailable("Runs is not wired")

    async def get(self, household_id: int, run_id: int) -> Run | None:
        raise RunsUnavailable("Runs is not wired")

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        return []

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        return []

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        raise RunsUnavailable("Runs is not wired")

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        raise RunsUnavailable("Runs is not wired")
