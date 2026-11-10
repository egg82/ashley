"""What `# Now` says when a message was said aloud on a page, and the field it offers: the line names the speaker (or
says it does not know), sits after the phone line, appears only when offered; `Reply.aloud` is in every provider's
schema, required and with no default."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from ashley.inference.reply import Reply
from ashley.people.model import Household, Person
from ashley.persona import facts
from ashley.persona.persona import Context, system

ALANA = Person(1, 1, "Alana")
HOME = Household(1, "home", "America/Denver", "", (ALANA,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = Context(NOW, HOME, ALANA, None, None, None, True)


def moment(context: Context) -> str:
    return system("chat", context)["default"].moment


def test_a_known_speaker_is_named_in_the_aloud_line() -> None:
    assert facts.ALOUD.format(name="Alana") in moment(replace(CONTEXT, aloud=True))


def test_an_unknown_speaker_gets_the_other_line() -> None:
    text = moment(replace(CONTEXT, speaker=None, aloud=True))
    assert facts.ALOUD_UNKNOWN in text and "{name}" not in text and "Alana said" not in text


def test_no_offer_no_line() -> None:
    text = moment(CONTEXT)
    assert facts.ALOUD_UNKNOWN not in text and "`aloud`" not in text


def test_the_aloud_line_follows_the_phone_line() -> None:
    text = moment(replace(CONTEXT, aloud=True, phone=True))
    assert text.index(facts.PHONE.format(name="Alana")) < text.index(facts.ALOUD.format(name="Alana"))


def test_the_schema_every_provider_is_sent_requires_aloud_with_no_default() -> None:
    schema = Reply.model_json_schema()
    assert "aloud" in schema["required"] and "default" not in schema["properties"]["aloud"]
    assert Reply(spoken="a", text="b").aloud is False
