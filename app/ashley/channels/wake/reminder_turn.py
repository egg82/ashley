"""The turn a reminder starts when it falls due: an `Inbound` nobody is waiting on (`unprompted`) that the person asked
for earlier (`promised`), so it goes out whatever Initiative would say; on the phone thread of the person it is for
(`push:<person id>`), with that person as the one it is with, so it reaches where they alone read it
(`audience.owner_alone`), never Discord. A reminder routed to a room or screen runs on that device's thread
(`device:<id>`) instead, with the device's audience and place, so what she says is fit for whoever is there: spoken for
a satellite, which the satellites singleton says (`ashley.channels.voice.reminders`), text for a screen, which its
page shows as it does any turn of its thread (`Inbound.device_id`). Her answer is only stored (`later_by` `turn`), not
queued in the outbox, which drops what waits too long; each delivery is recorded on the reminder, and one not reached
at its room or screen is pushed to the phone (`ashley.channels.push.reminders`). It offers only the tools that change nothing (`Inbound.reads_only`), so she can look at their money before she words it
and never act on it unattended, unless the reminder names the tools its turn may use (`Reminder.tools`, which its maker
agreed to: `Inbound.tools_only`), when it carries them out and says what it did. Its conversation is not remembered. A reminder a deposit, a withdrawal, a balance falling
below or a bill coming due fired carries it (`Reminder.landed`), which she states from its fields. A reminder a tainted turn made starts tainted `inherited`
(`Reminder.taint`), since its brief was written under outside words. The wake's id is the turn's `source`, so an occurrence handed in twice is one turn.

An errand's occurrence (`Reminder.ends_at`) is one check of it: she is given the ask, what she noted at the check
before (`Reminder.plan`) and when it ends, and offered `check_again` (`Inbound.errand`) to set the next. It is not
`promised`: whether she says anything at a check is Initiative's, from her `says`, so a check with nothing to tell
stays quiet.

A standing errand's occurrence (`Reminder.method`) is one round of work that never finishes: she is given the ask, and
the household's skill of that kind loads as her method (`Inbound.method`). It is not `promised` either, so a round
with nothing new to tell stays quiet, and what she finds reaches the person by its route when she says it."""

from datetime import UTC
from zoneinfo import ZoneInfo

from ...people.model import Person
from ...senses.deposit_rule import Landed, money
from ...senses.repeat import LOCAL_FORMAT
from ...senses.wakes import Reminder
from ..model import Device, Inbound
from .on_device import moved


def inbound(wake_id: int, reminder: Reminder, person: Person, made_by: Person, device: Device | None = None,
            zone: ZoneInfo | None = None) -> Inbound:
    """The turn; `device` is the satellite or screen its route names (`reminder_device.of`), None for the phone.
    `zone` is the household's, which an errand's end is shown in (UTC when None)."""
    errand = reminder.ends_at is not None
    standing = reminder.method is not None
    phone = Inbound(household_id=reminder.household_id, thread=f"push:{person.id}",
                    text=said(reminder, person, made_by, device, zone), kind="chat", medium="text", audience="owner",
                    speaker_id=person.id, shared=False, place=None, channel="device", remembers=False, later=True,
                    later_by="turn", source=f"wake:{wake_id}", unprompted=True,
                    promised=not _judged(reminder) and not errand and not standing,
                    tools_only=reminder.tools, reads_only=reminder.tools is None,
                    taint=None if reminder.taint is None else "inherited", made_in=reminder.made_in,
                    errand=wake_id if errand else None, method=reminder.method)
    if device is None:
        return phone
    return moved(phone, reminder.route, device)


def _judged(reminder: Reminder) -> bool:
    return reminder.landed is not None and reminder.landed.judged


def said(reminder: Reminder, person: Person, made_by: Person, device: Device | None = None,
         zone: ZoneInfo | None = None) -> str:
    """The reminder as she reads it."""
    asked = "they asked" if made_by.id == person.id else f"{made_by.name} asked"
    if reminder.ends_at is not None:
        return _errand(reminder, person, asked, reminder.ends_at.astimezone(zone or UTC).strftime(LOCAL_FORMAT),
                       _where(reminder, device))
    if reminder.method is not None:
        return _standing(reminder, person, asked, _where(reminder, device))
    return (f"[A reminder you set, not words anyone said: for {person.name}; {asked} you to remind them.]\n"
            f"What to remind them of: {reminder.brief}\n"
            f"{_landed(reminder.landed)}{_what_to_do(reminder, person, _where(reminder, device))}")


