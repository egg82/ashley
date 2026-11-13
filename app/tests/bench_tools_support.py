"""A recording `Workshop` for her bench tools' tests: `read` shows `pieces`, `recent`, `changes` and `shelf`, `apply` records the command
and answers `outcome`, and either raises `raises` when set."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ashley.workshop.commands import Command
from ashley.workshop.model import Bench, By, Change, Owner, Piece
from ashley.workshop.reactions import Unseen
from ashley.workshop.workshop import Applied, BenchView, Logged, Placed, TurnUndone, Workshop

EPOCH = datetime(2026, 10, 29, tzinfo=UTC)


@dataclass
class FakeWorkshop(Workshop):
    pieces: tuple[Piece, ...] = ()
    recent: tuple[Logged, ...] = ()
    shelf: tuple[Piece, ...] = ()
    changes: dict[int, Change] = field(default_factory=dict[int, Change])
    outcome: Applied = Applied(7, "accepted", 7)
    raises: Exception | None = None
    turn_undone: TurnUndone = TurnUndone((3, 2), ())
    turn_undos: list[tuple[By, int]] = field(default_factory=list[tuple[By, int]])
    applied: list[tuple[Owner, int, Command]] = field(default_factory=list[tuple[Owner, int, Command]])
    reads: list[tuple[Owner, int]] = field(default_factory=list[tuple[Owner, int]])

    async def open(self, owner: Owner, title: str) -> Bench:
        raise NotImplementedError

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        raise NotImplementedError

    async def open_benches(self, owner: Owner) -> list[Bench]:
        raise NotImplementedError

    async def close(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        raise NotImplementedError

    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        self.reads.append((owner, bench_id))
        if self.raises is not None:
            raise self.raises
        return BenchView(Bench(bench_id, owner.household_id, owner.person_id, "B", EPOCH, None), self.pieces,
                         self.recent, changes=self.changes, shelf=self.shelf)

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        if self.raises is not None:
            raise self.raises
        self.applied.append((owner, bench_id, command))
        return self.outcome

    async def undo_turn(self, owner: Owner, bench_id: int, by: By, seq: int) -> TurnUndone:
        self.turn_undos.append((by, seq))
        return self.turn_undone

    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        raise NotImplementedError

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        raise NotImplementedError

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        raise NotImplementedError

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        raise NotImplementedError
