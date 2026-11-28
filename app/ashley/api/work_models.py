"""The wire models of `/api/work`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel

from .outside_models import ActionCause, ActionUndo


WorkState = Literal["running", "waiting_on_you", "open", "done", "stopped"]
Lane = Literal["waiting", "doing", "done_untold", "would_like", "on_her_own", "kept_quiet"]
QuietWhy = Literal["quiet_hours", "not_greeting", "below_threshold", "rolled_silent", "said_none"]


class KeptQuietEntry(BaseModel):
    """One time she decided not to say something on her own: `why` is a code (`quiet_hours`, the person's own; `not_greeting`,
    a turn with no moment to score; `below_threshold`, the moment scored too low; `rolled_silent`, the seeded roll came out
    silent; `said_none`, the plan allowed it and she had nothing to say), `at` when, `cause` the record that started the
    turn. Never her words."""

    why: QuietWhy
    at: AwareDatetime
    cause: ActionCause | None = None


class KeptQuiet(BaseModel):
    """What she kept quiet for the person within the last `quiet_keep_s` (7 days): how many (`count`) and the newest
    `latest`, newest first."""

    count: int
    latest: list[KeptQuietEntry]



class ActionUndone(BaseModel):
    """That an action's Undo was taken: when it was last moved (`at`) and how it stands: `undoing`, being carried out
    now; `undone`, carried out; `waiting_on_you`, a delete proposed and waiting for the person's yes in the conversation
    the undo's answer named; `gone`, what it would take back was no longer there, so nothing was done."""

    at: AwareDatetime
    how: Literal["undoing", "undone", "waiting_on_you", "gone"]


class WorkItem(BaseModel):
    """One thing the signed-in person asked her to do or make that has not ended, or that waits on them: a `kind` of
    `errand` (asked once, held until its source answers), `open_errand` (carried out over checks), `standing_errand`
    (done each time its rule comes round, never finished), `bench` (an open bench), `watch` (a live watch she keeps),
    `proposal` (something she proposed that nobody has agreed to), `action` (a change she made for them with no one's
    OK in that turn, kept 90 days) or `kept_quiet` (one item for all she decided not to say on her own for them in the
    last 7 days, in `kept_quiet`). `id` is that record's own id (a bench's id is the workshop's `/workshop/{id}`, a
    watch's the one `DELETE /api/work/watches/{id}` cancels, a proposal's the one `POST /api/chat/agree` takes, an
    action's its `GET /api/outside-actions` id, a `kept_quiet`'s its newest entry's), `title` what it is (the person's own words, shown only to them; a
    proposal's is written by code from what it would do, an action's by code from what it did, a `kept_quiet`'s by code from its count).
    `state`: `running`, in her hands; `waiting_on_you`, only the person can move it (an install to approve, a job
    blocked on them or on their machine, a check whose words have not reached them, a proposal); `open`, a bench with
    nothing in flight; `done`, finished with its result not yet told, or an action carried out; `stopped`, an errand's check that could not be
    sent or a watch paused after failing. `lane` is where the board puts it: `waiting`, `doing`, `done_untold` or
    `would_like` (something she offered unasked), `on_her_own` (every `action`, and only those) or `kept_quiet` (every
    `kept_quiet`, and only that). It follows `state` for
    every other kind, and nothing yet marks a proposal as offered unasked, so no item is `would_like`. `at` is when it
    last moved, or when an action was made: a bench's last change (else when it opened),
    an errand's next check due or a one-shot's asking, or finishing when `done`, a watch's last wake (else when it was
    armed), a proposal's making, a `kept_quiet`'s newest entry. `until_local` is when an `open_errand` ends, as the household's wall clock
    (`YYYY-MM-DDTHH:MM`), null for any other kind, a `standing_errand` included. `conversation_id` is the conversation a
    proposal was made in, null for any other kind. `can_tap` is whether Agree is a tap (`POST /api/chat/agree`, a
    proposal of held calls); a proposal without it is agreed by answering her in that conversation. `cause` is what started
    the turn an `action` was made in and `undo` how it is taken back (None when it cannot be, and then no Undo is
    offered), both null for any other kind. `can_undo` is whether Undo is offered (`POST /api/work/actions/{id}/undo`):
    an `action` with an `undo` that was not taken. `undone` is that it was taken and how it stands, null for any other
    kind and for an action never undone. `kept_quiet` is the `kept_quiet` item's count and latest entries, null for any
    other kind."""

    kind: Literal["errand", "open_errand", "standing_errand", "bench", "watch", "proposal", "action", "kept_quiet"]
    id: int
    title: str
    state: WorkState
    lane: Lane
    at: AwareDatetime
    until_local: str | None = None
    conversation_id: int | None = None
    can_tap: bool = False
    cause: ActionCause | None = None
    undo: ActionUndo | None = None
    can_undo: bool = False
    undone: ActionUndone | None = None
    kept_quiet: KeptQuiet | None = None


class WorkResponse(BaseModel):
    """The signed-in person's open work, those waiting on them first, then running, open, stopped and done, the most
    recently moved first within each."""

    entries: list[WorkItem]


class UndoDone(BaseModel):
    """What the Undo of action `id` did, in the words of `ActionUndone.how`: `undone`, the change was taken back; `waiting_on_you`, taking it back is a
    delete, proposed for the person's yes like any delete she proposes, which they give by answering her in
    `conversation_id` (it waits in the board's `waiting` lane); `gone`, what it would take back was no longer there,
    so nothing was done. `conversation_id` is null unless `waiting_on_you`."""

    id: int
    how: Literal["undone", "waiting_on_you", "gone"]
    conversation_id: int | None


class WatchCancelled(BaseModel):
    """The watch `id` was ended by the person (`DELETE /api/work/watches/{id}`)."""

    id: int
