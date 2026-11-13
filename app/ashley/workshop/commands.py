"""Every change to a bench is one of these Commands (GoF Command): frozen records in one closed union, each naming who
made it (`by`), decided by `decide.decide` against the bench into an accepted change or a typed refusal, and logged
whichever it was. `seq` numbers a bench's commands 1, 2, 3... in the order they were decided, refused ones included.

What an accepted command did is its Effect, which is what Undo inverts."""

from dataclasses import dataclass
from typing import Literal

from .model import By, Piece, Place, Size, Text
from .reader import Passage
from .reasons import REASONS as REASONS, Reason as Reason


@dataclass(frozen=True)
class Add:
    """Add a piece of `kind` with `text`, last on the bench, at `size`. Its id is this command's `seq`."""

    by: By
    kind: str
    text: Text
    size: Size


@dataclass(frozen=True)
class Remove:
    """Take piece `piece_id` off the bench; the pieces after it move up one."""

    by: By
    piece_id: int


@dataclass(frozen=True)
class Move:
    """Put piece `piece_id` at `place`: its order among the bench's pieces as they stand (the others shift to make
    room) and its size. A move to where it already is is accepted and changes nothing but `changed_by`."""

    by: By
    piece_id: int
    place: Place


@dataclass(frozen=True)
class Edit:
    """Replace piece `piece_id`'s text with `text`, based on the piece as it was at `base_version`."""

    by: By
    piece_id: int
    base_version: int
    text: Text


@dataclass(frozen=True)
class Run:
    """Run piece `piece_id`, a code piece, as it is at `base_version`, in `language` (one the sandbox runs, which the
    caller checks: `decide` does not know the sandbox). Its effect changes no piece; the run itself happens after the
    command is logged (`workshop.run_piece`)."""

    by: By
    piece_id: int
    base_version: int
    language: str


@dataclass(frozen=True)
class Propose:
    """Propose installing piece `piece_id`, an automation piece, as it is at `base_version`, into Home Assistant:
    `enabled` or not once installed, and `turn_off`, the entity id of an automation to turn off with it (None for
    none). It changes no piece and is never undone; nothing is installed until a person's Install names it."""

    by: By
    piece_id: int
    base_version: int
    enabled: bool
    turn_off: str | None


@dataclass(frozen=True)
class Install:
    """A person's approval of proposal `proposal` (the `seq` of a Propose of piece `piece_id`): install the piece as
    proposed, under `automation_id` in Home Assistant. The write to the house happens after the command is logged
    (`workshop.install_piece`); her own Install is refused, since every write to the house is the person's."""

    by: By
    piece_id: int
    proposal: int
    automation_id: str


CueAction = Literal["play", "pause", "seek"]


@dataclass(frozen=True)
class Cue:
    """Drive the player of piece `piece_id`, a video piece: `action` play or pause (`seconds` None), or seek to
    `seconds` (0 to `embed.MAX_START`). It changes no piece and is never undone; the open screens of the bench are
    told once (`live.events.BenchCued`) and a screen that opens later is not."""

    by: By
    piece_id: int
    action: CueAction
    seconds: float | None


@dataclass(frozen=True)
class Point:
    """Highlight `passage` of piece `piece_id`, a reader piece, as it is at `base_version`; None takes the highlight
    away. It changes no piece's text, place or `changed_by`, and is never undone. The bench keeps the latest one for
    each piece, which a screen shows for as long as the piece is at that version."""

    by: By
    piece_id: int
    base_version: int
    passage: Passage | None


@dataclass(frozen=True)
class ShownRow:
    """A row of a facts piece as the person was shown it: its `name` and its value then (`facts.shown_value`)."""

    name: str
    value: str


@dataclass(frozen=True)
class Surfaced:
    """Record that `rows` of piece `piece_id`, a facts piece (choices, and guessed numbers a check rests on), were
    shown to the person beside a turn of hers, each by its name and value then. It changes no piece and is never undone.
    A row counts as shown while some accepted Surfaced names its current name and value (`workshop.BenchView.surfaced`), so a row whose value changes is
    shown again."""

    by: By
    piece_id: int
    rows: tuple[ShownRow, ...]


@dataclass(frozen=True)
class Archive:
    """Put piece `piece_id` on the bench's shelf: it leaves the layout (the pieces after it move up one) and no longer
    counts toward `max_pieces`, and keeps its text, version and runs. What is not wanted at all is a Remove."""

    by: By
    piece_id: int


@dataclass(frozen=True)
class Restore:
    """Bring piece `piece_id` back from the shelf, last on the bench at the size it had. A Move puts it elsewhere."""

    by: By
    piece_id: int


@dataclass(frozen=True)
class Undo:
    """Apply the inverse of what command `seq` did, while what it changed has not changed since. It cannot name an
    Undo (there is no redo), and a command already undone has changed since, so it is refused."""

    by: By
    seq: int


