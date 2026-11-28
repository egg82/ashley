"""Wire models for the workshop (`api.benches`, `api.bench_talk`): the piece kinds, a person's benches, a bench with its
pieces and recent commands, and the commands that change it. A bench's talk uses the web chat's own models
(`ChatRequest`, `ChatReply`, `ChatConversation`)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from ..workshop import rules as workshop_rules
from ..workshop.commands import CommandType, Reason
from ..workshop.model import Size
from ..workshop.rules import BodyFormat, Family
from ..text import NoNul
from .bench_embed_models import PieceVideo
from .bench_file_models import PieceFile
from .bench_reader_models import PiecePointer, PieceReader
from .bench_recipe_models import PieceRecipe
from .bench_wake_models import PieceWake
from .bench_site_models import PieceSite
from .bench_install_models import PieceAutomation
from .bench_run_models import PieceRun
from .skill_models import WorkKind

_RULES = workshop_rules.load()
_TITLE = _RULES.title_max_chars
_BODY = max(k.max_chars for k in _RULES.kinds.values())


class PieceKind(BaseModel):
    """One kind of piece, from `kinds.json`. `family` `stored`: the body is the content; `live`: the body is a
    reference to a source the client renders. `max_chars` is the longest body a piece of it may have. `format` is how a
    stored body is written: `markdown`, `plain` (shown as typed), `code`, whose `language` names it (null otherwise),
    `automation`, Home Assistant's automation config as a JSON object (`alias`, `description`, `triggers`,
    `conditions`, `actions`, `mode`; an empty body is a draft), `site`, one https URL, or `video`, a JSON object of
    a `url` (a YouTube or Vimeo page, or a direct media file) and an optional `start` in seconds. A `live` kind's
    body is a reference, shown in a frame."""

    name: str
    family: Family
    label: str
    max_chars: int
    format: BodyFormat
    language: str | None


class LinkKind(BaseModel):
    """One kind of link between two pieces, from `workshop.json`'s `link_kinds`: a piece `from_id` is `name` (`part_of`,
    `depends_on`, `version_of`) of piece `to_id`. `label` is what a screen calls it."""

    name: str
    label: str


class WorkshopKinds(BaseModel):
    """What a bench allows, so the client hard-codes none of it: the piece kinds, the size classes a piece may take
    (`small` a quarter of the width, `medium` a half, `large` three quarters, `full` the row), the most pieces a bench
    holds and the longest title of a bench or a piece; the languages a code piece can be run in
    (`run_languages`, empty while nothing can be run) and the longest body that can be run (`run_max_chars`); and the
    kinds of link between pieces (`link_kinds`)."""

    kinds: list[PieceKind]
    link_kinds: list[LinkKind]
    sizes: list[Size]
    max_pieces: int
    title_max_chars: int
    run_languages: list[str]
    run_max_chars: int
    work_kinds: list[WorkKind]


class BenchRequest(BaseModel):
    """A bench to open, by a `title` (1 to `title_max_chars` characters, not only whitespace), an `ask` (what the person
    wants to work on: 1 to 4000 characters, not only whitespace, sent to her as their first message in the bench's
    talk, which she answers), or both. With only an ask, the title is cut from it until she names the bench; with only
    a title, no message is sent."""

    model_config = ConfigDict(extra="forbid")

    title: NoNul | None = Field(default=None, min_length=1, max_length=_TITLE, pattern=r"\S")
    ask: NoNul | None = Field(default=None, min_length=1, max_length=4000, pattern=r"\S")

    @model_validator(mode="after")
    def _names_something(self) -> "BenchRequest":
        if self.title is None and self.ask is None:
            raise ValueError("a bench is opened with a title, an ask, or both")
        return self


class BenchSummary(BaseModel):
    """One of the signed-in person's benches. `closed_at` is null while it is open. `piece_count` is the pieces on its
    layout now, its shelf not counted; `last_changed_at` is when its last accepted command was decided (a cue of a video's player or a highlight is not one),
    null for a bench nothing was done on.
    `thread` is the thread its talk is carried on, which a `LiveTurn` names when the talk got a turn."""

    id: int
    title: str
    opened_at: datetime
    closed_at: datetime | None
    work: str | None
    piece_count: int
    last_changed_at: datetime | None
    thread: str


class BenchList(BaseModel):
    """Some of the signed-in person's benches: the open ones, the most recently opened first (`GET /api/benches`), or
    the closed ones, the most recently closed first (`GET /api/benches/closed`)."""

    benches: list[BenchSummary]


class PiecePin(BaseModel):
    """Where a person fixed a piece on the bench's map: its top-left corner, in bench units, the goal centred at 0, 0."""

    model_config = ConfigDict(extra="forbid")

    x: int
    y: int


class PieceBox(BaseModel):
    """The size a person gave a piece on the bench's map, in bench units."""

    model_config = ConfigDict(extra="forbid")

    w: int
    h: int


class PiecePlace(BaseModel):
    """Where a piece sits: `order` among the bench's pieces (0 first; a bench's pieces hold exactly 0 to n-1), its
    size class, and the `pin` and `box` a person gave it on the bench's map, null until they did; a read always
    carries both. In a move, a `pin` or `box` given is set, null clears it, and one left out stays as the piece has
    it; one outside the bench's bounds is refused `bad_place`."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=0)
    size: Size
    pin: PiecePin | None = None
    box: PieceBox | None = None


class BenchPiece(BaseModel):
    """One piece of a bench, on its layout or its shelf. `id` is the `seq` of the command that added it. `piece_version` rises by one with every
    change to its title or body; an edit names the version it was based on (`base_version`). `placement` is where it
    sits (on the shelf, where it sat when archived). `changed_by` is the `seq` of the last command
    that added, edited, moved, archived or restored it, and `changed_at` and `changed_author` (`changed_person_id` for a person's, null
    for hers) are when that command was decided and who made it, however long ago. `last_run` is the piece's latest
    run, whoever ran it, null for a piece never run. `automation` is an automation piece's installing into Home
    Assistant (null for any other kind). `video` is a video piece's video, understood (null for any other kind, and
    for a video piece with no body yet). `reader` is a reader piece's page, understood (null for any other kind, and for
    a reader piece with no body yet), and `pointer` its highlight (null for none, or once the piece has changed since).
    `file` is an image or file piece's bytes, understood, with a short-lived link to them (null for any other kind).
    `site` is a site piece's address, measured (null for any other kind, and for a site piece with no address yet).
    `recipe` is a recipe piece's recipe, scaled for its headcount (null for any other kind, and for an empty body).
    `wake` is a wake rule piece's senders (null for any other kind)."""

    id: int
    kind: str
    title: str
    body: str
    piece_version: int
    placement: PiecePlace
    changed_by: int
    changed_at: datetime
    changed_author: Literal["person", "ashley"]
    changed_person_id: int | None
    last_run: PieceRun | None
    automation: PieceAutomation | None
    video: PieceVideo | None
    reader: PieceReader | None
    pointer: PiecePointer | None
    file: PieceFile | None
    site: PieceSite | None
    recipe: PieceRecipe | None
    wake: PieceWake | None


