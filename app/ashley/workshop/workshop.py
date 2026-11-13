"""The Workshop service (`ashley.services`): what is on this bench, and who changed what. Callers import only this
module, `model`, `commands` and `rules`; the Postgres implementation lives beside it.

Every call names the `Owner` asking. A bench belongs to its household and the person who opened it (audience `owner`,
`decisions.md` "Per person by default"), and a bench of another person or household is treated exactly as one that
does not exist. Titles and bodies are people's data: stored, never logged."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ..services import Service
from .commands import Command, Effect, Reason, ScreenCommand, ShownRow
from .model import Author, Bench, By, Change, Owner, Piece
from .proposals import Proposal
from .reactions import Unseen
from .reader import Passage


class WorkshopError(Exception):
    """Base of what the service raises on purpose."""


class WorkshopUnavailable(WorkshopError):
    """No writable primary could be reached, or none is wired. Nothing was written. Transient."""


class BenchNotFound(WorkshopError):
    """No bench of the owner's has that id."""


class BenchClosed(WorkshopError):
    """The bench is closed, so it takes no command. Nothing was logged."""


class UnknownOwner(WorkshopError):
    """The owner is not a person of that household."""


class ScreenNotFound(WorkshopError):
    """The household has no unrevoked device of that id."""


@dataclass(frozen=True)
class Logged:
    """One row of a bench's command log: command `seq`, decided at `at` (the database's clock), `outcome` `accepted`
    or the refusal's reason, and `piece_id`, the piece its effect changed (None when refused)."""

    seq: int
    at: datetime
    command: Command
    outcome: Literal["accepted"] | Reason
    piece_id: int | None

    @property
    def by(self) -> By:
        return self.command.by


@dataclass(frozen=True)
class Pointer:
    """The highlight of a reader piece: `passage`, put up by command `seq` against the piece's `version`. A screen shows
    it only while the piece is still at that version."""

    seq: int
    version: int
    passage: Passage


@dataclass(frozen=True)
class SiteFrame:
    """What was measured of a site piece's address: `frameable` is whether the site lets a page frame it, None when that
    could not be measured, and `title` the page's own, empty when none was read."""

    frameable: bool | None
    title: str = ""


@dataclass(frozen=True)
class BenchView:
    """A bench as a screen shows it: `pieces` in order, and `recent`, its latest commands, oldest first. `changes` holds,
    for every piece, shelved ones included, the command it last changed by (the `Piece.changed_by` command), however
    old. `undo_next` is the `seq` the next Undo should name, walked over the last `undo_window` commands
    (`undo_walk.next_undo`), None when there is none. `shelf` is its archived pieces, the most recently archived first.
    `proposals` holds, for each piece on the layout waiting on the person's approval to install it, her proposal
    (`proposals.pending`). `pointers` holds the highlight of each reader piece that has one, by piece id, whether or not
    the piece has changed since (`Pointer.version`). `frames` holds the measure of each site address recorded on the
    bench (`record_site_frame`), by address. `surfaced` holds every (piece id, choice row by name and value) an accepted
    `Surfaced` named, however old (`surfacing.unshown` reads it)."""

    bench: Bench
    pieces: tuple[Piece, ...]
    recent: tuple[Logged, ...]
    changes: Mapping[int, Change] = field(default_factory=lambda: dict[int, Change]())
    undo_next: int | None = None
    shelf: tuple[Piece, ...] = ()
    proposals: Mapping[int, Proposal] = field(default_factory=lambda: dict[int, Proposal]())
    pointers: Mapping[int, Pointer] = field(default_factory=lambda: dict[int, Pointer]())
    frames: Mapping[str, SiteFrame] = field(default_factory=lambda: dict[str, SiteFrame]())
    surfaced: frozenset[tuple[int, ShownRow]] = frozenset()


@dataclass(frozen=True)
class ScreenView:
    """A device's screen as the hall shows it. `laid_out` is False while the device has no screen bench: `pieces` are then
    the seed (`screen_seed.json`) as the bench would be created, ids 1 to n, version 1, `changed_by` the id, the controls
    piece holding the device's `device_controls` rows; `seq` is the last command's, 0 when not laid out; `pieces` in order;
    `undo_next` the `seq` the next Undo should name, None when not laid out or when there is none (the commands that
    laid the screen out are not offered). `last_changed_by` is,
    for each piece id, whether a person or she made the command it last changed by (the seed is hers); two views are equal
    by the rest."""

    device_id: int
    laid_out: bool
    seq: int
    pieces: tuple[Piece, ...]
    undo_next: int | None
    last_changed_by: Mapping[int, Author] = field(default_factory=lambda: dict[int, Author](), compare=False)


