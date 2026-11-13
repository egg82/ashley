"""What a bench tool call returns to the model, and its `tools.call` line: the tool, bench, command type, seq, piece id
and outcome, never a title or a body."""

import json
import logging
import time

from .. import logs
from ..inference.model import ToolCall, ToolResult
from ..workshop.commands import Reason

log = logging.getLogger("ashley.tools")

# Not a workshop Reason: a NUL never becomes a command, the Workshop raises ValueError first.
BAD_TEXT_HINT = "a title or body may not hold a NUL character"

HINTS: dict[Reason, str] = {
    "unknown_kind": "that kind of piece does not exist; bench_read lists the kinds",
    "bad_title": "a title is not empty and not longer than the bench allows",
    "too_long": "the body is longer than its kind allows; bench_read lists each kind's max_chars",
    "full": "the bench holds as many pieces as it can; archive or remove one first",
    "no_such_piece": "no piece with that id is on the bench (or, to restore, on its shelf); read it again",
    "bad_place": "that order is past the last piece",
    "stale_base": "the piece changed since you read it: read it again and redo your edit on what is there now",
    "nothing_to_undo": ("that seq is not a recent change the bench accepted: an undo cannot be undone, nor a change among the bench's "
                       "older commands; undo_next in bench_read names one that can"),
    "changed_since": "what that change touched has changed since, so it cannot be undone",
    "not_runnable": "only a code piece can be run",
    "bad_automation": "an automation piece's body is Home Assistant's automation config as one JSON object (alias, "
                      "description, triggers, conditions, actions, mode), with no id; house_automation gives one",
    "bad_site": "a site piece's body is one https URL and nothing else, and not a YouTube or Vimeo page: a video is a "
                'video piece with body {"url": <the video\'s watch URL>}',
    "bad_video": 'a video piece\'s body is a JSON object like {"url": "https://www.youtube.com/watch?v=...", "start": 90} '
                 "(start optional, whole seconds): the page of one specific video on YouTube or Vimeo (never a search, channel or "
                 "playlist page: find the video first), or a direct .mp4/.webm/.ogv/.m4v/.mov file",
    "not_installable": "only an automation piece can be installed",
    "incomplete": "it needs an alias, at least one trigger and at least one action before it can be installed",
    "no_proposal": "that is not a proposal of this piece waiting to be installed",
    "needs_person": "only the person installs an automation or undoes an install: ask them to, on the piece",
    "bad_wake": "a wake rule's body is one JSON object of exactly event (the slug its wake action sends), brief (what "
                "to do on that wake, short) and tools (the names that turn may use), and optionally greets (true or "
                "false; true when the wake is a greeting, so code decides whether and how fully to say it; absent or "
                "false, what you write goes out when you say it is worth saying), who (a person.* entity id) and what "
                "(a slug): set, the rule answers only a wake whose who or what is exactly that; when several rules "
                "answer one wake, the one setting the most of who and what runs, and a tie runs none)",
    "bad_measurements": 'a measurements piece\'s body is {"items": [{"name", "value", "unit", "source", "tolerance", "ref", "asked"}]}: '
                        "name an identifier unique in the piece, value a finite number, unit mm (every length in millimetres), deg, "
                        "count, g (grams), ml (millilitres) or min (minutes), source measured, datasheet, accepted, bound or guessed, "
                        "tolerance an optional ± of 0 or more (above 0 on a bound row), ref optional text up to 200 characters, "
                        "asked an optional true or false on a guessed row only, given optionally the name of a choice row in the "
                        "same piece that the number belongs to. A choice row is "
                        '{"kind": "choice", "name", "label", "value", "options", "source", "turn", "piece", "ref"}: label (up to 60 '
                        "characters) and value (up to 80) plain words, options optionally 2 to 6 such values with value one of "
                        "them, source stated, seen, datasheet, accepted or guessed, turn (the person's turn that says it) only with "
                        "stated or accepted, piece (the bench piece it comes from) only with seen or datasheet",
    "confirmed_measurement": "that edit changes the number or choice of a row whose source is not guessed and keeps where it "
                             "came from (a number's source and ref, a choice's source, turn and piece): a confirmed row "
                             "changes only when the person gives a new answer or a new source exists, and the row then says "
                             "which; otherwise leave the row as it was",
    "bad_citation": "a choice row that is stated or accepted names in turn the person's turn in this talk that says it, and "
                    "one that is seen or datasheet names in piece the image, file, reader, site or recipe piece on this "
                    "bench it comes from; if nothing the person said or no piece settles it, its source is guessed",
    "not_video": "only a video, clip or audio piece has a player to cue",
    "bad_reader": "a reader piece is put up by result, the number of a page that was read; its body is not written by hand",
    "bad_recipe": "a recipe piece is put up by result, the number of a page that was read, with serves; its body is not written by hand",
    "not_reader": "only a reader piece has a page to highlight",
    "bad_passage": "that is not a passage of the piece's text; copy a quote from bench_read_piece",
    "bad_file": "an image or file piece is made from bytes (a person's upload, or bench_add_file for what you made), and "
                "its content is never edited, only its title",
    "bad_controls": "a controls piece's body is a list of at most 12 buttons, each an id, label (1 to 40 characters), action "
                    "and entity_id; screen_buttons builds it",
    "already_shown": "the screen already has a piece of that kind: move or resize it instead",
    "required": "the screen always keeps its conversation, so the hall can ask you to put things back",
    "bad_body": "a job piece is written by the jobs' runner alone: it is neither added nor edited by hand; a job is "
                "handed off with bench_hand_off and cancelled with bench_job_cancel",
    "bad_cue": "seek takes seconds from the start, 0 or more and under 100 hours; play and pause take none",
    "bad_rows": "only a measurements piece's current choice rows can be shown, each once; read the piece again",
}


def ok(call: ToolCall, started: float, body: dict[str, object], *, outside: bool | None = None,
       **fields: object) -> ToolResult:
    """A success result of `body`; `outside` is `ToolResult.outside`."""
    _logged(call, started, "ok", fields)
    return ToolResult(call.id, json.dumps(body, ensure_ascii=False), outside=outside)


def failed(call: ToolCall, started: float, outcome: str, reason: str, **fields: object) -> ToolResult:
    """An error result saying `outcome` and `reason`, which name no argument value."""
    _logged(call, started, outcome, fields)
    return ToolResult(call.id, f"{outcome}: {reason}", is_error=True)


def _logged(call: ToolCall, started: float, outcome: str, fields: dict[str, object]) -> None:
    logs.info(log, "tools.call", tool=call.name, outcome=outcome, **fields,
              duration_ms=int((time.monotonic() - started) * 1000))
