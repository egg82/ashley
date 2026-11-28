"""A reminder's, errand check's or standing errand's turn is the household's, never the words of the person it is for:
stored as a line code writes from its fields, its instructions reaching her only as the turn's note, while its thread,
audience, tools and delivery stay the person's. A later turn of that conversation carries it as from the household."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ashley import services
from ashley.channels import standing
from ashley.channels.audience import owner_alone
from ashley.channels.model import Device, Inbound
from ashley.channels.prompt import messages
from ashley.channels.wake import reminder_turn, runner
from ashley.channels.wake.reminder_turn import said, shown
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Turn
from ashley.inference.model import Message
from ashley.people.model import Household, Person
from ashley.senses.outside_record import Cause
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from test_reminder_turn import BRIEF, SAYS, world

SAM, ALANA = Person(2, 1, "Sam"), Person(3, 1, "Alana")
NOW = datetime(2026, 11, 24, 19, 34, tzinfo=UTC)
PLAIN = Reminder(1, 2, 3, BRIEF, NOW, None)
HALL = Device(9, 1, "hall screen", "hall", "present", "text", "chat")


def before(reminder: Reminder, person: Person, made_by: Person) -> Inbound:
    """The phone turn as it was built when the reminder was stored as the person's turn: every field but the three
    this change moves (`text`, `author`, `note`)."""
    return Inbound(household_id=1, thread=f"push:{person.id}", text=said(reminder, person, made_by), kind="chat",
                   medium="text", audience="owner", speaker_id=person.id, shared=False, place=None, channel="device",
                   remembers=False, later=True, later_by="turn", source="wake:7", unprompted=True, promised=True,
                   tools_only=None, reads_only=True, cause=Cause("reminder", 7))


def test_the_fired_turn_is_the_household_s_line_and_her_instructions_are_only_its_note() -> None:
    inbound = reminder_turn.inbound(7, PLAIN, SAM, ALANA)
    assert inbound.author == "household"
    assert inbound.text == f"Reminder: {BRIEF}"
    assert inbound.note is not None and inbound.note == said(PLAIN, SAM, ALANA)
    assert inbound.note.startswith("[A reminder you set")
    assert "[A reminder" not in inbound.text and "Remind Sam" not in inbound.text


def test_errand_checks_and_standing_rounds_are_labelled_by_their_kind() -> None:
    errand = replace(PLAIN, ends_at=NOW + timedelta(days=2))
    rounds = replace(PLAIN, repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)), method="price-watch")
    assert reminder_turn.inbound(7, errand, SAM, ALANA).text == f"Errand check: {BRIEF}"
    assert reminder_turn.inbound(7, rounds, SAM, ALANA).text == f"Standing errand: {BRIEF}"
    for made in (errand, rounds):
        got = reminder_turn.inbound(7, made, SAM, ALANA)
        assert got.author == "household" and got.note == said(made, SAM, ALANA)


def test_its_thread_audience_and_tools_are_the_person_s_as_before() -> None:
    inbound = reminder_turn.inbound(7, PLAIN, SAM, ALANA)
    assert replace(inbound, text="x", author="person", note=None) == replace(before(PLAIN, SAM, ALANA), text="x")
    assert owner_alone(inbound) and inbound.tends_home is None
    acting = replace(PLAIN, tools=("look",))
    got = reminder_turn.inbound(7, acting, SAM, ALANA)
    assert got.tools_only == ("look",) and not got.reads_only and got.speaker_id == SAM.id


def test_it_answers_the_person_privately_but_never_agrees_for_them() -> None:
    held = standing.of(reminder_turn.inbound(7, PLAIN, SAM, ALANA))
    assert held is not None and (held.speaker_id, held.private, held.agreeing) == (SAM.id, True, False)


def test_on_a_device_others_read_the_line_names_whom_it_is_for_never_what_it_is_about() -> None:
    inbound = reminder_turn.inbound(7, replace(PLAIN, route="screen"), SAM, ALANA, HALL)
    assert inbound.thread == "device:9" and inbound.author == "household" and inbound.speaker_id == SAM.id
    assert inbound.text == "Reminder for Sam" and BRIEF not in inbound.text
    assert inbound.note is not None and BRIEF in inbound.note
    assert shown(PLAIN, SAM) == f"Reminder: {BRIEF}"


def test_a_fired_reminder_is_stored_as_the_household_s_line_and_a_later_turn_carries_it_as_such(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.remind()
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            [prompt] = w.model.prompts
            last = [m.text for m in prompt.messages if isinstance(m, Message)][-1]
            assert last.endswith(said(Reminder(w.home, w.alana, w.alana, BRIEF, NOW, None),
                                                          Person(w.alana, w.home, "Alana"),
                                                          Person(w.alana, w.home, "Alana")))
            rows = scalar(db_url, "SELECT json_agg(json_build_array(author, speaker_id, text, visibility, owner_id) "
                                  "ORDER BY id) FROM turns")
            assert rows[0] == ["household", None, f"Reminder: {BRIEF}", "private", w.alana]
            assert rows[1][0] == "ashley" and rows[1][2] == SAYS.text
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)]
            talk = int(scalar(db_url, "SELECT conversation_id FROM turns ORDER BY id LIMIT 1"))
            found = await services.get(Conversations).get(talk)
            assert found is not None
            home = Household(w.home, "Willow", "America/Denver", "", (Person(w.alana, w.home, "Alana"),))
            got = messages(found.turns, Turn(0, "person", w.alana, "thanks", NOW), home)
            assert "[From the Willow household, not words anyone said] Reminder:" in got[0].text
            assert "Alana:" not in got[0].text and "[A reminder you set" not in "".join(m.text for m in got)
    run(go())