@dataclass(frozen=True)
class Applied:
    """What `apply` decided: command `seq`, `outcome` as `Logged.outcome`, `piece_id` the piece it changed (for an
    accepted Add, the new piece's id) and `effect` what it did (not compared: two Applied are equal by the rest), both
    None when refused."""

    seq: int
    outcome: Literal["accepted"] | Reason
    piece_id: int | None
    effect: Effect | None = field(default=None, compare=False)


@dataclass(frozen=True)
class TurnUndone:
    """What `undo_turn` decided, all or nothing: `undone` the `seq`s of the turn's commands now taken back, newest first
    (empty when anything was refused), and `refused` each command that could not be undone with its reason. Nothing to
    undo is one refusal, of the `seq` asked, `nothing_to_undo`."""

    undone: tuple[int, ...]
    refused: tuple[tuple[int, Reason], ...]


@dataclass(frozen=True)
class Placed:
    """A piece's body where it stands: on bench `bench_id` of `owner_id`, at `version`."""

    bench_id: int
    owner_id: int
    piece_id: int
    version: int
    body: str


class Workshop(Service):
    @classmethod
    def null(cls) -> "Workshop":
        return NullWorkshop()

    @abstractmethod
    async def open(self, owner: Owner, title: str) -> Bench:
        """A new open bench of `owner`'s titled `title`, with no pieces and no commands; its thread is `bench:<id>`.
        Raises ValueError (before touching the database) for a title empty, only whitespace, longer than
        `title_max_chars` or holding a NUL character; UnknownOwner; WorkshopUnavailable. Logs `workshop.opened` with the bench and person ids."""

    @abstractmethod
    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        """Every piece of `kind` on the layout of the household's open benches, whoever owns them, by bench and piece
        id; shelved pieces and closed benches are left out. For what the household's pieces of a kind do outside any
        bench (a wake rule answering the house), never to show a bench. Raises WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def open_benches(self, owner: Owner) -> list[Bench]:
        """`owner`'s open benches, the most recently opened first (ties by id, higher first); closed ones are left out.
        Each carries its `piece_count` and `last_changed_at`, read in the same query. Raises WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def closed_benches(self, owner: Owner) -> list[Bench]:
        """`owner`'s closed benches, the most recently closed first (ties by id, higher first), each as `open_benches`
        gives one. Raises WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def close(self, owner: Owner, bench_id: int) -> Bench:
        """Close bench `bench_id`, now: the project is put away. It is kept, readable by `read` and `log`, listed by
        `closed_benches` instead of `open_benches`, and takes no command until reopened. Closing a closed bench changes
        nothing and returns it as it is. Raises BenchNotFound; WorkshopUnavailable. Logs `workshop.closed` with the
        bench id when it closes."""

    @abstractmethod
    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        """Open closed bench `bench_id` again, as it was closed (its pieces, shelf, log and `opened_at`), so it is
        listed by `open_benches` and takes commands. Reopening an open bench changes nothing and returns it as it is.
        Raises BenchNotFound; WorkshopUnavailable. Logs `workshop.reopened` with the bench id when it reopens."""

    async def set_work(self, owner: Owner, bench_id: int, work: str | None) -> Bench:
        """Set bench `bench_id`'s kind of work to `work` (None: no kind), open or closed. Which kinds
        exist is `ashley.skills.config`'s, checked by the caller. It is no Command: a label the person overwrites needs no
        replay or undo. Setting what it already is changes nothing; otherwise publishes
        `ashley.live.events.BenchChanged` to the owner. Raises ValueError (before touching the database) for a blank
        kind or one holding a NUL; BenchNotFound; WorkshopUnavailable. Logs `workshop.work`
        with the bench id and kind when it changes. Not abstract: an implementation that keeps no kind of work raises
        WorkshopUnavailable."""
        raise WorkshopUnavailable("this workshop keeps no kind of work")

    @abstractmethod
    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        """Bench `bench_id`, open or closed, with its pieces, its shelf, its latest `recent_commands` commands and each
        piece's `changes`. Raises BenchNotFound; WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        """Decide `command` on bench `bench_id` (`decide.decide`, against the bench as it stands and the rules this
        service was built with) and log it, accepted or refused, as the bench's next `seq`, changing the pieces as the
        decision says, in one transaction: two commands racing on one bench are decided one after the other, each
        against the bench the other left. After an accepted command commits, publishes `ashley.live.events.BenchChanged`
        to the owner alone; a refusal publishes nothing.
        Raises ValueError (before touching the database) when `command.by` names a person other than the owner or a text of
        the command holds a NUL character (the routes refuse one first; her tools must clean theirs);
        BenchNotFound; BenchClosed; WorkshopUnavailable. Nothing is logged when it raises. Logs `workshop.command`
        with the bench id, seq, command type, piece id, kind, author (`person` or `ashley`) and outcome."""

    @abstractmethod
    async def undo_turn(self, owner: Owner, bench_id: int, by: By, seq: int) -> TurnUndone:
        """Undo together the accepted commands of the turn that made command `seq` (those with the same `By.turn`), newest
        first, each by an Undo `by` made as `apply` would make it, each judged by the ordinary undo rules (`changed_since`
        and the rest), in one transaction: if any is refused none is undone and nothing is logged, and every refusal is
        returned. A command with no turn, a Run and the like, an Undo and a command already undone are not part of
        the group; an empty group is `nothing_to_undo`. After it commits, publishes `BenchChanged`. Raises what `apply`
        raises."""

    @abstractmethod
    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        """Every command of bench `bench_id`, in `seq` order from 1: replayed from empty through `decide` with the
        service's rules, it reproduces `read`'s pieces and shelf and each row's outcome. Raises BenchNotFound;
        WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        """At most `limit` open benches where a person's accepted commands came after the last one she has seen (the
        newest `bench_reactions` record; a bench no reaction has covered counts from its first command), the newest of
        them decided at least `pause_s` ago, the longest quiet first. Each lists its latest `listed` commands. Her own
        commands never count. Raises WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        """Seconds since each of the bench's reactions recorded within the last `window_s`, newest first. Raises
        WorkshopUnavailable. Reads only."""

    @abstractmethod
    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        """Record that she has been handed the person's commands up to `to_seq` of the bench, so the next `unseen`
        starts after it; recording the same `to_seq` again changes nothing. Deletes the bench's records older than
        `keep_s` except its newest. Raises WorkshopUnavailable."""


    async def screen(self, household_id: int, device_id: int) -> ScreenView:
        """The screen of the household's unrevoked device `device_id`. Reads only, and writes nothing, laid out or not.
        Raises ScreenNotFound; WorkshopUnavailable. Not abstract: an implementation that keeps no screens raises
        WorkshopUnavailable."""
        raise WorkshopUnavailable("this workshop keeps no screens")

    async def apply_screen(self, household_id: int, device_id: int, command: ScreenCommand) -> Applied:
        """Decide `command` on the device's screen under the screen rules (`rules.load_screen`) and log it, accepted or
        refused, in one transaction. A device with no screen bench first gets one: only the transaction that inserts it
        seeds it (the seed's Adds, made by her, as seqs 1 to n; the controls piece's body from the device's
        `device_controls` rows, which are deleted in the same transaction), so a device's buttons have one home at any
        time and two first commands at once make one bench. After the commit, publishes
        `ashley.live.events.ScreenChanged` to the household when the bench was created or the command was accepted; a
        refusal on an existing bench publishes nothing. Raises ValueError (before anything is written) for a command not in
        `ScreenCommand`, a text holding a NUL, or `by` naming a person not of the household; ScreenNotFound;
        WorkshopUnavailable. Logs `workshop.screen_opened` (bench, device, seeded count) on creation, and
        `workshop.command` with the device id too. Not abstract: an implementation that keeps no screens raises
        WorkshopUnavailable."""
        raise WorkshopUnavailable("this workshop keeps no screens")

    async def record_site_frame(self, household_id: int, bench_id: int, url: str, frame: SiteFrame) -> None:
        """Keep `frame` as the measure of the site address `url` on the bench, replacing an earlier one, and forget the
        bench's measures of addresses no piece holds. It is no Command: it is a fact about the site, not a change of the
        bench. Raises WorkshopUnavailable. Not abstract: an implementation that keeps none raises it."""
        raise WorkshopUnavailable("this workshop keeps no site frames")


class NullWorkshop(Workshop):
    """What an unwired process sees: every call raises WorkshopUnavailable."""

    async def open(self, owner: Owner, title: str) -> Bench:
        raise WorkshopUnavailable("no workshop is wired")

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        raise WorkshopUnavailable("the workshop is not wired")

    async def open_benches(self, owner: Owner) -> list[Bench]:
        raise WorkshopUnavailable("no workshop is wired")

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        raise WorkshopUnavailable("no workshop is wired")

    async def close(self, owner: Owner, bench_id: int) -> Bench:
        raise WorkshopUnavailable("no workshop is wired")

    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        raise WorkshopUnavailable("no workshop is wired")

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        raise WorkshopUnavailable("no workshop is wired")

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        raise WorkshopUnavailable("no workshop is wired")

    async def undo_turn(self, owner: Owner, bench_id: int, by: By, seq: int) -> TurnUndone:
        raise WorkshopUnavailable("no workshop is wired")

    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        raise WorkshopUnavailable("no workshop is wired")

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        raise WorkshopUnavailable("no workshop is wired")

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        raise WorkshopUnavailable("no workshop is wired")

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        raise WorkshopUnavailable("no workshop is wired")

    async def screen(self, household_id: int, device_id: int) -> ScreenView:
        raise WorkshopUnavailable("no workshop is wired")

    async def apply_screen(self, household_id: int, device_id: int, command: ScreenCommand) -> Applied:
        raise WorkshopUnavailable("no workshop is wired")
