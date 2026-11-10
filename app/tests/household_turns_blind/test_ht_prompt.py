"""How a household turn reaches her: from the household by name in carried history, the older relevant ones, and the
note that ends only the answered message."""

from ashley.channels.model import Inbound
from ashley.channels.prompt import messages, said_before
from ht_support import ALANA, HOME, NAME, turn


def test_a_household_turn_in_history_is_from_the_household_by_name_in_the_user_role_never_a_persons_words() -> None:
    wake = turn(1, "household", "alana_arrived · Alana · front_door", minutes=0)
    hers = turn(2, "ashley", "Welcome home.", minutes=1)
    said = turn(3, "person", "thanks", ALANA.id, minutes=2)
    got = messages([wake, hers], said, HOME)
    assert got[0].author == "person"
    assert NAME in got[0].text and "alana_arrived · Alana · front_door" in got[0].text
    assert "not words anyone said" in got[0].text
    assert "Alana:" not in got[0].text and "Alana" not in got[0].text.replace("alana_arrived · Alana · front_door", "")
    assert got[1].author == "ashley" and got[1].text.endswith("Welcome home.")
    assert got[2].author == "person" and got[2].text.endswith("Alana: thanks")


def test_a_person_turn_is_not_marked_as_from_the_household() -> None:
    got = messages([turn(1, "person", "hello", ALANA.id)], turn(2, "person", "again", ALANA.id, minutes=1), HOME)
    assert all("household" not in m.text.lower() for m in got)


def test_the_answered_household_message_names_the_household_and_carries_the_note_on_its_own_line() -> None:
    said = turn(5, "household", "alana_arrived · Alana · front_door")
    plain = messages([], said, HOME)
    noted = messages([], said, HOME, note="Greet him only if he has been away.")
    assert plain[-1].text.count("\n") == 0 and NAME in plain[-1].text
    assert noted[-1].text == plain[-1].text + "\nGreet him only if he has been away."
    assert noted[-1].author == "person"


def test_the_note_ends_the_answered_message_only_not_the_carried_ones() -> None:
    earlier = turn(1, "household", "alana_arrived")
    said = turn(2, "household", "alana_left", minutes=5)
    got = messages([earlier], said, HOME, note="BRIEF-TEXT")
    assert "BRIEF-TEXT" not in got[0].text and got[1].text.endswith("\nBRIEF-TEXT")
    assert sum("BRIEF-TEXT" in m.text for m in got) == 1


def test_a_person_message_takes_a_note_the_same_way() -> None:
    got = messages([], turn(1, "person", "hi", ALANA.id), HOME, note="N")
    assert got[-1].text.endswith("Alana: hi\nN") or got[-1].text.endswith("hi\nN")


def test_a_relevant_older_household_turn_reads_by_the_household_name_not_someone() -> None:
    lines = said_before([turn(1, "household", "alana_arrived", minutes=0), turn(2, "person", "hi", ALANA.id, minutes=1),
                         turn(3, "person", "who", None, minutes=2), turn(4, "ashley", "Hello.", minutes=3)],
                        HOME)
    assert lines[0].endswith(f"{NAME}: alana_arrived") and "Someone" not in lines[0]
    assert lines[1].endswith("Alana: hi")
    assert lines[2].endswith("Someone: who")
    assert lines[3].endswith("You: Hello.")


def test_inbound_defaults_to_a_person_without_a_note() -> None:
    inbound = Inbound(10, "t", "hi", "chat", "text", "owner", 1, False, None, "web")
    assert (inbound.author, inbound.note) == ("person", None)
    wake = Inbound(10, "t", "e", "chat", "text", "owner", None, False, None, "device", author="household", note="b")
    assert (wake.author, wake.note) == ("household", "b")
