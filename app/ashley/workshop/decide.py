"""The one place a bench changes: `decide`, a pure function of the bench's state, one command and the rules, answering
the bench's next state with the command accepted (and what it did) or refused (and why). Nothing here reads a clock,
a database or a random number, so replaying a bench's log from `EMPTY` through `decide` reproduces the bench, and the
same outcome for every command in it, refusals included (`replay`)."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from . import (automation_config, embed, job_body, facts, reader, recipe, screen_controls, stored_file, surfacing,
               wake_rule)
from .commands import (Add, Added, Archive, Archived, Command, Cue, Cued, Edit, Edited, Effect, Install, Installed, Move, Moved,
                       Point, Pointed, Propose, Proposed, Ran, Reason, Remove, Removed, Rename, Renamed, Restore, Restored, Run,
                       Shown, Surfaced, Undo)
from .effects import apply, inverse, shelved, titled
from .model import By, Piece, Place, Text
from .rules import BodyFormat, Kind, Rules


@dataclass(frozen=True)
class BenchState:
    """What `decide` judges a command against. `pieces` in order: `pieces[i].place.order == i`. `next_seq` is the
    `seq` the next command gets, 1 on an empty bench. `effects` holds what each accepted command did, by its `seq`;
    `undos` maps the `seq` of every accepted Undo to the `seq` it undid. `decide` reads both only for an Undo, and only
    the entries at or after the `seq` it names that touch that command's piece, and for an Install, the entries of its
    piece from the proposal it names on, so a caller holding the bench elsewhere may pass just those. `shelf` is the archived pieces, the most recently archived first, each at the place it left;
    it is passed whole. `title` is the bench's title as it stands, which a Rename records as what it replaced."""

    pieces: tuple[Piece, ...] = ()
    next_seq: int = 1
    effects: Mapping[int, Effect] = field(default_factory=lambda: MappingProxyType({}))
    undos: Mapping[int, int] = field(default_factory=lambda: MappingProxyType({}))
    shelf: tuple[Piece, ...] = ()
    title: str = ""

    def piece(self, piece_id: int) -> Piece | None:
        return next((p for p in self.pieces if p.id == piece_id), None)


EMPTY = BenchState()


@dataclass(frozen=True)
class Accepted:
    """The command was applied as `seq`: `effect` is what it did, `state` the bench after it."""

    seq: int
    effect: Effect
    state: BenchState


@dataclass(frozen=True)
class Refused:
    """The command was refused as `seq` for `reason`. `state` is the bench unchanged but for `next_seq`, which a
    refusal uses up as an acceptance does."""

    seq: int
    reason: Reason
    state: BenchState


Decision = Accepted | Refused
PLAYED: tuple[BodyFormat, ...] = ("video", "clip", "audio")
"""The formats of the pieces a Cue drives: an embedded video, a video file, an audio file."""
CITABLE: tuple[BodyFormat, ...] = ("image", "file", "reader", "site", "recipe")
"""The formats of the pieces a facts choice row may name as where it was seen or published."""

# The body formats code checks on every Add and Edit, and the refusal for a body that is not empty and fails the check.
_BODIES: Mapping[BodyFormat, tuple[Callable[[str], bool], Reason]] = MappingProxyType({
    "automation": (automation_config.well_formed, "bad_automation"),
    "wake": (wake_rule.well_formed, "bad_wake"),
    "facts": (facts.well_formed, "bad_facts"),
    "site": (embed.site_well_formed, "bad_site"),
    "video": (embed.video_well_formed, "bad_video"),
    "reader": (reader.well_formed, "bad_reader"),
    "recipe": (recipe.well_formed, "bad_recipe"),
    "image": (stored_file.image_well_formed, "bad_file"),
    "clip": (stored_file.clip_well_formed, "bad_file"),
    "audio": (stored_file.audio_well_formed, "bad_file"),
    "file": (stored_file.file_well_formed, "bad_file"),
    "controls": (screen_controls.well_formed, "bad_controls"),
    "job": (job_body.well_formed, "bad_body"),
})


