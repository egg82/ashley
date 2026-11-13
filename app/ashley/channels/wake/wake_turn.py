"""The turn a wake starts: an `Inbound` nobody is waiting on (`unprompted`), on the phone thread of the person it is
about (`push:<person id>`, which the push singleton delivers), with that person as the one it is with, so her memory
and the hearing rule are theirs. The stored message is the household's turn, written from the wake's fields alone
(never anything HA sent as text), so it is safe to show; her rule's brief reaches her only as the turn's `note`. The
wake's id is the turn's `source`, so a wake handed in twice is one turn. The turn carries the facts of its moment
(`Inbound.moment`), and the note tells her what `Initiative` planned of them for this call: say it in full, keep it to
one line, or say nothing."""

from ...initiative.moment import Moment, Outcome
from ...people.model import Person
from ...senses.wakes import Wake
from ...workshop.wake_rule import WakeRule
from ..model import Inbound

_THIS_TIME: dict[Outcome, str] = {
    "full": "This time, say it in full.",
    "short": "This time, keep it to one short line.",
    "silent": "This time, say nothing: set `says` to none. Nothing you write is sent; still do what the brief asks "
              "of your tools.",
}


def inbound(wake_id: int, wake: Wake, rule: WakeRule, person: Person, moment: Moment, outcome: Outcome) -> Inbound:
    return Inbound(household_id=wake.household_id, thread=f"push:{person.id}", text=said(person, wake),
                   kind="chat", medium="text", audience="owner", speaker_id=person.id, shared=False, place=None,
                   channel="device", remembers=False, later=True, later_by="outbox", source=f"wake:{wake_id}",
                   unprompted=True, tools_only=rule.tools, author="household",
                   note=note(rule, person, wake, outcome), taint=None, moment=moment)


def said(person: Person, wake: Wake) -> str:
    """The wake as the page shows it, from its fields alone: the event, who, and what."""
    return " · ".join([wake.event, person.name, *([wake.what] if wake.what else [])])


def note(rule: WakeRule, person: Person, wake: Wake, outcome: Outcome) -> str:
    """What only she reads, with the turn: when it happened, her rule's brief, what her reply may do, and the
    instruction for this call that `outcome` gives."""
    return (f"The event happened at {wake.at.isoformat(timespec='minutes')}.\n"
            f"Your brief for this wake: {rule.brief}\n"
            f"Whatever you write goes to {person.name}'s phone only if you set `says` to reply.\n"
            f"{_THIS_TIME[outcome]}")
