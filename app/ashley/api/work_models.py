"""The wire models of `/api/work`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel


WorkState = Literal["running", "waiting_on_you", "open", "done", "stopped"]


class WorkItem(BaseModel):
    """One thing the signed-in person asked her to do or make that has not ended: a `kind` of `errand` (asked once, held
    until its source answers), `open_errand` (carried out over checks) or `bench` (an open bench), `id` that record's own
    id (a bench's id is the workshop's `/workshop/{id}`), `title` what it is (the person's own words, shown only to them).
    `state`: `running`, in her hands; `waiting_on_you`, only the person can move it (an install to approve, a job
    blocked on them or on their machine, a check whose words have not reached them); `open`, a bench with nothing in
    flight; `done`, finished with its result not yet told; `stopped`, an errand's check that could not be sent. `at`
    is when it last moved: a bench's last change (else when it opened), an errand's check due or a one-shot's asking,
    or finishing when `done`. `until_local` is when an `open_errand` ends, as the household's wall clock
    (`YYYY-MM-DDTHH:MM`), null for any other kind."""

    kind: Literal["errand", "open_errand", "bench"]
    id: int
    title: str
    state: WorkState
    at: AwareDatetime
    until_local: str | None = None


class WorkResponse(BaseModel):
    """The signed-in person's open work, those waiting on them first, then running, open, stopped and done, the most
    recently moved first within each."""

    entries: list[WorkItem]