def decide(state: BenchState, command: Command, rules: Rules) -> Decision:
    """Judge `command` against `state` under `rules`. When several reasons apply, the first that fails, in this order:
    - Add: `unknown_kind`, `bad_title`, `too_long`, `bad_controls`, a body check below, `bad_citation` (hers only),
      `already_shown`, `full`. The piece goes last, its id the command's `seq`, version 1.
    - Remove: `no_such_piece`, `required`.
    - Move: `no_such_piece`, `bad_place` (an order past the last piece's).
    - Edit: `no_such_piece`, `unknown_kind` (the piece's kind has left the rules), `stale_base`,
      `bad_title`, `too_long`, then a body check below, then `confirmed_measurement` and `bad_citation` (hers only). The
      version rises by one.
    - Run: `no_such_piece`, `unknown_kind`, `not_runnable` (its kind's format is not `code`), `stale_base`. Its
      effect, `Ran`, changes no piece: not its version, place or `changed_by`.
    - Propose: `no_such_piece`, `unknown_kind`, `not_installable` (its kind's format is not `automation`),
      `stale_base`, `incomplete` (`automation_config.complete`). Its effect, `Proposed`, changes no piece.
    - Install: `needs_person` (made by her), `no_such_piece`, `unknown_kind`, `not_installable`, `no_proposal` (the
      `seq` named is not an accepted Propose of this piece, or an Install named it already), `stale_base` (the piece
      has changed since the proposal). Its effect, `Installed`, carries the proposal's options and changes no piece's
      text or place.
    - Cue: `no_such_piece`, `unknown_kind`, `not_video` (its kind's format is not one of `PLAYED`), `bad_cue` (a seek without
      `seconds` or outside 0 to `embed.MAX_START`, a play or pause with `seconds`). Its effect, `Cued`, changes no
      piece.
    - Point: `no_such_piece`, `unknown_kind`, `not_reader` (its kind's format is not `reader`), `stale_base`,
      `bad_passage` (a passage that is not a non-empty range inside one paragraph of the piece's text; none is allowed
      and takes the highlight away). Its effect, `Pointed`, changes no piece.
    - Surfaced: `no_such_piece`, then `surfacing.judged`'s (`unknown_kind`, `bad_rows`). Its effect, `Shown`, changes no piece.
    - Rename: `bad_title`. Its effect, `Renamed`, changes no piece.
    - Archive: `no_such_piece` (not on the layout), `required`. The piece goes to the front of the shelf, the others move up.
    - Restore: `no_such_piece` (not on the shelf), `full`. The piece goes last, at the size it had.
    - Undo: `nothing_to_undo` (an Undo cannot be undone: there is no redo; nor can a Run, which ran, a Propose, a Cue, a Point or a Surfaced; nor
      can a command older than the last `rules.undo_window` commands, refusals and Undos counted:
      `seq < next_seq - undo_window`), `needs_person` (her Undo of an Install), `changed_since`
      (a command already undone,
      or one whose piece a later command changed and no undo took back), then `required` (the inverse would leave no
      piece of a required kind) or `already_shown` (it would bring back a kind the layout holds, under `one_each`),
      then `full`. Undoing an Add removes the piece; a Remove brings the piece back as it was, at its
      old order or last when fewer pieces remain; an Edit restores the earlier text (the version still rises); a Move
      returns the piece to its earlier place (or last); an Archive restores the piece to its old order (or last); a
      Restore archives it again; an Install is taken back by an `Uninstalled` naming it; a Rename by a `Renamed` back to
      the title it replaced.
    Add and Edit of a `by_code` kind's piece (`job`) are refused `bad_body` unless the jobs' runner (`By.runner`) made
    them, and its body must be that kind's (`job_body`); so is an Undo of such an Edit by anyone else.
    A large piece's (`image`, `file`) body must be a stored file (`stored_file`), `bad_file` otherwise, and an Edit
    may not change it (`bad_file`, after the other Edit refusals).
    A title is refused when empty, only whitespace or longer than `rules.title_max_chars`; a body may be empty. An
    automation piece's body that is not empty is refused `bad_automation` (after `too_long`) unless it is an
    automation config (`automation_config.well_formed`), a wake rule's `bad_wake` unless it is a rule
    (`wake_rule.well_formed`), a facts piece's `bad_facts` unless it is a list of facts
    (`facts.well_formed`), a site's `bad_site` unless one https URL that is not a video page, a video's
    `bad_video` unless a video body
    (`embed`). Her Add or Edit of a facts piece is refused `bad_citation` when a choice row it adds or changes
    with a source that cites a piece (`facts.cited_pieces`) names none, or names one that is not a piece on the
    layout or the shelf of a kind whose format is in `CITABLE`."""
    seq = state.next_seq
    checked = _effect_of(state, command, rules, seq)
    after = replace(state, next_seq=seq + 1)
    if isinstance(checked, str):
        return Refused(seq, checked, after)
    effects = MappingProxyType({**state.effects, seq: checked})
    undos = MappingProxyType({**state.undos, seq: command.seq}) if isinstance(command, Undo) else state.undos
    return Accepted(seq, checked, replace(after, pieces=apply(state.pieces, checked, seq),
                                          shelf=shelved(state.shelf, checked, seq), effects=effects, undos=undos,
                                          title=titled(state.title, checked)))


