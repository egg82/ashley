"""The Wakes service (`ashley.services`): what the house says just happened, handed in by Home Assistant through
`/api/wakes` and taken up by the `wakes` singleton (`ashley.channels.wake.runner`), an event queue between the two.
Home Assistant detects; she decides (`decisions.md`, "Home Assistant wakes her; she decides"). A reminder is a wake
she sets for herself (`decisions.md`, "Reminders are wakes she sets for herself"): due at its time, and when it
repeats, settling one occurrence schedules the next in the same statement.

A wake is structured fields only, never free text. One event id is one wake per household however often it arrives,
so a retry or a second delivery stores nothing new. A wake is due until it is settled, once, with what came of it;
settled wakes are pruned past their keeping, unsettled ones never."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from ..services import Service
from .deposit_rule import DepositRule, Landed
from .repeat import Repeat

Outcome = Literal["turn", "failed", "no_rule", "ambiguous", "no_person", "expired", "cancelled"]
"""What came of a wake: `turn`, her turn on it ran (whether or not she spoke); `failed`, the turn could not run;
`no_rule`, no open bench of the household holds a wake rule for its event; `ambiguous`, more than one does; `no_person`,
it names no person of the household; `expired`, it waited past its use; `cancelled`, a reminder called off before it
fired."""

MAX_BRIEF = 500
MAX_TOOLS = 20

Route = Literal["phone", "quiet"]
ROUTES: tuple[Route, ...] = get_args(Route)
"""Where a fired reminder's words go: `phone`, pushed to the browsers of the person it is for; `quiet`, only stored
in their conversation, for a reminder whose turn acts and has nothing to add."""

State = Literal["scheduled", "sending", "undelivered", "failed"]


class WakesUnavailable(Exception):
    """The database could not be reached or written. Transient."""


@dataclass(frozen=True)
class Wake:
    """One event the house reports: `event_id` HA's id for this run of the automation (`{{ context.id }}`), `event`
    the slug a wake rule answers, `who` the HA `person.*` entity it is about, `what` a slug of what it concerns, `at`
    when it happened."""

    household_id: int
    event_id: str
    event: str
    who: str | None
    what: str | None
    at: datetime


@dataclass(frozen=True)
class Reminder:
    """A wake she sets for herself: for `person_id`, asked for by `made_by` (the same person, or another of the
    household), due at the aware instant `due_at`, with `brief`, what to remind them of (1 to `MAX_BRIEF` characters;
    people's data, never logged), and `repeat`, how it comes round again, or None for once. `route` is where its words
    go once it has fired, and `tools` the names of the tools its turn may use: None offers only the ones that change
    nothing, a tuple those named (and only the ones its maker could use, `ashley.tools.reminders`). `landed` is the
    deposit a reminder fired for (`Deposits.fire`), None for any other. `taint` is what had tainted the turn that made it
    (`Checkpoint.tainted`: its origin or the tool that read outside words), None for a household's own: its firing turn
    starts tainted `inherited` when it is set, since its `brief` was written under outside words. `made_in` is the
    conversation and turn that made it when `taint` is set, which the judge's words for that firing turn are read from;
    None for a reminder made before it was kept."""

    household_id: int
    person_id: int
    made_by: int
    brief: str
    due_at: datetime
    repeat: Repeat | None
    landed: Landed | None = None
    route: Route = "phone"
    tools: tuple[str, ...] | None = None
    taint: str | None = None
    made_in: tuple[int, int] | None = None


@dataclass(frozen=True)
class Scheduled:
    """A reminder the person still needs to see, by its wake id, and where it stands (`state`): `scheduled`, still to
    fire; `sending`, fired and its push not yet tried; `undelivered`, fired but no push reached their phone yet;
    `failed`, it could not fire. A delivered or cancelled reminder, or one they dismissed, is not listed. `deposit` is
    the rule of a reminder that waits on a deposit (`ashley.senses.deposits`), whose `reminder.due_at` is when it was
    set."""

    id: int
    reminder: Reminder
    state: State = "scheduled"
    deposit: DepositRule | None = None


@dataclass(frozen=True)
class Delivery:
    """A fired reminder whose push is to be tried: for `person_id` of `household_id`, tried `attempts` times so far."""

    id: int
    household_id: int
    person_id: int
    attempts: int


@dataclass(frozen=True)
class Received:
    """The wake's id, and whether this call stored it (`new`) or it had arrived before."""

    id: int
    new: bool


WatchWhat = Literal["changed", "paused"]


@dataclass(frozen=True)
class WatchWake:
    """A check of a watch that has something to tell (`ashley.watches`): `what` is `changed` or `paused`, and `changes`
    the JSON the check stored, for the kind to render (`decisions.md`, "Watches wake her when what a read returns
    changes, until a condition or a time"). Fields only, never the source's text."""

    household_id: int
    person_id: int
    watch_id: int
    what: WatchWhat
    changes: Mapping[str, object]


@dataclass(frozen=True)
class Due:
    """A wake not yet settled and due, `age_s` after it fell due (a house wake falls due when it arrives)."""

    id: int
    wake: Wake | Reminder | WatchWake
    age_s: float


class Wakes(Service):
    @classmethod
    def null(cls) -> "Wakes":
        return NullWakes()

    @abstractmethod
    async def receive(self, device_id: int, wake: Wake) -> Received:
        """Store `wake`, handed in by `device_id`; the same household and event id again returns the stored wake's id
        with `new` false and changes nothing. Raises WakesUnavailable."""

    @abstractmethod
    async def schedule(self, reminder: Reminder) -> int:
        """Store `reminder` as a wake due at its `due_at`; its id. Raises ValueError for a brief outside 1 to
        `MAX_BRIEF` characters or holding a NUL, more than `MAX_TOOLS` tools, or a `landed` deposit (only
        `Deposits.fire` sets one), before anything is written; WakesUnavailable."""

    @abstractmethod
    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        """Replace the brief, `due_at`, `repeat`, `route` and `tools` of the household's reminder `wake_id` with
        `changed`'s, keeping its id, for `person_id` or made by them, while it is unsettled; its occurrences already
        fired are untouched, and the next ones follow the new rule. An armed money reminder keeps its time and has no
        repeat. False, changing nothing, when it is settled, not theirs or does not exist. Raises ValueError as
        `schedule` does; WakesUnavailable."""

    @abstractmethod
    async def due(self, limit: int) -> tuple[Due, ...]:
        """At most `limit` unsettled wakes whose time has come, the longest due first. Raises WakesUnavailable."""

    @abstractmethod
    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        """Settle the wake with `outcome`; False, changing nothing, when it was settled already or does not exist.
        With `next_due`, a repeating reminder's next occurrence is stored, due then, in the same statement, and only
        when this call settled it, so an occurrence has one successor however many runners settle it. A reminder
        settled `turn` is `sending` until its push is tried (`undelivered`, `delivered`). Raises WakesUnavailable."""

    @abstractmethod
    async def reminders(self, household_id: int, person_id: int) -> tuple[Scheduled, ...]:
        """The household's reminders for `person_id` or made by them that are still to fire, or fired and not
        delivered, or failed, and not dismissed (`Scheduled.state`), soonest due first. Raises WakesUnavailable."""

    @abstractmethod
    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        """Settle the unsettled reminder `wake_id` as `cancelled`, so it and the rest of its repeats never fire, when it
        is the household's and for `person_id` or made by them; False, changing nothing, otherwise. Raises
        WakesUnavailable."""

    @abstractmethod
    async def prune(self, older_than_s: float) -> int:
        """Delete the wakes settled more than `older_than_s` ago; how many. Never an unsettled one, nor a reminder still
        listed (`reminders`: undelivered, sending or failed) until its person dismisses it. Raises WakesUnavailable."""

    @abstractmethod
    async def refire(self, wake_id: int, after_s: float) -> int:
        """Count a firing of the unsettled wake that could not run (refused, or its person not found) and make it due
        again `after_s` from now; the firings counted so far, or 0, changing nothing, when it is settled or does not
        exist. Raises WakesUnavailable."""

    @abstractmethod
    async def undelivered(self, limit: int, retry_s: float, within_s: float) -> tuple[Delivery, ...]:
        """At most `limit` reminders fired with a turn (`settle` with `turn` marks one `sending`) whose push is not yet
        delivered, not dismissed, fired less than `within_s` ago, and not tried in the last `retry_s`; the longest fired first.
        Raises WakesUnavailable."""

    @abstractmethod
    async def claim(self, wake_id: int, retry_s: float) -> bool:
        """Take this try at a reminder's push, atomically: True for the one caller that finds it `sending` or
        `undelivered`, not dismissed and not tried in the last `retry_s`, and times the try now; False,
        changing nothing, for any other. Raises WakesUnavailable."""

    @abstractmethod
    async def delivered(self, wake_id: int, reached: bool) -> None:
        """Record one try at a reminder's push: `reached` marks it delivered, which takes it off the list; otherwise
        `undelivered`, with the try counted and timed. Raises WakesUnavailable."""

    @abstractmethod
    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        """The person has seen a fired reminder that is listed (undelivered, sending or failed): take it off the list,
        so it may be pruned. False, changing nothing, unless it is the household's, listed, fired, and for
        `person_id` or made by them. Raises WakesUnavailable."""


class NullWakes(Wakes):
    """What an unwired process sees: every call raises, so a wake is never taken in and quietly dropped."""

    async def receive(self, device_id: int, wake: Wake) -> Received:
        raise WakesUnavailable("wakes are not wired")

    async def schedule(self, reminder: Reminder) -> int:
        raise WakesUnavailable("wakes are not wired")

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        raise WakesUnavailable("wakes are not wired")

    async def due(self, limit: int) -> tuple[Due, ...]:
        raise WakesUnavailable("wakes are not wired")

    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        raise WakesUnavailable("wakes are not wired")

    async def reminders(self, household_id: int, person_id: int) -> tuple[Scheduled, ...]:
        raise WakesUnavailable("wakes are not wired")

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        raise WakesUnavailable("wakes are not wired")

    async def prune(self, older_than_s: float) -> int:
        raise WakesUnavailable("wakes are not wired")

    async def refire(self, wake_id: int, after_s: float) -> int:
        raise WakesUnavailable("wakes are not wired")

    async def undelivered(self, limit: int, retry_s: float, within_s: float) -> tuple[Delivery, ...]:
        raise WakesUnavailable("wakes are not wired")

    async def claim(self, wake_id: int, retry_s: float) -> bool:
        raise WakesUnavailable("wakes are not wired")

    async def delivered(self, wake_id: int, reached: bool) -> None:
        raise WakesUnavailable("wakes are not wired")

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        raise WakesUnavailable("wakes are not wired")