def _errand(reminder: Reminder, person: Person, asked: str, ends: str, where: str) -> str:
    noted = ("This is its first check." if reminder.plan is None
             else f"What you noted at your last check: {reminder.plan}")
    return (f"[An errand you are carrying out over time, not words anyone said: for {person.name}; {asked} you to do "
            f"it.]\nWhat they asked: {reminder.brief}\n{noted}\n"
            f"It runs until {ends}. Do what you can now with the tools you have. If it is not done and there is time, "
            f"set your next check with check_again; if you do not, the errand ends here. Tell {person.name} only what "
            f"they would want to hear now, such as that it is done or cannot be; otherwise set `says` to none. {where}")


def _standing(reminder: Reminder, person: Person, asked: str, where: str) -> str:
    return (f"[A standing errand you carry out each time it comes round, not words anyone said: for {person.name}; "
            f"{asked} you to keep doing it.]\nWhat they asked: {reminder.brief}\n"
            f"Do this round now, following the method for it in your instructions, with the tools you have. Tell "
            f"{person.name} only what they would want to hear now, such as something new you found or that it cannot "
            f"be done; otherwise set `says` to none. {where}")


def _where(reminder: Reminder, device: Device | None) -> str:
    if device is None:
        return "It goes to their phone."
    if reminder.route == "room":
        return f"It is said aloud in the {device.place}, where others may hear it: say nothing private."
    return f"It shows on the screen in the {device.place}, where others may see it: say nothing private."


def _what_to_do(reminder: Reminder, person: Person, where: str) -> str:
    if reminder.tools is not None:
        return ("They asked you to do this, and agreed to the tools you have now. Do it now with them, then say "
                "briefly what you did or why you could not.\n")
    return ("If it depends on their money, look first with the tools you have (they only read) and say what you "
            "found, how much or that there is nothing to do. It goes out whatever you find.\n"
            f"Remind {person.name} of it now, briefly, in your own words. {where}")


def _landed(landed: Landed | None) -> str:
    if landed is None:
        return ""
    if landed.below_cents is not None:
        return (f"The balance that fell: {landed.account_name} is at {money(landed.cents)}, below "
                f"{money(landed.below_cents)}, as read on {landed.day.isoformat()}. {_judge(landed)}"
                f"Say where it stands, from these figures.\n")
    if landed.due_in is not None:
        return (f"The bill coming due: {money(landed.cents)} to {landed.payee}, out of {landed.account_name}, expected "
                f"{_in(landed.due_in)}, on {landed.day.isoformat()}{', and it pays itself' if landed.autopay else ''}. "
                f"{_judge(landed)}Say what is due and when, from these figures.\n")
    amount = f"{landed.cents // 100}.{landed.cents % 100:02d}"
    if landed.direction == "out":
        source = "" if landed.payee is None else f", to {landed.payee}"
        return (f"The withdrawal that left: {amount} on {landed.day.isoformat()} out of {landed.account_name}{source}. "
                f"Say what left, from these figures.\n")
    source = "" if landed.payee is None else f", from {landed.payee}"
    return (f"The deposit that landed: {amount} on {landed.day.isoformat()} into {landed.account_name}{source}. "
            f"{_why(landed)}{_history(landed)}{_judge(landed)}Say what landed, from these figures.\n")


def _in(days: int) -> str:
    return "today" if days == 0 else f"in {days} day(s)"


def _why(landed: Landed) -> str:
    return f"It matched because: {', '.join(landed.because)}. " if landed.because else ""


def _history(landed: Landed) -> str:
    h = landed.history
    if h is None:
        return ""
    if h.seen == 0:
        return "This payer has not paid into this account in the history read. "
    return (f"This payer paid into this account {h.seen} time(s) before, from {_money(h.low_cents)} to "
            f"{_money(h.high_cents)}, about every {h.every_days} days, last on {h.last_day}. ")


def _judge(landed: Landed) -> str:
    return ("Decide whether this is what they meant: set `says` to none if it is not, and nothing is sent. "
            if landed.judged else "")


def _money(cents: int | None) -> str:
    return "?" if cents is None else f"{cents // 100}.{cents % 100:02d}"
