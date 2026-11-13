"""A reminder falling due, taken up by the `wakes` singleton (`runner`): her turn on it (`reminder_turn`), and, when it
repeats, when it is due next: the first occurrence after now or after its own time, whichever is later, in the
household's zone (`ashley.senses.repeat.next_after`). So an occurrence missed while she was down fires once, late, and
the next is still to come, never every missed one in turn."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ... import services
from ...people.people import People
from ...senses.repeat import next_after
from ...senses.wakes import Outcome, Reminder
from ..respond import RespondRefused, respond
from . import reminder_device, reminder_turn


async def fired(wake_id: int, reminder: Reminder) -> tuple[Outcome, datetime | None]:
    """What came of it (`turn`, `failed` when the model refused, `no_person` when whom it is for or who asked is no
    longer of the household) and its next occurrence, or None for a one-off. Its turn is on the device its route names
    when that device still fits (`reminder_device.of`), else the phone's. Raises PeopleUnavailable, DevicesUnavailable
    and RespondUnavailable, which leave it due."""
    household = await services.get(People).household(reminder.household_id)
    if household is None:
        return "no_person", None
    nxt = None if reminder.repeat is None else next_after(reminder.repeat, max(datetime.now(UTC), reminder.due_at),
                                                          ZoneInfo(household.timezone))
    people = {p.id: p for p in household.people}
    person, made_by = people.get(reminder.person_id), people.get(reminder.made_by)
    if person is None or made_by is None:
        return "no_person", nxt
    try:
        listed = await reminder_device.of(reminder)
        await respond(reminder_turn.inbound(wake_id, reminder, person, made_by,
                                            None if listed is None else listed.device))
    except RespondRefused:
        return "failed", nxt
    return "turn", nxt
