"""A members fact through `PostgresMemory`: heard by a known member who alone hears the reply, by no one else, never
volunteered; any member who holds it may forget it."""

import pytest
from ashley.memory.model import Held
from contract.conversations_support import run, scalar
from hm_support import AT, QUERY, TEXT, Home, make_home, memory, money


async def alana_said_it(home: Home) -> int:
    async with memory(home.url) as mem:
        [fact] = await mem.apply(home.id, home.talk, [money(home.alana, home.alana, "private")], AT)
    return fact


def test_elodie_alone_hears_a_members_fact_alanas_turn_produced(db_url: str) -> None:
    home = make_home(db_url)

    async def go() -> None:
        fact = await alana_said_it(home)
        async with memory(db_url) as mem:
            [got] = await mem.recall(home.asker(home.elodie, True), QUERY)
            assert got.fact.id == fact and got.fact.text == TEXT and got.fact.visibility == "members"
            assert got.fact.owner_id is None and got.may_volunteer is False
            [mine] = await mem.recall(home.asker(home.alana, True), QUERY)
            assert mine.fact.id == fact and mine.may_volunteer is False

    run(go())


@pytest.mark.parametrize("who", ["the kiosk", "a satellite, speaker known", "a household discord channel",
                                 "an unknown speaker on an owner-only channel", "nobody on an owner-only channel"])
def test_no_other_way_of_asking_hears_it(db_url: str, who: str) -> None:
    home = make_home(db_url)
    asking = {"the kiosk": home.asker(None, False), "a satellite, speaker known": home.asker(home.elodie, False),
              "a household discord channel": home.asker(home.alana, False),
              "an unknown speaker on an owner-only channel": home.asker(None, True),
              "nobody on an owner-only channel": home.asker(None, True)}[who]

    async def go() -> None:
        await alana_said_it(home)
        async with memory(db_url) as mem:
            assert await mem.recall(asking, QUERY) == ()
            assert await mem.recall(asking, "money") == ()

    run(go())


def test_another_household_never_hears_it_even_naming_a_member_id(db_url: str) -> None:
    home = make_home(db_url)

    async def go() -> None:
        await alana_said_it(home)
        async with memory(db_url) as mem:
            assert await mem.recall(home.asker(home.mia, True, home.other), QUERY) == ()
            assert await mem.recall(home.asker(home.elodie, True, home.other), QUERY) == ()
            assert await mem.held(home.other, home.mia) == ()

    run(go())


def test_a_standing_members_fact_comes_with_the_profile_only_where_the_member_alone_hears(db_url: str) -> None:
    home = make_home(db_url)
    fact = home.raw(TEXT, None, "members", standing=True)

    async def go() -> None:
        async with memory(db_url) as mem:
            for member in (home.alana, home.elodie):
                [got] = await mem.profile(home.asker(member, True))
                assert got.fact.id == fact and got.may_volunteer is False
            for shared in (home.asker(None, False), home.asker(home.elodie, False), home.asker(None, True)):
                assert await mem.profile(shared) == ()
            assert await mem.profile(home.asker(home.mia, True, home.other)) == ()

    run(go())


def test_both_members_hold_it_and_a_stranger_does_not(db_url: str) -> None:
    home = make_home(db_url)

    async def go() -> None:
        fact = await alana_said_it(home)
        async with memory(db_url) as mem:
            for member in (home.alana, home.elodie):
                [held] = await mem.held(home.id, member)
                assert isinstance(held, Held) and held.fact.id == fact
                [one] = await mem.held(home.id, member, fact)
                assert one.fact.id == fact
            assert await mem.held(home.other, home.mia, fact) == ()

    run(go())


def test_a_private_finance_fact_stays_alanas_alone(db_url: str) -> None:
    home = make_home(db_url)

    async def go() -> None:
        async with memory(db_url) as mem:
            await mem.apply(home.id, home.talk, [money(home.alana, home.alana, "private", stated=True)], AT)
            assert await mem.recall(home.asker(home.elodie, True), QUERY) == ()
            assert await mem.held(home.id, home.elodie) == ()
            assert len(await mem.recall(home.asker(home.alana, True), QUERY)) == 1

    run(go())


def test_the_second_member_may_forget_a_members_fact_and_it_goes_for_both(db_url: str) -> None:
    home = make_home(db_url)

    async def go() -> None:
        fact = await alana_said_it(home)
        async with memory(db_url) as mem:
            assert await mem.forget(home.id, fact, home.elodie) == 1
            assert await mem.held(home.id, home.alana) == () and await mem.held(home.id, home.elodie) == ()
            assert await mem.recall(home.asker(home.alana, True), QUERY) == ()

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM facts") == 0
