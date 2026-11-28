"""The wire models of `/api/work`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel


WorkState = Literal["running", "waiting_on_you", "open", "done", "stopped"]
Lane = Literal["waiting", "doing", "done_untold", "would_like"]


class WorkItem(BaseModel):
    """One thing the signed-in person asked her to do or make that has not ended, or that waits on them: a `kind` of
    `errand` (asked once, held until its source answers), `open_errand` (carried out over checks), `standing_errand`
    (done each time its rule comes round, never finished), `bench` (an open bench), `watch` (a live watch she keeps) or
    `proposal` (something she proposed that nobody has agreed to). `id` is that record's own id (a bench's id is the
    workshop's `/workshop/{id}`, a watch's the one `DELETE /api/work/watches/{id}` cancels, a proposal's the one
    `POST /api/chat/agree` takes), `title` what it is (the person's own words, shown only to them; a proposal's is
    written by code from what it would do).
    `state`: `running`, in her hands; `waiting_on_you`, only the person can move it (an install to approve, a job
    blocked on them or on their machine, a check whose words have not reached them, a proposal); `open`, a bench with
    nothing in flight; `done`, finished with its result not yet told; `stopped`, an errand's check that could not be
    sent or a watch paused after failing. `lane` is where the board puts it: `waiting`, `doing`, `done_untold` or
    `would_like` (something she offered unasked). It follows `state`, and nothing yet marks a proposal as offered
    unasked, so no item is `would_like`. `at` is when it last moved: a bench's last change (else when it opened),
    an errand's next check due or a one-shot's asking, or finishing when `done`, a watch's last wake (else when it was
    armed), a proposal's making. `until_local` is when an `open_errand` ends, as the household's wall clock
    (`YYYY-MM-DDTHH:MM`), null for any other kind, a `standing_errand` included. `conversation_id` is the conversation a
    proposal was made in, null for any other kind. `can_tap` is whether Agree is a tap (`POST /api/chat/agree`, a
    proposal of held calls); a proposal without it is agreed by answering her in that conversation."""

    kind: Literal["errand", "open_errand", "standing_errand", "bench", "watch", "proposal"]
    id: int
    title: str
    state: WorkState
    lane: Lane
    at: AwareDatetime
    until_local: str | None = None
    conversation_id: int | None = None
    can_tap: bool = False


class WorkResponse(BaseModel):
    """The signed-in person's open work, those waiting on them first, then running, open, stopped and done, the most
    recently moved first within each."""

    entries: list[WorkItem]


class WatchCancelled(BaseModel):
    """The watch `id` was ended by the person (`DELETE /api/work/watches/{id}`)."""

    id: int
