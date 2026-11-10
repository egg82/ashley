"""`to_phone.copy` builds the phone copy and queues nothing; `storing.stored` returns her turn and what is queued with
it. Neither needs a database."""

import pytest
from ashley import services
from ashley.channels import to_phone
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Outbox, Pushed
from ashley.channels.storing import stored
from ashley.inference.reply import Reply
from ashley.people.model import Person
from later_support import FakeOutbox

LIST = Reply(spoken="It is on your phone.", text="1. Ramen\n2. Saffron Table", to_phone=True)
PLAIN = Reply(spoken="Sure.", text="Sure, written.")
ALANA = Person(1, 7, "Alana")


def spoken(speaker: int | None = 1) -> Inbound:
    return Inbound(household_id=7, thread="device:77", text="where can we eat", kind="command", medium="spoken",
                   audience="household", speaker_id=speaker, shared=True, place="kitchen", channel="voice", later=True)


def written() -> Inbound:
    return Inbound(household_id=7, thread="person:1:web", text="where can we eat", kind="chat", medium="text",
                   audience="owner", speaker_id=1, shared=False, place=None, channel="web", later=True)


def test_the_copy_is_the_text_for_the_speakers_phone() -> None:
    assert to_phone.copy(LIST, 1, 7, 31) == Pushed(7, "push:1", Outbound(31, "text", LIST.text))


def test_the_copy_goes_to_the_phone_offered_not_to_the_household() -> None:
    got = to_phone.copy(LIST, 12, 7, 31)
    assert got is not None and got.thread == "push:12" and got.household_id == 7


@pytest.mark.parametrize("reply, phone", [(PLAIN, 1), (LIST, None), (PLAIN, None)],
                         ids=["not asked for", "not offered", "neither"])
def test_no_copy_when_there_is_nothing_for_the_phone(reply: Reply, phone: int | None) -> None:
    assert to_phone.copy(reply, phone, 7, 31) is None


def test_copy_queues_nothing_itself() -> None:
    outbox = FakeOutbox()
    services.register(Outbox, outbox)
    try:
        assert to_phone.copy(LIST, 1, 7, 31) is not None
    finally:
        services.unregister(Outbox)
    assert outbox.added == [] and outbox.waiting == []


def test_copy_needs_no_service_at_all() -> None:
    assert to_phone.copy(LIST, 1, 7, 31) is not None


def test_a_spoken_reply_offered_to_the_phone_is_stored_as_the_written_text_with_the_copy() -> None:
    turn, queued = stored(LIST, spoken(), ALANA, 1, 31, 5)
    assert (turn.author, turn.text, turn.answers) == ("ashley", LIST.text, 5)
    assert turn.heard == "private" and turn.owner_id == 1
    assert queued == (Pushed(7, "push:1", Outbound(31, "text", LIST.text)),)


def test_a_spoken_reply_not_for_the_phone_is_stored_as_what_was_said_and_queues_nothing() -> None:
    turn, queued = stored(PLAIN, spoken(), ALANA, 1, 31, 5)
    assert (turn.author, turn.text, turn.answers) == ("ashley", PLAIN.spoken, 5)
    assert queued == ()


def test_a_reply_asking_for_a_phone_nobody_offered_is_stored_as_said_and_queues_nothing() -> None:
    turn, queued = stored(LIST, spoken(None), None, None, 31, 5)
    assert turn.text == LIST.spoken and queued == ()


def test_a_written_reply_is_stored_as_its_text() -> None:
    turn, queued = stored(PLAIN, written(), ALANA, None, 31, 5)
    assert (turn.author, turn.text, turn.answers) == ("ashley", PLAIN.text, 5)
    assert queued == ()


def test_what_the_channel_queued_travels_with_the_turn_whole_and_once() -> None:
    own = Pushed(7, "discord:5", Outbound(31, "text", "hello"))
    _, alone = stored(PLAIN, spoken(), ALANA, 1, 31, 5, (own,))
    assert alone == (own,)
    _, both = stored(LIST, spoken(), ALANA, 1, 31, 5, (own,))
    assert len(both) == 2 and own in both and both.count(own) == 1
    assert Pushed(7, "push:1", Outbound(31, "text", LIST.text)) in both
