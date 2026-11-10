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


class WorkshopKinds(BaseModel):
    """What a bench allows, so the client hard-codes none of it: the piece kinds, the size classes a piece may take
    (`small` a quarter of the width, `medium` a half, `large` three quarters, `full` the row), the most pieces a bench
    holds and the longest title of a bench or a piece; and the languages a code piece can be run in
    (`run_languages`, empty while nothing can be run) and the longest body that can be run (`run_max_chars`)."""

    kinds: list[PieceKind]
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


class PiecePlace(BaseModel):
    """Where a piece sits: `order` among the bench's pieces (0 first; a bench's pieces hold exactly 0 to n-1) and its
    size class."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=0)
    size: Size


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
    `recipe` is a recipe piece's recipe, scaled for its headcount (null for any other kind, and for an empty body)."""

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


class LoggedCommand(BaseModel):
    """One command of a bench's log: `seq`, when it was decided, who made it (`author`, and `person_id` for a
    person's, null for hers), its `type`, `outcome` `accepted` or the refusal's reason, and `piece_id`, the piece it
    changed (null when refused). Never the text it carried."""

    seq: int
    at: datetime
    author: Literal["person", "ashley"]
    person_id: int | None
    type: CommandType
    outcome: Literal["accepted"] | Reason
    piece_id: int | None


class BenchDetail(BaseModel):
    """A bench as a screen shows it: the bench, its pieces in order, and its latest commands, oldest first.
    `undo_next` is the `seq` an Undo should name now (one of `recent`'s), null when there is nothing to undo. `shelf`
    is its archived pieces, the most recently archived first: off the layout, not counted toward `max_pieces`, each
    kept whole with its last run, to restore."""

    bench: BenchSummary
    pieces: list[BenchPiece]
    recent: list[LoggedCommand]
    undo_next: int | None
    shelf: list[BenchPiece]


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


class ClearHighlightRequest(BaseModel):
    """Take the highlight off reader piece `piece_id`, as it is at `base_version` (a `Point` with no passage). Refused
    `not_reader` for any other piece and `stale_base` when it has changed since."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["clear_point"]
    piece_id: int
    base_version: int


class CommandRequest(RootModel[Annotated[AddPieceRequest | RemovePieceRequest | MovePieceRequest | EditPieceRequest
                                         | ArchivePieceRequest | RestorePieceRequest | InstallPieceRequest
                                         | UndoRequest | ClearHighlightRequest,
                                         Field(discriminator="type")]]):
    """One change to a bench, told apart by `type`."""


class CommandApplied(BaseModel):
    """The command was accepted as `seq`; `piece_id` is the piece it changed (for an add, the new piece), null for a
    change of the bench itself (an undo of a rename)."""

    seq: int
    piece_id: int | None


class CommandRefused(BaseModel):
    """The command was refused as `seq` and logged so; nothing on the bench changed. `reason` is why, a stable word a
    client branches on (`stale_base`: read the bench again and redo the edit on the newer version)."""

    code: Literal["refused"]
    reason: Reason
    seq: int
    detail: str