class LoggedCommand(BaseModel):
    """One command of a bench's log: `seq`, when it was decided, who made it (`author`, and `person_id` for a
    person's, null for hers), its `type`, `outcome` `accepted` or the refusal's reason, and `piece_id`, the piece it
    changed (null when refused), `undone_by`, the `seq` of the accepted Undo that took it back (null when none has), and `by_turn`, the person's turn a change of hers was made in (null for a person's change
    and for hers made outside a turn), so her changes group by turn. Never the text it carried."""

    seq: int
    at: datetime
    author: Literal["person", "ashley"]
    person_id: int | None
    type: CommandType
    outcome: Literal["accepted"] | Reason
    piece_id: int | None
    by_turn: int | None
    undone_by: int | None


class BenchLink(BaseModel):
    """Piece `from_id` is `kind` (one of `WorkshopKinds.link_kinds`) of piece `to_id`."""

    from_id: int
    kind: str
    to_id: int


class BenchDetail(BaseModel):
    """A bench as a screen shows it: the bench, its pieces in order, and its latest commands, oldest first.
    `undo_next` is the `seq` an Undo should name now (one of `recent`'s), null when there is nothing to undo. `shelf`
    is its archived pieces, the most recently archived first: off the layout, not counted toward `max_pieces`, each
    kept whole with its last run, to restore. `links` is the links between pieces on the layout, by from, kind and to;
    a link with an end removed or shelved is kept and listed again once that piece is back."""

    bench: BenchSummary
    pieces: list[BenchPiece]
    recent: list[LoggedCommand]
    undo_next: int | None
    shelf: list[BenchPiece]
    links: list[BenchLink]


class AddPieceRequest(BaseModel):
    """Add a piece of `kind` last on the bench. Its id is the command's `seq`."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["add"]
    kind: NoNul = Field(min_length=1, max_length=64)
    title: NoNul = Field(max_length=_TITLE)
    body: NoNul = Field(max_length=_BODY)
    size: Size


class RemovePieceRequest(BaseModel):
    """Take piece `piece_id` off the bench."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["remove"]
    piece_id: int


