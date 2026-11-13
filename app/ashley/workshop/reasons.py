"""Why `decide` refuses a command: one closed set of reasons, logged with the refused command."""

from typing import Literal

Reason = Literal["unknown_kind", "bad_title", "too_long", "full", "no_such_piece", "bad_place", "stale_base",
                 "nothing_to_undo", "changed_since", "not_runnable", "bad_automation", "bad_site", "bad_video",
                 "not_installable", "incomplete", "no_proposal", "needs_person", "bad_wake", "not_video", "bad_cue",
                 "bad_reader", "not_reader", "bad_passage", "bad_file", "bad_facts", "bad_controls",
                 "bad_recipe", "already_shown", "required", "confirmed_measurement", "bad_body", "bad_citation", "bad_rows",
                 "bad_session"]
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
- `bad_session`: an Add or Edit of a session piece whose body is not empty and not a session reference
  (`workshop.session_piece`).
- `not_installable`: a Propose or Install of a piece whose kind's format is not `automation`.
- `incomplete`: a Propose of an automation with no alias, trigger or action.
- `no_proposal`: an Install naming a `seq` that is not an accepted Propose of that piece, or one an Install already
  named.
- `needs_person`: an Install, or an Undo of an install, made by her: only a person changes the house.
- `bad_wake`: an Add or Edit of a wake rule piece whose body is not empty and not a wake rule (`workshop.wake_rule`).
- `bad_facts`: an Add or Edit of a facts piece whose body is not empty and not a list of facts
  (`workshop.facts`).
- `confirmed_measurement`: an Edit by her of a facts piece that changes what a confirmed row holds (a number's
  value, unit or tolerance, a choice's value) while keeping where it came from (`workshop.facts.rewrites_confirmed`):
  a confirmed row changes only with a new answer from the person or a new source, and the row says which.
- `bad_citation`: an Add or Edit by her of a facts piece with a choice row, new or changed, whose source cites a
  piece that it does not name or that is not an image, file, reader, site or recipe piece of the bench
  (`workshop.decide.CITABLE`). Her bench tools refuse a cited turn that is not the person's on the bench's talk the same
  way, before the command is built.
- `bad_rows`: a Surfaced of a piece that is not a facts piece, or one a turn that had read outside words wrote,
  or naming no rows, a name twice, or a row that is not a choice the piece holds now under that name and value.
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
                               "bad_wake", "not_video", "bad_cue", "bad_reader", "not_reader", "bad_passage", "bad_file", "bad_facts",
                               "bad_controls", "bad_recipe", "already_shown", "required", "confirmed_measurement", "bad_body",
                               "bad_citation", "bad_rows")