def replay(commands: Iterable[Command], rules: Rules, title: str = "") -> list[Decision]:
    """Every command decided in turn from `EMPTY` under the bench's opening `title` (a Rename records the title it
    replaced, so replay needs the one the bench opened with); the last decision's `state` is the bench."""
    state = replace(EMPTY, title=title)
    out: list[Decision] = []
    for command in commands:
        decision = decide(state, command, rules)
        out.append(decision)
        state = decision.state
    return out


def _effect_of(state: BenchState, command: Command, rules: Rules, seq: int) -> Effect | Reason:
    if isinstance(command, Add):
        return _add(state, command, rules, seq)
    if isinstance(command, Undo):
        return _undo(state, command, rules, seq)
    if isinstance(command, Restore):
        return _restore(state, command, rules, seq)
    if isinstance(command, Rename):
        return _rename(state, command, rules)
    if isinstance(command, Install) and command.by.person_id is None:
        return "needs_person"
    piece = state.piece(command.piece_id)
    if piece is None:
        return "no_such_piece"
    if isinstance(command, Remove):
        return "required" if _last_required(state, piece, rules) else Removed(piece)
    if isinstance(command, Archive):
        return "required" if _last_required(state, piece, rules) else Archived(piece)
    if isinstance(command, Move):
        if command.place.order >= len(state.pieces):
            return "bad_place"
        return Moved(piece.id, piece.place, command.place)
    if isinstance(command, Run):
        return _run(piece, command, rules)
    if isinstance(command, Propose):
        return _propose(piece, command, rules)
    if isinstance(command, Cue):
        return _cue(piece, command, rules)
    if isinstance(command, Point):
        return _point(piece, command, rules)
    if isinstance(command, Surfaced):
        return surfacing.judged(piece, command, rules)
    if isinstance(command, Install):
        return _install(state, piece, command, rules)
    return _edit(state, piece, command, rules)


def _last_required(state: BenchState, piece: Piece, rules: Rules) -> bool:
    """Whether `piece` is the only piece on the layout of a kind the rules require."""
    return piece.kind in rules.required and sum(p.kind == piece.kind for p in state.pieces) <= 1


def _rename(state: BenchState, command: Rename, rules: Rules) -> Effect | Reason:
    title = command.title.strip()
    return "bad_title" if not title or len(title) > rules.title_max_chars else Renamed(state.title, title)


def _text_refusal(text: Text, kind: Kind, rules: Rules) -> Reason | None:
    if not text.title.strip() or len(text.title) > rules.title_max_chars:
        return "bad_title"
    if len(text.body) > kind.max_chars:
        return "too_long"
    checked = _BODIES.get(kind.format)
    if checked is not None and not checked[0](text.body):
        return checked[1]
    return None


def _stored(text: Text, kind: Kind) -> Text:
    """`text` as it is stored: a site's or video's body without the whitespace around it (and a video's url too)."""
    if kind.format == "site":
        return replace(text, body=embed.trimmed(text.body))
    return replace(text, body=embed.trimmed_video(text.body)) if kind.format == "video" else text


def _add(state: BenchState, command: Add, rules: Rules, seq: int) -> Effect | Reason:
    kind = rules.kinds.get(command.kind)
    if kind is None:
        return "unknown_kind"
    if kind.by_code and not command.by.runner:
        return "bad_body"
    text = _stored(command.text, kind)
    refused = _text_refusal(text, kind, rules)
    if refused is None:
        refused = _citation(state, "", text.body, command.by, kind, rules)
    if refused is not None:
        return refused
    if rules.one_each and any(p.kind == kind.name for p in state.pieces):
        return "already_shown"
    if len(state.pieces) >= rules.max_pieces:
        return "full"
    return Added(Piece(seq, kind.name, text, 1, Place(len(state.pieces), command.size), seq, command.by.outside))


def _citation(state: BenchState, before: str, after: str, by: By, kind: Kind, rules: Rules) -> Reason | None:
    """`bad_citation` for her facts body naming a piece that is not a source on this bench (`decide`)."""
    if kind.format != "facts" or by.person_id is not None:
        return None
    held = {p.id: p for p in (*state.pieces, *state.shelf)}
    for cited in facts.cited_pieces(before, after):
        found = None if cited is None else held.get(cited)
        source = None if found is None else rules.kinds.get(found.kind)
        if source is None or source.format not in CITABLE:
            return "bad_citation"
    return None


def _edit(state: BenchState, piece: Piece, command: Edit, rules: Rules) -> Effect | Reason:
    kind = rules.kinds.get(piece.kind)
    if kind is None:
        return "unknown_kind"
    if kind.by_code and not command.by.runner:
        return "bad_body"
    if command.base_version != piece.version:
        return "stale_base"
    text = _stored(command.text, kind)
    refused = _text_refusal(text, kind, rules)
    if refused is None and kind.family == "large" and text.body != piece.text.body:
        return "bad_file"
    if refused is None and kind.format == "facts" and command.by.person_id is None and (
            facts.rewrites_confirmed(piece.text.body, text.body)):
        return "confirmed_measurement"
    if refused is None:
        refused = _citation(state, piece.text.body, text.body, command.by, kind, rules)
    return refused if refused is not None else Edited(piece.id, piece.text, text, command.by.outside)


