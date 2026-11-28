"""What the board (`GET /api/work`) reads that only the turn-side systems may touch: a person's pending proposals
(`Proposals.of`, each judged still takeable by `refusal` against the time limit of the tool that proposed it) and live
watches (`Watches.live`), and ending one of those watches (`Watches.disarm`). They are handed to `ashley.api.work_pending` as plain
records, so the API holds no import of the tools or the watches."""

from dataclasses import dataclass
from datetime import UTC, datetime

from .. import services
from ..senses.deposit_config import CONFIG as DEPOSITS
from ..senses.deposit_rule import describe
from ..senses.proposal_payloads import HeldCalls, HouseChange, MoneyRule, Payload, WatchSchedule
from ..senses.proposals import Proposals, ProposalsUnavailable, refusal
from ..tools import outside_config
from ..tools.house_look_config import load as house_look
from ..watches.watches import Watches, WatchesUnavailable


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
    """A live watch of the person's: `label` as armed, `paused` when it stopped after failing, `at` its last wake (else
    when it was armed)."""

    id: int
    label: str
    paused: bool
    at: datetime


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
    return tuple(Kept(w.id, w.label, w.state == "paused", w.last_woke_at or w.armed_at) for w in live)


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
