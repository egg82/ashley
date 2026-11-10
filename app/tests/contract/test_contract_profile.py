"""`Memory.profile` on PostgresMemory: the current standing facts of the asker's household, through the visibility
filter `recall` uses, by fact id; and what the two other reads do with a standing fact. Written blind from the
contract."""

import pytest
from ashley.memory.model import Forget, Invalidate, Update
from ashley.memory.postgres import PostgresMemory

from conversations_support import run
from hybrid_support import Dictated, conversation_of, memory_with
from memory_support import pool
from profile_support import AT, LATER, Cast, add_all, asker, seated, new

NAMES = ["house", "a-shared", "a-discreet", "a-private", "e-shared", "e-discreet", "e-private"]


async def seed(memory: PostgresMemory, c: Cast) -> dict[str, int]:
    """One standing fact per row of the visibility table, a non-standing control, a foreign household's, and three
    that stop being current (updated, invalidated, forgotten)."""
    made = await add_all(memory, c.home, c.talk, [
        new(None, "house xyzzy"), new(c.alana, "a-shared xyzzy"), new(c.alana, "a-discreet xyzzy", visibility="discreet"),
        new(c.alana, "a-private xyzzy", visibility="private"), new(c.elodie, "e-shared xyzzy"),
        new(c.elodie, "e-discreet xyzzy", visibility="discreet"), new(c.elodie, "e-private xyzzy", visibility="private"),
        new(c.alana, "plain xyzzy", standing=False), new(c.alana, "old xyzzy"), new(c.alana, "gone xyzzy"),
        new(c.alana, "forgotten xyzzy")])
    ids = dict(zip([*NAMES, "plain", "old", "gone", "forgotten"], made, strict=True))
    [ids["new"]] = await memory.apply(c.home, c.talk, [Update(ids["old"], new(c.alana, "new xyzzy"))], AT.replace(day=2))
    await memory.apply(c.home, c.talk, [Invalidate(ids["gone"]), Forget(ids["forgotten"])], AT.replace(day=2))
    await add_all(memory, c.other_home, c.foreign_talk, [new(c.zed, "z xyzzy")])
    return ids


def test_every_row_of_the_visibility_filter(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            ids = await seed(memory, c)
            by_id = {v: k for k, v in ids.items()}
            everyone = {"house", "a-shared", "e-shared", "new"}
            wanted = {
                (None, False): everyone, (None, True): everyone,
                (c.alana, False): everyone | {"a-discreet", "e-discreet"},
                (c.alana, True): everyone | {"a-discreet", "e-discreet", "a-private"},
                (c.elodie, False): everyone | {"a-discreet", "e-discreet"},
                (c.elodie, True): everyone | {"a-discreet", "e-discreet", "e-private"},
            }
            for (speaker, owner_only), names in wanted.items():
                got = await memory.profile(asker(c.home, speaker, owner_only))
                assert {by_id[r.fact.id] for r in got} == names, (speaker, owner_only)
                assert len(got) == len(names)
                for r in got:
                    assert r.fact.standing is True
                    assert r.fact.household_id == c.home
                    foreign_discreet = r.fact.visibility == "discreet" and r.fact.owner_id != speaker
                    assert r.may_volunteer is not foreign_discreet, (speaker, by_id[r.fact.id])

    run(scenario())


def test_the_profile_is_in_fact_id_order_and_the_same_every_time(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            ids = await seed(memory, c)
            got = await memory.profile(asker(c.home, c.alana, True))
            order = [r.fact.id for r in got]
            assert order == sorted(order) and len(order) == 7
            assert order[-1] == ids["new"], "an update's replacement has the newest id and so comes last"
            assert order == [r.fact.id for r in await memory.profile(asker(c.home, c.alana, True))]

    run(scenario())


def test_the_other_household_sees_only_its_own(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await seed(memory, c)
            got = await memory.profile(asker(c.other_home, c.zed, True))
            assert [r.fact.text for r in got] == ["z xyzzy"]

    run(scenario())


def test_a_household_with_nothing_standing_has_an_empty_profile(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await add_all(memory, c.home, c.talk, [new(c.alana, "just a note", standing=False)])
            assert await memory.profile(asker(c.home, c.alana, True)) == ()

    run(scenario())


def test_a_replaced_invalidated_or_forgotten_standing_fact_is_gone(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            ids = await seed(memory, c)
            got = {r.fact.id for r in await memory.profile(asker(c.home, c.alana, True))}
            assert not got & {ids["old"], ids["gone"], ids["forgotten"]}
            assert ids["new"] in got

    run(scenario())


def test_profile_makes_no_embedding_call(db_url: str) -> None:
    c = seated(db_url)
    inference = Dictated({})

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            await add_all(memory, c.home, c.talk, [new(c.alana, "Alana is vegetarian")])
            inference.roles.clear()
            assert len(await memory.profile(asker(c.home, c.alana))) == 1
            assert inference.roles == []

    run(scenario())


def test_recall_never_returns_a_standing_fact_even_when_its_words_match(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            standing, plain = await add_all(memory, c.home, c.talk, [
                new(c.alana, "zqkettle lives in the drawer"), new(c.alana, "zqkettle is on the shelf", standing=False)])
            got = await memory.recall(asker(c.home, c.alana, True), "zqkettle")
            assert [r.fact.id for r in got] == [plain]
            assert standing in {r.fact.id for r in await memory.profile(asker(c.home, c.alana, True))}

    run(scenario())


def test_recall_by_vector_never_returns_a_standing_fact_either(db_url: str) -> None:
    c = seated(db_url)
    near = {0: 1.0}
    inference = Dictated({"bin schedule": near, "standing one": near, "plain one": {0: 1.0, 1: 0.5}})

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            standing, plain = await add_all(memory, c.home, c.talk, [
                new(c.alana, "standing one"), new(c.alana, "plain one", standing=False)])
            got = await memory.recall(asker(c.home, c.alana, True), "bin schedule")
            assert [r.fact.id for r in got] == [plain]
            assert standing not in {r.fact.id for r in got}

    run(scenario())


@pytest.mark.parametrize("standing", [True, False])
def test_similar_still_returns_a_fact_whether_or_not_it_is_standing(db_url: str, standing: bool) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (made,) = await add_all(memory, c.home, c.talk, [new(c.alana, "zqkettle lives in the drawer",
                                                                  standing=standing)])
            seen = conversation_of(c.home, c.talk, [("person", "zqkettle")])
            assert [f.id for f in await memory.similar(seen, 10)] == [made]

    run(scenario())


def test_an_update_may_replace_a_standing_fact_with_a_standing_one(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (first,) = await add_all(memory, c.home, c.talk, [new(c.alana, "Alana uses a wheelchair")])
            (second,) = await memory.apply(c.home, c.talk, [Update(first, new(c.alana, "Alana uses a cane"))], LATER)
            got = await memory.profile(asker(c.home, c.alana))
            assert [(r.fact.id, r.fact.text) for r in got] == [(second, "Alana uses a cane")]

    run(scenario())
