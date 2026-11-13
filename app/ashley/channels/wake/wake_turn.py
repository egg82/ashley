"""The turn a wake starts: an `Inbound` nobody is waiting on (`unprompted`), on the phone thread of the person it is
about (`push:<person id>`, which the push singleton delivers), with that person as the one it is with, so her memory
and the hearing rule are theirs. The stored message is the household's turn, written from the wake's fields alone
(never anything HA sent as text), so it is safe to show; her rule's brief reaches her only as the turn's `note`. The
wake's id is the turn's `source`, so a wake handed in twice is one turn. A greeting rule's turn carries the facts of its
moment (`Inbound.moment`), and the note tells her what `Initiative` planned of them for this call: say it in full, keep
it to one line, or say nothing. Any other rule's turn carries neither. A greeting Initiative placed at a satellite or
screen runs on that device's thread instead (`on_device.moved`), and its answer is stored for the device's delivery
(`device_delivery`) rather than queued in the outbox."""

from dataclasses import replace

from ...initiative.moment import Moment, Outcome
from ...people.model import Person
from ...people.quiet import held
from ...senses.wakes import Route, Wake
from ...workshop.wake_rule import WakeRule
from ..model import Device, Inbound
from .on_device import moved

_THIS_TIME: dict[Outcome, str] = {
    "full": "This time, say it in full.",
    "short": "This time, keep it to one short line.",
    "silent": "This time, say nothing: set `says` to none. Nothing you write is sent; still do what the brief asks "
              "of your tools.",
}


def inbound(wake_id: int, wake: Wake, rule: WakeRule, person: Person, moment: Moment | None = None,
            outcome: Outcome | None = None, at: tuple[Route, Device] | None = None) -> Inbound:
    """The turn; `at` is the route and device a greeting is placed at, None for the phone."""
    phone = Inbound(household_id=wake.household_id, thread=f"push:{person.id}", text=said(person, wake),
                   kind="chat", medium="text", audience="owner", speaker_id=person.id, shared=False, place=None,
                   channel="device", remembers=False, later=True, later_by="outbox", source=f"wake:{wake_id}",
                   unprompted=True, tools_only=rule.tools, author="household",
                   note=note(rule, person, wake, outcome, at), taint=None, moment=moment,
                   quiet=held(person, wake.at))
    return phone if at is None else replace(moved(phone, *at), later_by="turn")


def said(person: Person, wake: Wake) -> str:
    """The wake as the page shows it, from its fields alone: the event, who, and what."""
    return " · ".join([wake.event, person.name, *([wake.what] if wake.what else [])])


def note(rule: WakeRule, person: Person, wake: Wake, outcome: Outcome | None = None,
         at: tuple[Route, Device] | None = None) -> str:
    """What only she reads, with the turn: when it happened, her rule's brief, what her reply may do, and the
    instruction for this call that `outcome` gives, when there is one."""
    return (f"The event happened at {wake.at.isoformat(timespec='minutes')}.\n"
            f"Your brief for this wake: {rule.brief}\n"
            + _goes(person, at) + ("" if outcome is None else f"\n{_THIS_TIME[outcome]}"))


def _goes(person: Person, at: tuple[Route, Device] | None) -> str:
    if at is None:
        return f"Whatever you write goes to {person.name}'s phone only if you set `says` to reply."
    route, device = at
    where = f"said aloud in the {device.place}" if route == "room" else f"shown on the screen in the {device.place}"
    return (f"Whatever you write is {where} only if you set `says` to reply, where others may hear or see it: say "
            "nothing private.")