class MovePieceRequest(BaseModel):
    """Put piece `piece_id` at `placement`, an order among the pieces as they stand (the others shift)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["move"]
    piece_id: int
    placement: PiecePlace


class EditPieceRequest(BaseModel):
    """Replace piece `piece_id`'s title and body, based on its `base_version`; refused `stale_base` when another change
    came first, and nothing is merged."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["edit"]
    piece_id: int
    base_version: int
    title: NoNul = Field(max_length=_TITLE)
    body: NoNul = Field(max_length=_BODY)


class ArchivePieceRequest(BaseModel):
    """Put piece `piece_id` on the bench's shelf: it leaves the layout and the `max_pieces` count, kept whole."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["archive"]
    piece_id: int


class RestorePieceRequest(BaseModel):
    """Bring piece `piece_id` back from the shelf, last on the bench at the size it had; refused `full` when the bench
    holds `max_pieces`."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["restore"]
    piece_id: int


class InstallPieceRequest(BaseModel):
    """Approve her proposal `proposal` (`automation.install_proposal.seq` of piece `piece_id`): install the piece into Home
    Assistant as she proposed. Refused `no_proposal` when that is not the piece's proposal or was installed already,
    `stale_base` when the piece changed since. Answered once the house has been written to; how that went is the
    piece's `automation.last_install`."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["install"]
    piece_id: int
    proposal: int


class UndoRequest(BaseModel):
    """Undo command `seq`, while what it changed has not changed since. Refused `nothing_to_undo` when `seq` is an undo
    (there is no redo) or older than the bench's last `undo_window` commands, and `changed_since` when it was already
    undone. Undoing an install takes it back out of the house before it is answered (`automation.last_install` of the
    piece)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["undo"]
    seq: int


class UndoTurnRequest(BaseModel):
    """Undo together every change of the turn of hers that made command `seq`, newest first, each judged as an Undo is
    (`UndoRequest`), all or nothing: when any piece changed since, none is undone and `TurnRefused` says which."""

    model_config = ConfigDict(extra="forbid")

    seq: int


class TurnUndone(BaseModel):
    """The turn's changes are all taken back: `undone`, their `seq`s, newest first."""

    undone: list[int]


class TurnRefusal(BaseModel):
    """Command `seq` of the turn could not be undone, for `reason`."""

    seq: int
    reason: Reason


class TurnRefused(BaseModel):
    """Nothing was undone and nothing logged. `reason` is the first refusal's (`changed_since`: a piece changed after
    her turn; `nothing_to_undo`: no change of a turn there, or all already undone); `refused` lists every one."""

    code: Literal["refused"]
    reason: Reason
    refused: list[TurnRefusal]
    detail: str


class LinkRequest(BaseModel):
    """Link piece `from_id` to piece `to_id` as `kind`: both on the layout. Refused `no_such_piece` for an end that is
    not, `bad_link` for a piece linked to itself or a kind `link_kinds` does not have, `already_linked` when it is. A
    link changes neither piece: not its version, nor what it last changed by."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["link"]
    from_id: int
    kind: NoNul = Field(min_length=1, max_length=64)
    to_id: int


class UnlinkRequest(BaseModel):
    """Take away the link of `kind` from piece `from_id` to piece `to_id`; refused as a link is, and `not_linked` when
    there is no such link."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["unlink"]
    from_id: int
    kind: NoNul = Field(min_length=1, max_length=64)
    to_id: int


class ClearHighlightRequest(BaseModel):
    """Take the highlight off reader piece `piece_id`, as it is at `base_version` (a `Point` with no passage). Refused
    `not_reader` for any other piece and `stale_base` when it has changed since."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["clear_point"]
    piece_id: int
    base_version: int


class CommandRequest(RootModel[Annotated[AddPieceRequest | RemovePieceRequest | MovePieceRequest | EditPieceRequest
                                         | ArchivePieceRequest | RestorePieceRequest | InstallPieceRequest
                                         | UndoRequest | ClearHighlightRequest | LinkRequest | UnlinkRequest,
                                         Field(discriminator="type")]]):
    """One change to a bench, told apart by `type`."""


class CommandApplied(BaseModel):
    """The command was accepted as `seq`; `piece_id` is the piece it changed (for an add, the new piece; for a link or
    an unlink, its `from_id`), null for a change of the bench itself (an undo of a rename)."""

    seq: int
    piece_id: int | None


class CommandRefused(BaseModel):
    """The command was refused as `seq` and logged so; nothing on the bench changed. `reason` is why, a stable word a
    client branches on (`stale_base`: read the bench again and redo the edit on the newer version)."""

    code: Literal["refused"]
    reason: Reason
    seq: int
    detail: str
