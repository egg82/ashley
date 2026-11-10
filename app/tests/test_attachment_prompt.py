"""A turn's attachment reaches her whole, with the message it came with: in the message answered and in every carried
turn that has one, naming its title and length and marking where it ends, so what the person typed stays distinct from
what they pasted. A turn with none reads as before."""

from datetime import UTC, datetime

from ashley.channels import prompt
from ashley.conversations.model import Attachment, Turn
from ashley.people.model import Household, Person

ALANA = Person(1, 1, "Alana")
HOME = Household(1, "home", "UTC", "", (ALANA,))
NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
PASTE = Attachment("Brief", "line one\nline two\n" + "z" * 5000)


def test_the_message_answered_carries_its_attachment_in_full_after_what_was_typed() -> None:
    said = Turn(2, "person", ALANA.id, "here's the brief:", NOW, attachment=PASTE)
    got = prompt.messages((), said, HOME)[-1].text
    assert got.startswith("Alana: here's the brief:")
    assert PASTE.text in got
    assert 'titled "Brief"' in got and f"{len(PASTE.text)} characters" in got
    assert got.index("here's the brief:") < got.index(PASTE.text)


def test_a_carried_turn_with_an_attachment_brings_it_too_and_one_without_is_unchanged() -> None:
    earlier = Turn(1, "person", ALANA.id, "see this", NOW, attachment=PASTE)
    plain = Turn(2, "person", ALANA.id, "and this", NOW)
    said = Turn(3, "person", ALANA.id, "thoughts?", NOW)
    got = prompt.messages((earlier, plain), said, HOME)
    assert PASTE.text in got[0].text
    assert got[1].text == "(Wed 15 Jul 2026 12:00) Alana: and this"


def test_an_untitled_attachment_is_still_marked_as_pasted() -> None:
    said = Turn(2, "person", ALANA.id, "log:", NOW, attachment=Attachment(None, "boom"))
    got = prompt.messages((), said, HOME)[-1].text
    assert "boom" in got and "titled" not in got and "4 characters" in got
