"""Every change to a bench is one of these Commands (GoF Command): frozen records in one closed union, each naming who
made it (`by`), decided by `decide.decide` against the bench into an accepted change or a typed refusal, and logged
whichever it was. `seq` numbers a bench's commands 1, 2, 3... in the order they were decided, refused ones included.

What an accepted command did is its Effect, which is what Undo inverts."""

from dataclasses import dataclass
from typing import Literal

from .model import By, Piece, Place, Size, Text
from .reader import Passage


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


Command = Add | Remove | Move | Edit | Run | Propose | Install | Archive | Restore | Undo | Rename | Cue | Point
ScreenCommand = Add | Remove | Move | Edit | Undo
"""The Commands a device's screen takes (`Workshop.apply_screen`): the others are a bench's alone."""
CommandType = Literal["add", "remove", "move", "edit", "run", "propose", "install", "archive", "restore", "undo",
                      "rename", "cue", "point"]


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


Effect = (Added | Removed | Edited | Moved | Ran | Cued | Pointed | Proposed | Installed | Uninstalled | Archived | Restored
          | Renamed)

Reason = Literal["unknown_kind", "bad_title", "too_long", "full", "no_such_piece", "bad_place", "stale_base",
                 "nothing_to_undo", "changed_since", "not_runnable", "bad_automation", "bad_site", "bad_video",
                 "not_installable", "incomplete", "no_proposal", "needs_person", "bad_wake", "not_video", "bad_cue",
                 "bad_reader", "not_reader", "bad_passage", "bad_file", "bad_measurements", "bad_controls",
                 "bad_recipe", "already_shown", "required", "confirmed_measurement", "bad_body", "bad_citation"]
"""Why a command was refused:
- `unknown_kind`: an Add of a kind `kinds.json` does not have.
- `bad_title`: a title (a piece's, or a Rename's) empty, only whitespace, or longer than `title_max_chars`.
- `too_long`: a body longer than its kind's `max_chars`.
- `full`: an Add, a Restore, or an Undo that would bring a piece back, on a bench already holding `max_pieces`.
- `no_such_piece`: a Remove, Move, Edit, Run or Archive of a piece not on the bench's layout (a shelved piece is not),
  or a Restore of one not on its shelf.
- `bad_place`: a Move to an order past the last piece's.
- `stale_base`: an Edit, Run, Propose or Point whose `base_version` is not the piece's current version, or an Install whose
  proposal was of an earlier version.
- `nothing_to_undo`: an Undo naming a command that was refused, is an Undo, a Run or a Propose, is not earlier than
  it, is older than the last `undo_window` commands, or does not exist.
- `changed_since`: an Undo whose command's piece has been changed by a later command, or (for a Remove) is back.
- `not_runnable`: a Run of a piece whose kind's format is not `code`.
- `bad_automation`: an Add or Edit of an automation piece whose body is not empty and not an automation config
  (`workshop.automation_config`).
- `bad_site`: an Add or Edit of a site piece whose body is not empty and not one https URL, or is a YouTube or Vimeo
  page, which is a video piece (`workshop.embed`).
- `bad_video`: an Add or Edit of a video piece whose body is not empty and not a video body (`workshop.embed`).
- `not_installable`: a Propose or Install of a piece whose kind's format is not `automation`.
- `incomplete`: a Propose of an automation with no alias, trigger or action.
- `no_proposal`: an Install naming a `seq` that is not an accepted Propose of that piece, or one an Install already
  named.
- `needs_person`: an Install, or an Undo of an install, made by her: only a person changes the house.
- `bad_wake`: an Add or Edit of a wake rule piece whose body is not empty and not a wake rule (`workshop.wake_rule`).
- `bad_measurements`: an Add or Edit of a measurements piece whose body is not empty and not a list of measurements
  (`workshop.measurements`).
- `confirmed_measurement`: an Edit by her of a measurements piece that changes what a confirmed row holds (a number's
  value, unit or tolerance, a choice's value) while keeping where it came from (`workshop.measurements.rewrites_confirmed`):
  a confirmed row changes only with a new answer from the person or a new source, and the row says which.
- `bad_citation`: an Add or Edit by her of a measurements piece with a choice row, new or changed, whose source cites a
  piece that it does not name or that is not an image, file, reader, site or recipe piece of the bench
  (`workshop.decide.CITABLE`). Her bench tools refuse a cited turn that is not the person's on the bench's talk the same
  way, before the command is built.
- `not_video`: a Cue of a piece whose kind's format is not `video`, `clip` or `audio`.
- `bad_cue`: a Cue to seek without `seconds` or with `seconds` not in 0 to `embed.MAX_START`, or to play or pause with
  `seconds`.
- `bad_reader`: an Add or Edit of a reader piece whose body is not empty and not a page (`workshop.reader`).
- `bad_recipe`: an Add or Edit of a recipe piece whose body is not empty and not a recipe (`workshop.recipe`).
- `not_reader`: a Point at a piece whose kind's format is not `reader`.
- `bad_passage`: a Point whose passage is not a non-empty range inside one paragraph of the piece's text.
- `bad_file`: an Add of a large piece (kind `image`, `clip`, `audio` or `file`) whose body is not a stored file of the right sort
  (`workshop.stored_file`), or an Edit of one that changes its body: a large piece's bytes are fixed, its title is not.
- `bad_controls`: an Add or Edit of a controls piece (a screen's) whose body is not a list of controls
  (`workshop.screen_controls.well_formed`; an empty body is not one).
- `bad_body`: an Add or Edit, or an Undo of an Edit, of a `by_code` kind's piece not made by the jobs' runner
  (`rules.Kind.by_code`), or by it with a body that is not that kind's (`workshop.job_body`).
- `already_shown`: an Add, or an Undo bringing a piece back, of a kind the layout already holds, under rules with
  `one_each`.
- `required`: a Remove, Archive or Undo that would leave no piece of a kind in `rules.required`."""

REASONS: tuple[Reason, ...] = ("unknown_kind", "bad_title", "too_long", "full", "no_such_piece", "bad_place",
                               "stale_base", "nothing_to_undo", "changed_since", "not_runnable", "bad_automation",
                               "bad_site", "bad_video", "not_installable", "incomplete", "no_proposal", "needs_person",
                               "bad_wake", "not_video", "bad_cue", "bad_reader", "not_reader", "bad_passage", "bad_file", "bad_measurements",
                               "bad_controls", "bad_recipe", "already_shown", "required", "confirmed_measurement", "bad_body",
                               "bad_citation")


def piece_of(effect: Effect) -> int | None:
    """The id of the piece `effect` changed, None for a `Renamed`, which changed the bench."""
    if isinstance(effect, Renamed):
        return None
    if isinstance(effect, (Added, Removed, Archived, Restored)):
        return effect.piece.id
    return effect.piece_id
