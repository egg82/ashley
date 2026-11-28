"""The wire models of `/api/outside-actions`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel


class ActionCause(BaseModel):
    """What started the turn a change was made in, by the record it names: `wake` (a household event's wake), `reminder`,
    `open_errand` or `standing_errand` (that occurrence's wake id, as `/api/work` lists the errand), `watch` (the watch's
    id), `bench` (the bench whose owner's changes she reacted to, `/workshop/{id}`) or `turn` (the person's own turn,
    which read words written outside the household)."""

    kind: Literal["wake", "reminder", "open_errand", "standing_errand", "watch", "bench", "turn"]
    id: int


class ActionUndo(BaseModel):
    """What takes a change back: `kind` is the inverse (`house_delete` the house's `within` kind of thing `ref` she
    created; `reminder_cancel` the reminder whose id is `ref`; `todo_remove`, `todo_done` or `todo_reopen` the item `ref`,
    its id or exact text, on the to-do list `within`), `within` None where the kind needs no place."""

    kind: Literal["house_delete", "reminder_cancel", "todo_remove", "todo_done", "todo_reopen"]
    ref: str
    within: str | None


class OutsideAction(BaseModel):
    """A change she made for the signed-in person with no OK in that turn: in a turn that had read words written outside
    the household, or in one no person's message started (a wake, a reminder or errand round, a watch, a bench's
    reaction). `label` is the plain headline the person was shown for it, None for one made before headlines were kept;
    `summary` is code's plain-words account of the change, never her words. `tier`: `runs`, a change that ran without
    the action judge (every change of a turn that read no outside words); `judged`, one the action judge let run.
    `explanation` is the judge's reason in words, None for `runs` and for a judged one that kept none. `cause` is what
    started the turn, None for one kept before causes were. `undo` is how it is taken back; None when it has no inverse
    (a send, a delete, a replaced config, a moved mail) or was kept before undos were, and then no Undo is offered."""

    id: int
    label: str | None
    summary: str
    tier: Literal["runs", "judged"]
    explanation: str | None
    at: AwareDatetime
    cause: ActionCause | None
    undo: ActionUndo | None


class OutsideActionsResponse(BaseModel):
    """The signed-in person's most recent outside actions, as `outside_actions`, newest first, at most `limit` of them. Rows are kept 90 days.
    Only theirs: another person's, or another household's, are never listed."""

    outside_actions: list[OutsideAction]
