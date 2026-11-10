"""What a person did on a bench since she last looked, for her to react to (`Workshop.unseen`): ids and kinds only,
never a piece's words. A reaction is recorded once she has been handed the changes up to a command (`Workshop.reacted`),
and the newest record is the last command she has seen."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Done:
    """One accepted command of a person: its `seq`, `type` (`add`, `edit`, `move`...), and the piece it changed with the
    piece's `kind` as it stands now (None for a command with no piece, such as a rename, and for a piece since removed),
    and `at`, when it was decided (the database's clock)."""

    seq: int
    type: str
    piece_id: int | None
    kind: str | None
    at: datetime


@dataclass(frozen=True)
class Unseen:
    """The person's changes on open bench `bench_id` after the last command she has seen (`after`) up to their newest
    (`to_seq`), the last of them quiet for at least the pause asked. `count` is how many accepted commands that is;
    `done` the latest of them, oldest first, at most the number asked for."""

    bench_id: int
    household_id: int
    owner_id: int
    after: int
    to_seq: int
    count: int
    done: tuple[Done, ...]
