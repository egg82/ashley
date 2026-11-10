"""`reminder_turn.inbound`: the turn a reminder starts is hers alone to the person, promised, unprompted, reads-only, not
remembered, and keyed by the wake's id."""

from ashley.channels.audience import owner_alone
from ashley.channels.wake.reminder_turn import inbound
from ashley.people.model import Person
from rb_support import PLANTED, reminder

ALANA = Person(11, 5, "Alana")
SAM = Person(12, 5, "Sam")


def made(wake_id: int = 31, who: Person = SAM, by: Person = ALANA) -> object:
    return inbound(wake_id, reminder(5, who.id, by.id), who, by)


def test_it_is_on_the_persons_push_thread_with_them_as_the_one_it_is_with() -> None:
    got = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    assert got.household_id == 5 and got.thread == f"push:{SAM.id}" and got.speaker_id == SAM.id


def test_it_reaches_the_person_alone_never_a_shared_screen() -> None:
    got = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    assert owner_alone(got)
    assert got.audience == "owner" and not got.shared and got.device_id is None and got.place is None


def test_it_is_promised_and_unprompted_offers_reads_only_and_is_not_remembered() -> None:
    got = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    assert got.promised is True and got.unprompted is True
    assert got.reads_only is True and got.tools_only is None
    assert got.remembers is False


def test_the_text_carries_what_to_remind_them_of() -> None:
    assert PLANTED in inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA).text
    assert inbound(31, reminder(5, ALANA.id, ALANA.id), ALANA, ALANA).text


def test_the_source_is_the_wakes_id() -> None:
    a = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    b = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    c = inbound(32, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    assert a.source is not None and a.source == b.source and "31" in a.source
    assert c.source != a.source


def test_it_is_not_a_bench_or_a_page_or_a_later_reply() -> None:
    got = inbound(31, reminder(5, SAM.id, ALANA.id), SAM, ALANA)
    assert got.bench_id is None and got.opens_benches is False and got.heard_as is None
