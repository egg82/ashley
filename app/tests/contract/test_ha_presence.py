"""Directed tests for HomeAssistantPresence against the stand-in Home Assistant."""

import httpx2
import pytest
from ashley import logs
from ashley.people.model import Account, Household, Person
from ashley.people.people import People, PeopleUnavailable
from ashley.senses.home_assistant_presence import HomeAssistantPresence
from conversations_support import FIELD, run
from ha_stand import TOKEN, Stand


class FixedPeople(People):
    def __init__(self, accounts: tuple[Account, ...] | None) -> None:
        self._accounts = accounts

    async def household(self, household_id: int) -> Household | None:
        raise AssertionError("presence reads accounts only")

    async def person_for(self, system: str, external_id: str) -> Person | None:
        raise AssertionError("presence reads accounts only")

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        if self._accounts is None:
            raise PeopleUnavailable("down")
        assert system == "home_assistant"
        return self._accounts


def account(person_id: int, entity: str) -> Account:
    return Account(person_id * 10, 1, person_id, "home_assistant", entity)


ALANA, SAM = account(1, "person.alana"), account(2, "person.sam")


def home(stand: Stand, accounts: tuple[Account, ...] | None) -> frozenset[int] | None:
    result: list[frozenset[int] | None] = []

    async def scenario() -> None:
        result.append(await HomeAssistantPresence(stand.home_assistant(), FixedPeople(accounts)).home(1))

    run(scenario())
    return result[0]


def test_only_state_home_is_home() -> None:
    stand = Stand()
    stand.states = {"person.alana": "home", "person.sam": "not_home"}
    assert home(stand, (ALANA, SAM)) == frozenset({1})
    stand.states = {"person.alana": "Work", "person.sam": "unknown"}
    assert home(stand, (ALANA, SAM)) == frozenset()
    stand.states = {"person.alana": "home", "person.sam": "home"}
    assert home(stand, (ALANA, SAM)) == frozenset({1, 2})


def test_a_person_with_two_accounts_is_home_when_either_is() -> None:
    stand = Stand()
    stand.states = {"person.alana": "not_home", "person.alana_phone": "home"}
    assert home(stand, (ALANA, account(1, "person.alana_phone"))) == frozenset({1})


def test_it_reads_each_entity_with_the_token() -> None:
    stand = Stand()
    stand.states = {"person.alana": "home"}
    home(stand, (ALANA,))
    assert [r.url.path for r in stand.requests] == ["/api/states/person.alana"]
    assert stand.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("failure", [(401, b"401: Unauthorized"), (500, b"x"), (200, b"junk"), (200, b"{}"),
                                     httpx2.ReadTimeout("slow"), httpx2.ConnectError("no")])
def test_one_unreadable_entity_makes_it_unknown(failure: tuple[int, bytes] | Exception) -> None:
    stand = Stand()
    stand.failure = failure
    assert home(stand, (ALANA, SAM)) is None


def test_a_missing_entity_makes_it_unknown_though_the_other_is_home() -> None:
    stand = Stand()
    stand.states = {"person.alana": "home"}
    assert home(stand, (ALANA, SAM)) is None


def test_no_mapped_account_or_no_people_is_unknown() -> None:
    assert home(Stand(), ()) is None
    assert home(Stand(), None) is None


def test_the_logs_carry_counts_and_reasons_not_ids(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    stand = Stand()
    stand.states = {"person.alana": "home", "person.sam": "away"}
    home(stand, (ALANA, SAM))
    stand.states = {}
    home(stand, (ALANA, SAM))
    out = capsys.readouterr().out
    events = [{k: v.strip('"') for k, v in FIELD.findall(ln)} for ln in out.splitlines() if "event=presence." in ln]
    assert [(e["event"], e.get("home"), e.get("reason")) for e in events] == [
        ("presence.read", "1", None), ("presence.unknown", None, "http_404")]
    assert "person.alana" not in out
