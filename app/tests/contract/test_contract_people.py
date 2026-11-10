"""People over a real database seeded with SQL: a household with everyone in it ordered by id, its timezone and
profile; the person an account names, never a guess; a household's accounts on one system ordered by id; the Null
Object and an unreachable database raising PeopleUnavailable; no name in any log line."""

import pytest
from ashley import logs, services
from ashley.people.model import Account, Household, Person
from ashley.people.people import People, PeopleUnavailable
from contract_support import unreachable_conninfo
from conversations_support import household, person, run
from people_support import account, home, people

MARK = "zqNAME5519"


def test_a_household_reads_with_its_timezone_profile_and_people_ordered_by_id(db_url: str) -> None:
    house = home(db_url, "the house", "Europe/Berlin", "two cats, one dog")
    other = home(db_url)
    ids = [person(db_url, house, n) for n in ("Zed", "Amy", "Mo")]
    person(db_url, other, "Not Theirs")

    async def scenario() -> None:
        async with people(db_url) as p:
            got = await p.household(house)
        assert got == Household(house, "the house", "Europe/Berlin", "two cats, one dog", (
            Person(ids[0], house, "Zed"), Person(ids[1], house, "Amy"), Person(ids[2], house, "Mo")))

    run(scenario())


def test_a_household_with_no_timezone_or_profile_set_reads_utc_and_empty(db_url: str) -> None:
    house = household(db_url, "plain")

    async def scenario() -> None:
        async with people(db_url) as p:
            got = await p.household(house)
        assert got == Household(house, "plain", "UTC", "", ())

    run(scenario())


def test_an_unknown_household_is_none(db_url: str) -> None:
    async def scenario() -> None:
        async with people(db_url) as p:
            assert await p.household(987_654_321) is None

    run(scenario())


def test_an_account_names_its_person(db_url: str) -> None:
    house = home(db_url)
    alana, sam = person(db_url, house, "Alana"), person(db_url, house, "Sam")
    account(db_url, house, alana, "home_assistant", "person.alana")
    account(db_url, house, sam, "home_assistant", "person.sam")
    account(db_url, house, sam, "discord", "1234")

    async def scenario() -> None:
        async with people(db_url) as p:
            assert await p.person_for("home_assistant", "person.alana") == Person(alana, house, "Alana")
            assert await p.person_for("home_assistant", "person.sam") == Person(sam, house, "Sam")
            assert await p.person_for("discord", "1234") == Person(sam, house, "Sam")

    run(scenario())


@pytest.mark.parametrize(("system", "external_id"), [
    ("home_assistant", "person.nobody"),
    ("discord", "person.alana"),          # the id exists, on another system
    ("home_assistant", "PERSON.ALANA"),   # never guessed by a looser match
    ("home_assistant", "person.ale"),
    ("home_assistant", ""),
])
def test_an_unknown_account_is_none(db_url: str, system: str, external_id: str) -> None:
    house = home(db_url)
    account(db_url, house, person(db_url, house, "Alana"), "home_assistant", "person.alana")

    async def scenario() -> None:
        async with people(db_url) as p:
            assert await p.person_for(system, external_id) is None

    run(scenario())


def test_accounts_are_one_households_on_one_system_ordered_by_id(db_url: str) -> None:
    house, other = home(db_url), home(db_url)
    a, b = person(db_url, house), person(db_url, house)
    stranger = person(db_url, other)
    first = account(db_url, house, b, "home_assistant", "person.b")
    account(db_url, house, b, "discord", "77")
    second = account(db_url, house, a, "home_assistant", "person.a")
    account(db_url, other, stranger, "home_assistant", "person.stranger")

    async def scenario() -> None:
        async with people(db_url) as p:
            got = await p.accounts(house, "home_assistant")
            assert got == (Account(first, house, b, "home_assistant", "person.b"),
                           Account(second, house, a, "home_assistant", "person.a"))
            assert await p.accounts(house, "authentik") == ()
            assert await p.accounts(987_654_321, "home_assistant") == ()

    run(scenario())


def test_every_call_raises_unavailable_when_the_database_is_unreachable() -> None:
    async def scenario() -> None:
        async with people(unreachable_conninfo(), connect_timeout_s=0.5) as p:
            with pytest.raises(PeopleUnavailable):
                await p.household(1)
            with pytest.raises(PeopleUnavailable):
                await p.person_for("home_assistant", "person.alana")
            with pytest.raises(PeopleUnavailable):
                await p.accounts(1, "home_assistant")

    run(scenario())


def test_the_null_object_raises_unavailable_on_every_call() -> None:
    services.unregister(People)
    p = services.get(People)

    async def scenario() -> None:
        with pytest.raises(PeopleUnavailable):
            await p.household(1)
        with pytest.raises(PeopleUnavailable):
            await p.person_for("home_assistant", "person.alana")
        with pytest.raises(PeopleUnavailable):
            await p.accounts(1, "home_assistant")

    run(scenario())


def test_no_name_reaches_any_log_line(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    house = home(db_url, f"house {MARK}", profile=f"profile {MARK}")
    alana = person(db_url, house, f"Alana {MARK}")
    account(db_url, house, alana, "home_assistant", f"person.{MARK}")
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        async with people(db_url) as p:
            got = await p.household(house)
            assert got is not None and got.people[0].name == f"Alana {MARK}", "control: the name was read"
            assert await p.person_for("home_assistant", f"person.{MARK}") is not None
            await p.accounts(house, "home_assistant")

    run(scenario())
    assert MARK not in capsys.readouterr().out