@dataclass(frozen=True)
class Rename:
    """Give the bench the title `title` (not empty, at most `title_max_chars`, kept without the space around it). It
    changes no piece."""

    by: By
    title: str


Command = Add | Remove | Move | Edit | Run | Propose | Install | Archive | Restore | Undo | Rename | Cue | Point | Surfaced
ScreenCommand = Add | Remove | Move | Edit | Undo
"""The Commands a device's screen takes (`Workshop.apply_screen`): the others are a bench's alone."""
CommandType = Literal["add", "remove", "move", "edit", "run", "propose", "install", "archive", "restore", "undo",
                      "rename", "cue", "point", "surfaced"]


def type_of(command: Command) -> CommandType:
    if isinstance(command, Add):
        return "add"
    if isinstance(command, Remove):
        return "remove"
    if isinstance(command, Move):
        return "move"
    if isinstance(command, Edit):
        return "edit"
    if isinstance(command, Run):
        return "run"
    if isinstance(command, Propose):
        return "propose"
    if isinstance(command, Install):
        return "install"
    if isinstance(command, Archive):
        return "archive"
    if isinstance(command, Restore):
        return "restore"
    if isinstance(command, Rename):
        return "rename"
    if isinstance(command, Cue):
        return "cue"
    if isinstance(command, Point):
        return "point"
    if isinstance(command, Surfaced):
        return "surfaced"
    return "undo"


@dataclass(frozen=True)
class Added:
    """`piece` came onto the bench, as it then was (its place the one it took)."""

    piece: Piece


@dataclass(frozen=True)
class Removed:
    """`piece` went off the bench, as it was just before."""

    piece: Piece


@dataclass(frozen=True)
class Edited:
    """Piece `piece_id`'s text went from `before` to `after`; `outside` when the edit was made in a turn that had read
    outside words."""

    piece_id: int
    before: Text
    after: Text
    outside: bool = False


@dataclass(frozen=True)
class Moved:
    """Piece `piece_id` went from place `before` to `after`."""

    piece_id: int
    before: Place
    after: Place


@dataclass(frozen=True)
class Ran:
    """Piece `piece_id` was run as it was at `version`. It changes no piece and is never undone."""

    piece_id: int
    version: int


@dataclass(frozen=True)
class Cued:
    """Piece `piece_id`'s player was cued: `action`, to `seconds` for a seek. It changes no piece and is never undone."""

    piece_id: int
    action: CueAction
    seconds: float | None


@dataclass(frozen=True)
class Pointed:
    """Piece `piece_id` at `version` has `passage` highlighted (None: no highlight). It changes no piece and is never
    undone."""

    piece_id: int
    version: int
    passage: Passage | None


@dataclass(frozen=True)
class Shown:
    """Choice `rows` of piece `piece_id` were shown to the person. It changes no piece and is never undone."""

    piece_id: int
    rows: tuple[ShownRow, ...]


@dataclass(frozen=True)
class Proposed:
    """Installing piece `piece_id` as it was at `version` was proposed, with its options. It changes no piece and is
    never undone."""

    piece_id: int
    version: int
    enabled: bool
    turn_off: str | None


@dataclass(frozen=True)
class Installed:
    """Piece `piece_id` as it was at `version` is to be installed under `automation_id`, `enabled` or not, turning off
    `turn_off` (None for none), as proposal `proposal` said. It changes no piece's text or place, but counts as a
    change of the piece for undo, and is undone by an `Uninstalled`."""

    piece_id: int
    version: int
    automation_id: str
    enabled: bool
    turn_off: str | None
    proposal: int


@dataclass(frozen=True)
class Uninstalled:
    """What install command `install` (of piece `piece_id`, under `automation_id`) did to the house is to be taken
    back. It changes no piece's text or place."""

    piece_id: int
    install: int
    automation_id: str


@dataclass(frozen=True)
class Archived:
    """`piece` left the layout for the shelf, as it was just before (its place the one it left)."""

    piece: Piece


@dataclass(frozen=True)
class Restored:
    """`piece` came back from the shelf onto the layout, as it then was (its place the one it took)."""

    piece: Piece


@dataclass(frozen=True)
class Renamed:
    """The bench's title went from `before` to `after`. It changes no piece."""

    before: str
    after: str


Effect = (Added | Removed | Edited | Moved | Ran | Cued | Pointed | Shown | Proposed | Installed | Uninstalled | Archived
          | Restored | Renamed)

def piece_of(effect: Effect) -> int | None:
    """The id of the piece `effect` changed, None for a `Renamed`, which changed the bench."""
    if isinstance(effect, Renamed):
        return None
    if isinstance(effect, (Added, Removed, Archived, Restored)):
        return effect.piece.id
    return effect.piece_id
