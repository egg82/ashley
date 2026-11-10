"""`GET /api/chat/conversation` serves each turn's `working`, from `InFlight.working`, owner-only as the thread is."""

from ashley import services
from ashley.api.models import ChatConversation
from ashley.conversations.inflight import InFlight, InFlightUnavailable, NullInFlight
from ashley.people.model import Person
from ashley.signin.model import SignedIn
from contract.web_chat_support import ALANA, ELLA, HOME, MARK, World, conversation, turn


class Working(NullInFlight):
    """`working` answers `ids` for `conversation_id`, nothing for any other conversation, and records each ask."""

    def __init__(self, conversation_id: int, *ids: int) -> None:
        self.conversation_id, self.ids = conversation_id, frozenset(ids)
        self.asked: list[int] = []
        self.error: Exception | None = None

    async def working(self, conversation_id: int) -> frozenset[int]:
        self.asked.append(conversation_id)
        if self.error is not None:
            raise self.error
        return self.ids if conversation_id == self.conversation_id else frozenset()


def flags(web: World, person: Person = ALANA) -> dict[int, bool]:
    got = web.get(person)
    assert got.status_code == 200
    body = ChatConversation.model_validate(got.json())
    return {t.id: t.working for t in body.turns}


def install(conversation_id: int, *ids: int) -> Working:
    fake = Working(conversation_id, *ids)
    services.register(InFlight, fake)
    return fake


def test_a_turn_with_work_in_flight_is_working_and_the_rest_are_not(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(
        31, (turn(1, "person", "a"), turn(2, "ashley", "A."), turn(3, "person", "b")))
    install(31, 3)
    assert flags(web) == {1: False, 2: False, 3: True}


def test_every_turn_carries_a_boolean_working(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "a"),
                                                                           turn(2, "ashley", "A.")))
    install(31)
    for t in web.get().json()["turns"]:
        assert t["working"] is False


def test_with_no_work_service_nothing_is_working(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "a"),))
    services.register(InFlight, InFlight.null())
    assert flags(web) == {1: False}


def test_the_work_is_asked_for_the_persons_own_conversation(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "a"),))
    fake = install(31, 1)
    flags(web)
    assert fake.asked == [31]


def test_an_idle_conversation_marks_its_working_turn_too(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "a"),), "idle")
    install(31, 1)
    assert flags(web) == {1: True}


def test_another_person_sees_none_of_it(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", f"alana {MARK}"),))
    fake = install(31, 1)
    got = web.get(ELLA)
    assert got.json() == {"thread": "person:2:web", "conversation_id": None, "started_at": None, "turns": []}
    assert MARK not in got.text and 31 not in fake.asked


def test_a_person_of_another_household_sees_none_of_it(web: World) -> None:
    stranger = Person(40, HOME + 1, "Zed")
    web.sessions.by_token["t-40"] = SignedIn(140, stranger)
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", f"alana {MARK}"),))
    fake = install(31, 1)
    got = web.get(stranger)
    assert got.status_code == 200 and got.json()["turns"] == [] and MARK not in got.text
    assert 31 not in fake.asked


def test_a_closed_conversation_shows_no_turns_working_or_not(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "old"),), "closed")
    install(31, 1)
    assert web.get().json()["turns"] == []


def test_the_read_changes_nothing_about_the_work(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", "a"),))
    install(31, 1)
    assert flags(web) == flags(web) == {1: True}
    assert web.loop.seen == []


def test_work_that_cannot_be_read_is_503_unavailable(web: World) -> None:
    web.conversations.by_thread[(HOME, "person:1:web")] = conversation(31, (turn(1, "person", f"alana {MARK}"),))
    install(31, 1).error = InFlightUnavailable("down")
    got = web.get()
    assert got.status_code == 503
    assert got.json()["code"] == "unavailable" and MARK not in got.text
