"""The `members` visibility against a migrated database: household money, heard by a household member who alone hears
the reply and by no one else. Written from the contract in `hearing.py` and the "visibilities" decision."""

import pytest
from ashley.memory.model import Add, Visibility
from ashley.memory.postgres import PostgresMemory

from conversations_support import run
from memory_support import pool
from profile_support import AT, asker, column, new, seated


def test_money_not_said_to_be_private_is_the_households_and_heard_by_members_only(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (made,) = await memory.apply(c.home, c.talk, [Add(new(c.alana, "Alana is saving for a house deposit",
                                                                  kind="finance", standing=False, stated=False))], AT)
            assert column(db_url, made, "owner_id") is None
            assert column(db_url, made, "visibility") == "members"
            assert column(db_url, made, "about_id") == c.alana
            heard = {(who, alone): bool(await memory.recall(asker(c.home, who, alone), "house deposit"))
                     for who in (c.alana, c.elodie, None) for alone in (True, False)}
            assert heard == {(c.alana, True): True, (c.elodie, True): True, (c.alana, False): False,
                             (c.elodie, False): False, (None, True): False, (None, False): False}
            assert not await memory.recall(asker(c.other_home, c.zed, True), "house deposit")

    run(scenario())


def test_money_the_owner_keeps_between_us_stays_theirs_alone(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            owed = new(c.alana, "Alana owes a friend two hundred dollars", kind="finance", standing=False,
                       visibility="private", stated=True)
            (made,) = await memory.apply(c.home, c.talk, [Add(owed)], AT)
            assert column(db_url, made, "owner_id") == c.alana
            assert column(db_url, made, "visibility") == "private"
            assert await memory.recall(asker(c.home, c.alana, True), "owes")
            assert not await memory.recall(asker(c.home, c.elodie, True), "owes")

    run(scenario())


@pytest.mark.parametrize("who", ["alana", "elodie"])
def test_every_member_holds_the_households_money_and_no_outsider_does(db_url: str, who: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (made,) = await memory.apply(c.home, c.talk, [Add(new(c.alana, "Alana's rent is paid on the first",
                                                                  kind="finance", standing=False, stated=False))], AT)
            member = c.alana if who == "alana" else c.elodie
            assert [h.fact.id for h in await memory.held(c.home, member, made)] == [made]
            assert await memory.held(c.other_home, c.zed, made) == ()

    run(scenario())


def test_a_member_forgets_the_households_money(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (made,) = await memory.apply(c.home, c.talk, [Add(new(c.alana, "Alana's rent is paid on the first",
                                                                  kind="finance", standing=False, stated=False))], AT)
            assert await memory.forget(c.home, made, by=c.elodie) == 1
            assert await memory.held(c.home, c.alana, made) == ()

    run(scenario())


def test_members_is_a_visibility_the_type_names() -> None:
    from typing import get_args
    assert "members" in get_args(Visibility)
