"""The wire models of `/api/reminders`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..senses.repeat import MAX_EVERY
from ..senses.wakes import MAX_BRIEF
from ..text import NoNul
from .models import Person


class Reminder(BaseModel):
    """A reminder still to fire: for `person`, set by `made_by` (often the same person), what it says, when it fires
    next (`due_at`, and `local_at`, that time as the household's wall clock, `YYYY-MM-DDTHH:MM`), and how it repeats:
    `repeat` none for once, else every `every` days, weeks, months or years. `what` is the person's own, shown only to
    them and to whoever set it. `state`: `scheduled`, still to fire; `sending`, fired and its push not tried yet;
    `undelivered`, fired but no push reached their phone yet (it is tried again for a day, and her words are in
    their conversation history); `failed`, it could not fire. A fired one stays listed until it is delivered or the
    person dismisses it. `on_deposit` is, for a reminder that waits on a deposit instead of a time, the rule in words
    (it fires on every match until cancelled, and `due_at` is when it was set); None for a timed one. `method` makes a
    repeating reminder a standing errand: the slug of the household's kind of work (`WorkshopKinds.work_kinds`) whose
    skill her turn follows each time it fires; None for any other reminder."""

    id: int
    person: Person
    made_by: Person
    what: str
    due_at: AwareDatetime
    local_at: str
    repeat: Literal["daily", "weekly", "monthly", "yearly"] | None
    every: int | None
    on_deposit: str | None = None
    method: str | None = None
    state: Literal["scheduled", "sending", "undelivered", "failed"]


class RemindersResponse(BaseModel):
    """The signed-in person's reminders, for them or set by them, soonest first."""

    reminders: list[Reminder]


class ReminderCancelled(BaseModel):
    """The reminder cancelled, so a repeating one fires no more, or, for one that already fired and is listed
    undelivered or failed, dismissed from the list."""

    id: int


class ReminderRequest(BaseModel):
    """A reminder the signed-in person sets for themselves, to reach their phone: `what`, and `local_at`, the first time as
    the household's wall clock, `YYYY-MM-DDTHH:MM`. With `repeat` it comes round every `every` days, weeks, months or
    years from `at`; without, it fires once. `method` makes it a standing errand and needs `repeat`: a kind of work
    the household has with a method."""

    model_config = ConfigDict(extra="forbid")

    what: NoNul = Field(min_length=1, max_length=MAX_BRIEF)
    local_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    repeat: Literal["daily", "weekly", "monthly", "yearly"] | None = None
    every: int = Field(default=1, ge=1, le=MAX_EVERY)
    method: NoNul | None = Field(default=None, max_length=40)


class ReminderMethodRequest(BaseModel):
    """A reminder's `method` as it is to be: a kind of work the household has with a method, for a repeating reminder
    still to fire, or null to make it an ordinary reminder again. Always sent; null is a choice."""

    model_config = ConfigDict(extra="forbid")

    method: NoNul | None = Field(max_length=40)
