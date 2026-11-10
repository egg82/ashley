"""`HomeAssistantPresence` against replayed HA state responses: each person's `home_assistant` account names their
`person` entity, read through `/api/states/<entity>`; `home` is home and any other state away; one unreadable entity
makes the answer unknown (None), never an empty set; no one mapped is unknown; an unmapped person is never in the set;
logs carry a count, never who."""

import time

import pytest
from ashley import logs
from ashley.people.model import Account, Household, Person
from ashley.people.people import People, PeopleUnavailable
from ashley.senses.home_assistant_presence import HomeAssistantPresence
from conversations_support import events
from ha_support import HA_TOKEN, Fault, ReplayHA
from inference_support import settle

HOUSE, OTHER = 5, 6
A, B, C = 987_101, 987_102, 987_103


class AccountsPeople(People):
    """Answers `accounts` from a fixed list, filtered as the contract says; counts the systems asked about."""

    def __init__(self, accounts: list[Account], error: Exception | None = None) -> None:
        self.all = accounts
        self.error = error
        self.systems: list[str] = []

    async def household(self, household_id: int) -> Household | None:
        people = tuple(Person(a.person_id, household_id, "x") for a in self.all if a.household_id == household_id)
        return Household(household_id, "h", "UTC", "", people)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        self.systems.append(system)
        if self.error:
            raise self.error
        return tuple(a for a in self.all if a.household_id == household_id and a.system == system)


MAPPED = [Account(1, HOUSE, A, "home_assistant", "person.zqavery"),
          Account(2, HOUSE, B, "home_assistant", "person.zqblair"),
          Account(3, HOUSE, C, "discord", "person.zqcasey"),          # C has no HA mapping
          Account(4, OTHER, 987_200, "home_assistant", "person.zqother")]


def presence(ha: ReplayHA, accounts: list[Account] = MAPPED, timeout_s: float = 5.0,
             error: Exception | None = None) -> tuple[HomeAssistantPresence, AccountsPeople]:
    people = AccountsPeople(accounts, error)
    return HomeAssistantPresence(ha.handle_for(), people, timeout_s=timeout_s), people


@pytest.mark.parametrize(("states", "home"), [
    ({"person.zqavery": "home", "person.zqblair": "not_home"}, frozenset({A})),
    ({"person.zqavery": "home", "person.zqblair": "home"}, frozenset({A, B})),
    ({"person.zqavery": "not_home", "person.zqblair": "Work"}, frozenset[int]()),
    ({"person.zqavery": "Home", "person.zqblair": "unknown"}, frozenset[int]()),   # only exactly `home` is home
])
def test_home_is_the_mapped_people_whose_entity_is_home(states: dict[str, str], home: frozenset[int]) -> None:
    ha = ReplayHA(states={**states, "person.zqcasey": "home", "person.zqother": "home"})
    p, people = presence(ha)
    assert settle(p.home(HOUSE)) == home
    assert sorted(ha.gets) == ["person.zqavery", "person.zqblair"]
    assert "home_assistant" in people.systems
    assert set(ha.auth) == {f"Bearer {HA_TOKEN}"}


def test_an_empty_set_means_everyone_mapped_is_away_not_unknown() -> None:
    got = settle(presence(ReplayHA(states={"person.zqavery": "not_home", "person.zqblair": "not_home"}))[0].home(HOUSE))
    assert got == frozenset() and got is not None


@pytest.mark.parametrize("accounts", [[], [MAPPED[2]], [MAPPED[3]]])
def test_no_one_mapped_is_unknown(accounts: list[Account]) -> None:
    ha = ReplayHA(states={"person.zqcasey": "home", "person.zqother": "home"})
    assert settle(presence(ha, accounts)[0].home(HOUSE)) is None


def test_an_entity_ha_does_not_know_makes_the_answer_unknown() -> None:
    ha = ReplayHA(states={"person.zqavery": "home"})   # person.zqblair is HA's 404
    assert settle(presence(ha)[0].home(HOUSE)) is None


FAULTS: list[Fault] = ["unauthorized", "connect", "not_json", "server_error"]


@pytest.mark.parametrize("fault", FAULTS)
def test_one_unreadable_entity_makes_the_answer_unknown(fault: Fault) -> None:
    ha = ReplayHA(states={"person.zqavery": "home", "person.zqblair": "home"}, faults={"person.zqblair": fault})
    assert settle(presence(ha)[0].home(HOUSE)) is None


def test_an_entity_that_hangs_is_unknown_within_the_timeout() -> None:
    ha = ReplayHA(states={"person.zqavery": "home", "person.zqblair": "home"}, faults={"person.zqblair": "hang"})
    start = time.monotonic()
    assert settle(presence(ha, timeout_s=0.3)[0].home(HOUSE), limit=10.0) is None
    assert time.monotonic() - start < 3.0


def test_people_unreachable_is_unknown() -> None:
    p, _ = presence(ReplayHA(states={"person.zqavery": "home"}), error=PeopleUnavailable("down"))
    assert settle(p.home(HOUSE)) is None


def test_read_logs_the_count_and_duration_never_who(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    ha = ReplayHA(states={"person.zqavery": "home", "person.zqblair": "home"})
    assert settle(presence(ha)[0].home(HOUSE)) == frozenset({A, B})
    out = capsys.readouterr().out
    (line,) = events(out, "presence.read")
    assert "2" in line.values() and "duration_ms" in line
    for leaked in (str(A), str(B), "zqavery", "zqblair", HA_TOKEN):
        assert leaked not in out


@pytest.mark.parametrize("why", ["unmapped", "unreadable"])
def test_unknown_logs_a_reason(capsys: pytest.CaptureFixture[str], why: str) -> None:
    logs.setup()
    capsys.readouterr()
    ha = ReplayHA(states={"person.zqavery": "home"}, faults={"person.zqblair": "connect"})
    assert settle(presence(ha, [] if why == "unmapped" else MAPPED)[0].home(HOUSE)) is None
    out = capsys.readouterr().out
    (line,) = events(out, "presence.unknown")
    assert set(line) - {"ts", "level", "logger", "event"}
    assert events(out, "presence.read") == []
    for leaked in (str(A), str(B), "zqavery", "zqblair"):
        assert leaked not in out