def _run(piece: Piece, command: Run, rules: Rules) -> Effect | Reason:
    kind = rules.kinds.get(piece.kind)
    if kind is None:
        return "unknown_kind"
    if kind.format != "code":
        return "not_runnable"
    return "stale_base" if command.base_version != piece.version else Ran(piece.id, piece.version)


def _cue(piece: Piece, command: Cue, rules: Rules) -> Effect | Reason:
    kind = rules.kinds.get(piece.kind)
    if kind is None:
        return "unknown_kind"
    if kind.format not in PLAYED:
        return "not_video"
    seconds = command.seconds
    seeking = command.action == "seek"
    if seeking != (seconds is not None) or (seconds is not None and not 0 <= seconds <= embed.MAX_START):
        return "bad_cue"
    return Cued(piece.id, command.action, seconds)


def _point(piece: Piece, command: Point, rules: Rules) -> Effect | Reason:
    kind = rules.kinds.get(piece.kind)
    if kind is None:
        return "unknown_kind"
    if kind.format != "reader":
        return "not_reader"
    if command.base_version != piece.version:
        return "stale_base"
    page = reader.page_of(piece.text.body)
    if command.passage is not None and (page is None or not reader.holds(page, command.passage)):
        return "bad_passage"
    return Pointed(piece.id, piece.version, command.passage)


def _installable(piece: Piece, rules: Rules) -> Reason | None:
    kind = rules.kinds.get(piece.kind)
    if kind is None:
        return "unknown_kind"
    return "not_installable" if kind.format != "automation" else None


def _propose(piece: Piece, command: Propose, rules: Rules) -> Effect | Reason:
    refused = _installable(piece, rules)
    if refused is not None:
        return refused
    if command.base_version != piece.version:
        return "stale_base"
    if not automation_config.complete(piece.text.body):
        return "incomplete"
    return Proposed(piece.id, piece.version, command.enabled, command.turn_off)


def _install(state: BenchState, piece: Piece, command: Install, rules: Rules) -> Effect | Reason:
    refused = _installable(piece, rules)
    if refused is not None:
        return refused
    proposal = state.effects.get(command.proposal)
    taken = any(isinstance(e, Installed) and e.proposal == command.proposal for e in state.effects.values())
    if not isinstance(proposal, Proposed) or proposal.piece_id != piece.id or taken:
        return "no_proposal"
    if proposal.version != piece.version:
        return "stale_base"
    return Installed(piece.id, piece.version, command.automation_id, proposal.enabled, proposal.turn_off,
                     command.proposal)


def _by_code(state: BenchState, piece_id: int, rules: Rules) -> bool:
    """Whether piece `piece_id` is of a kind only the jobs' runner changes."""
    piece = state.piece(piece_id)
    kind = None if piece is None else rules.kinds.get(piece.kind)
    return kind is not None and kind.by_code


def _restore(state: BenchState, command: Restore, rules: Rules, seq: int) -> Effect | Reason:
    kept = next((p for p in state.shelf if p.id == command.piece_id), None)
    if kept is None:
        return "no_such_piece"
    if len(state.pieces) >= rules.max_pieces:
        return "full"
    return Restored(replace(kept, place=replace(kept.place, order=len(state.pieces)), changed_by=seq))


def _undo(state: BenchState, command: Undo, rules: Rules, seq: int) -> Effect | Reason:
    reachable = seq - rules.undo_window <= command.seq < seq and command.seq not in state.undos
    done = state.effects.get(command.seq) if reachable else None
    if done is None or isinstance(done, (Ran, Proposed, Cued, Pointed, Shown)):
        return "nothing_to_undo"
    if isinstance(done, Installed) and command.by.person_id is None:
        return "needs_person"
    if isinstance(done, Edited) and not command.by.runner and _by_code(state, done.piece_id, rules):
        return "bad_body"
    undone = inverse(done, state.pieces, state.shelf, state.title, state.effects, state.undos, command.seq, seq)
    if undone is None:
        return "changed_since"
    if isinstance(undone, (Removed, Archived)) and _last_required(state, undone.piece, rules):
        return "required"
    if isinstance(undone, (Added, Restored)):
        if rules.one_each and any(p.kind == undone.piece.kind for p in state.pieces):
            return "already_shown"
        if len(state.pieces) >= rules.max_pieces:
            return "full"
    return undone

