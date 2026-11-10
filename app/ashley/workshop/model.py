"""What a bench and its pieces are, as values. Bench ids are Postgres identities; a piece's id and a command's `seq` are
numbers within their bench (`commands`). Every time is timezone-aware UTC."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Size = Literal["small", "medium", "large", "full"]
"""How much of the bench a piece takes, as a class the client maps to its own grid: `small` a quarter of the width,
`medium` a half, `large` three quarters, `full` the whole row."""

SIZES: tuple[Size, ...] = ("small", "medium", "large", "full")

Author = Literal["person", "ashley"]
"""Who made a change: `person` or `ashley`."""


@dataclass(frozen=True)
class Place:
    """Where a piece sits on its bench: `order`, its position among the bench's pieces (0 first; a bench's pieces hold
    exactly the orders 0 to n-1), and `size`. A value of its own so layout can move to Surfaces whole."""

    order: int
    size: Size

    def __post_init__(self) -> None:
        if self.order < 0:
            raise ValueError("a place's order is 0 or more")


@dataclass(frozen=True)
class By:
    """Who made a change: a person (`person_id` set) or her (`person_id` None). `outside` is set on a change of hers made
    in a turn that had read outside words: the piece it adds or edits is then marked `outside` for good. It is not stored
    with the command. `runner` is set on the bench jobs' runner alone, whose command is logged with it."""

    person_id: int | None
    outside: bool = False
    runner: bool = False

    @property
    def author(self) -> Author:
        return "ashley" if self.person_id is None else "person"


HER = By(None)
RUNNER = By(None, runner=True)
"""The bench jobs' runner, the only author of a `by_code` kind's pieces (`rules.Kind.by_code`)."""


@dataclass(frozen=True)
class Text:
    """A piece's words: its `title`, and its `body` (the content of a `stored` kind, the source reference of a `live`
    one)."""

    title: str
    body: str


@dataclass(frozen=True)
class Piece:
    """One piece on a bench. `id` is the `seq` of the command that added it, unique within the bench and never reused.
    `version` starts at 1 and rises by one with every change to `text`, an undone edit included, never otherwise, so
    an edit based on a version another change has passed is refused. `changed_by` is the `seq` of the last command that
    added, edited, moved, archived or restored this piece (its own place; another piece's move that shifts its order
    does not count). A piece on the shelf keeps the place it left, and its `changed_by` is the archive's. `outside` is true
    once a turn that had read outside words wrote its text: it never clears, and what reads the piece is tainted by it."""

    id: int
    kind: str
    text: Text
    version: int
    place: Place
    changed_by: int
    outside: bool = False


@dataclass(frozen=True)
class Change:
    """The command a piece last changed by: when it was decided and who made it."""

    at: datetime
    by: By


@dataclass(frozen=True)
class Owner:
    """The person whose benches are being asked about, and their household. Every Workshop call names one, and a bench
    of anyone else is as good as absent."""

    household_id: int
    person_id: int


@dataclass(frozen=True)
class Bench:
    """A bench, without its pieces. `closed_at` is None while it is open; a closed bench is kept, listed among the
    closed ones, and can be reopened. `piece_count` is how many pieces its layout holds now (not its shelf); `last_changed_at` is when its last accepted command was decided,
    not counting a Cue or a Point, which change nothing; None while it has none. `work` is its kind of work (a kind of
    `ashley.skills.config`), None until she or the person sets one."""

    id: int
    household_id: int
    owner_id: int
    title: str
    opened_at: datetime
    closed_at: datetime | None
    piece_count: int = 0
    last_changed_at: datetime | None = None
    work: str | None = None

    @property
    def thread(self) -> str:
        return thread_of(self.id)


def thread_of(bench_id: int) -> str:
    """The thread a bench's talk is carried on (`Conversations.for_thread`): `bench:<id>`."""
    return f"bench:{bench_id}"
