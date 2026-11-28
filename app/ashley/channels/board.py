"""What the board (`GET /api/work`) reads that only the turn-side systems may touch: a person's pending proposals
(`Proposals.of`, each judged still takeable by `refusal` against the time limit of the tool that proposed it), live
watches (`Watches.live`) and what she did on her own for them (`OutsideRecord.of_person`, `decisions.md`, "What she did
on her own is one record"), what she kept quiet for them (`OutsideRecord.quiet_of_person`), and ending one of those watches (`Watches.disarm`). They are handed to `ashley.api.work_pending` as plain
records, so the API holds no import of the tools or the watches."""

from dataclasses import dataclass
from datetime import UTC, datetime

from .. import services
from ..senses.deposit_config import CONFIG as DEPOSITS
from ..senses.deposit_rule import describe
from ..senses.outside_record import Cause, OutsideRecord, OutsideRecordUnavailable, QuietEntry, Undone
from ..senses.proposal_payloads import HeldCalls, HouseChange, MoneyRule, Payload, WatchSchedule
from ..senses.proposals import Proposals, ProposalsUnavailable, refusal
from ..tools import outside_config
from ..tools.house_look_config import load as house_look
from ..undo import Undo
from ..watches.watches import Watches, WatchesUnavailable

DID_LISTED = 50
QUIET_LISTED = 3


class BoardUnavailable(Exception):
    """A store the board reads could not be reached."""


@dataclass(frozen=True)
class Pending:
    """A proposal still waiting for the person's OK: `summary` is written by code from its payload, `tap` whether
    Agree can be a tap (held calls), `conversation_id` where it was made."""

    id: int
    summary: str
    proposed_at: datetime
    conversation_id: int
    tap: bool


@dataclass(frozen=True)
class Kept:
    """A live watch of the person's: `label` as armed, `paused` when it stopped after failing, `held` when the person
    paused it, `at` its last wake (else when it was armed)."""

    id: int
    label: str
    paused: bool
    held: bool
    at: datetime


@dataclass(frozen=True)
class Did:
    """A change she made for the person with no one's OK in that turn: its `outside_actions` row `id`, code's `summary`
    of it, when (`at`), what started the turn (`cause`), how it is taken back (`undo`, None when it cannot be) and
    whether that was taken (`undone`)."""

    id: int
    summary: str
    at: datetime
    cause: Cause | None
    undo: Undo | None
    undone: Undone | None = None


@dataclass(frozen=True)
class Quiet:
    """What she decided not to say on her own for the person within the record's keep: `count` of them, `id` the newest
    row's, and `latest` the newest `QUIET_LISTED` (their `why`, `at` and `cause`)."""

    id: int
    count: int
    latest: tuple[QuietEntry, ...]


def summary(payload: Payload) -> str:
    """What agreeing would do, in one line from the payload's own fields: the held calls' summaries, the house change's
    summary, the money rule in words, else the reminder's or watch's brief."""
    match payload:
        case HeldCalls(calls):
            return "; ".join(c.summary for c in calls)
        case HouseChange(_, said):
            return said
        case MoneyRule(_, rule):
            return describe(rule)
        case WatchSchedule(reminder, brief=brief):
            return reminder.brief if brief is None else brief
        case _:
            return payload.reminder.brief


def ttl_s(payload: Payload) -> float:
    """How long a proposal of this kind can still be agreed to: the limit of the tool that proposed it."""
    if isinstance(payload, HeldCalls):
        return outside_config.load().proposal_ttl_s
    if isinstance(payload, HouseChange):
        return house_look().proposal_ttl_s
    return DEPOSITS.proposal_ttl_s


async def pending(household_id: int, person_id: int) -> tuple[Pending, ...]:
    """The person's proposals in this household that can still be agreed to, newest first. Raises BoardUnavailable."""
    now = datetime.now(UTC)
    try:
        found = await services.get(Proposals).of(person_id)
    except ProposalsUnavailable as e:
        raise BoardUnavailable("proposals unavailable") from e
    return tuple(Pending(p.id, summary(p.payload), p.proposed_at, p.conversation_id, isinstance(p.payload, HeldCalls))
                 for p in found
                 if p.id is not None and p.household_id == household_id
                 and refusal(p, p.turn_id + 1, now, ttl_s(p.payload)) is None)


async def kept(household_id: int, person_id: int) -> tuple[Kept, ...]:
    """The person's armed and paused watches. Raises BoardUnavailable."""
    try:
        live = await services.get(Watches).live(household_id, person_id)
    except WatchesUnavailable as e:
        raise BoardUnavailable("watches unavailable") from e
    return tuple(Kept(w.id, w.label, w.state == "paused", w.held_at is not None, w.last_woke_at or w.armed_at) for w in live)


async def end_watch(household_id: int, person_id: int, watch_id: int) -> bool:
    """Whether the person's own live watch `watch_id` was ended (as `unwatch` ends one: `disarm` on its kind and target);
    False, changing nothing, for one that is unknown, another person's or household's, or already over. Raises
    BoardUnavailable."""
    watches = services.get(Watches)
    try:
        found = await watches.get(watch_id)
        if found is None or found.household_id != household_id or found.person_id != person_id or found.state == "ended":
            return False
        return await watches.disarm(household_id, person_id, found.kind, found.target)
    except WatchesUnavailable as e:
        raise BoardUnavailable("watches unavailable") from e


async def hold_watch(household_id: int, person_id: int, watch_id: int, held: bool) -> bool:
    """Whether the person's own live watch `watch_id` is now held (`held`) or running; False, changing nothing, for one
    that is unknown, another person's or household's, or over: the same watches `end_watch` ends. Raises
    BoardUnavailable."""
    watches = services.get(Watches)
    try:
        change = watches.hold if held else watches.release
        return await change(household_id, person_id, watch_id)
    except WatchesUnavailable as e:
        raise BoardUnavailable("watches unavailable") from e


async def did(household_id: int, person_id: int) -> tuple[Did, ...]:
    """The newest `DID_LISTED` changes she made on her own for the person in this household, newest first, within the
    record's keep (`actions_keep_s`). Raises BoardUnavailable."""
    try:
        found = await services.get(OutsideRecord).of_person(household_id, person_id, DID_LISTED)
    except OutsideRecordUnavailable as e:
        raise BoardUnavailable("the outside record is unavailable") from e
    return tuple(Did(r.id, r.action.summary, r.action.at, r.action.cause, r.action.undo, r.undone) for r in found)


async def quiet(household_id: int, person_id: int) -> Quiet | None:
    """What she kept quiet for the person in this household within the record's keep (`quiet_keep_s`); None when
    nothing. Raises BoardUnavailable."""
    try:
        found = await services.get(OutsideRecord).quiet_of_person(household_id, person_id, QUIET_LISTED)
    except OutsideRecordUnavailable as e:
        raise BoardUnavailable("the outside record is unavailable") from e
    return None if found is None else Quiet(found.id, found.count, found.latest)
