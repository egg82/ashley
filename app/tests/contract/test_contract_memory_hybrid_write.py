"""Embeddings on the write side of PostgresMemory (`apply`, `embed_missing`) and `similar`, over a migrated database
with dictated embeddings. Written blind from the `Memory` docstrings."""

from ashley.memory.model import Add, Forget, Invalidate, Update
from ashley.memory.recall_policy import RecallPolicy

from conversations_support import household, person, run
from hybrid_support import (AT, LATER, Dictated, conversation_of, distance_to, embedding_state, fact, memory_with,
                            rows)
from memory_support import conversation, say

TEXTS = ("alpha one", "beta two", "gamma three", "delta four", "epsilon five")


def test_an_inserted_fact_is_stored_with_the_embedding_of_its_text_by_the_current_model(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({t: {i: 1.0} for i, t in enumerate(TEXTS)}, model="m-now")

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            first, second = await memory.apply(home, talk, [Add(fact(TEXTS[0])), Add(fact(TEXTS[1]))], AT)
            [third] = await memory.apply(home, talk, [Update(first, fact(TEXTS[2]))], LATER)
            for fact_id, text in ((first, TEXTS[0]), (second, TEXTS[1]), (third, TEXTS[2])):
                found = distance_to(db_url, fact_id, inference.vector(text))
                assert found is not None and found < 1e-4, text
                assert embedding_state(db_url, fact_id) == (True, "m-now")
            assert set(inference.roles) == {"passage"}

    run(scenario())


def test_an_embedder_that_is_down_loses_no_fact_and_embed_missing_fills_them_later(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({t: {i: 1.0} for i, t in enumerate(TEXTS)})
    inference.down = True

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            first, second = await memory.apply(home, talk, [Add(fact(TEXTS[0])), Add(fact(TEXTS[1]))], AT)
            [third] = await memory.apply(home, talk, [Update(first, fact(TEXTS[2]))], LATER)
            assert [embedding_state(db_url, i) for i in (first, second, third)] == [(False, None)] * 3
            assert [r[0] for r in rows(db_url, "SELECT valid_to IS NULL FROM facts ORDER BY id")] == [False, True, True]
            assert await memory.embed_missing(10) == 0
            inference.down = False
            assert await memory.embed_missing(10) == 2
            assert [embedding_state(db_url, i)[0] for i in (first, second, third)] == [False, True, True]
            assert await memory.embed_missing(10) == 0

    run(scenario())


def test_embed_missing_embeds_the_oldest_first_up_to_its_limit_and_returns_how_many(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({t: {i: 1.0} for i, t in enumerate(TEXTS)})
    inference.down = True

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            ids: list[int] = []
            for day, text in enumerate(TEXTS):
                ids += await memory.apply(home, talk, [Add(fact(text))], AT.replace(day=day + 1))
            inference.down = False
            assert await memory.embed_missing(0) == 0
            assert await memory.embed_missing(2) == 2
            assert [embedding_state(db_url, i)[0] for i in ids] == [True, True, False, False, False]
            assert await memory.embed_missing(10) == 3
            assert all(embedding_state(db_url, i)[0] for i in ids)

    run(scenario())


def test_embed_missing_replaces_another_models_embeddings_and_leaves_the_current_models_alone(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    old = Dictated({TEXTS[0]: {0: 1.0}, TEXTS[1]: {1: 1.0}}, model="m-old")
    new = Dictated({TEXTS[0]: {10: 1.0}, TEXTS[1]: {11: 1.0}, TEXTS[2]: {12: 1.0}}, model="m-new")

    async def scenario() -> None:
        async with memory_with(db_url, old) as memory:
            first, second = await memory.apply(home, talk, [Add(fact(TEXTS[0])), Add(fact(TEXTS[1]))], AT)
        async with memory_with(db_url, new) as memory:
            [third] = await memory.apply(home, talk, [Add(fact(TEXTS[2]))], LATER)
            assert await memory.embed_missing(1) == 1
            assert await memory.embed_missing(10) == 1
            assert await memory.embed_missing(10) == 0
            for fact_id, text in ((first, TEXTS[0]), (second, TEXTS[1]), (third, TEXTS[2])):
                found = distance_to(db_url, fact_id, new.vector(text))
                assert found is not None and found < 1e-4, text
                assert embedding_state(db_url, fact_id) == (True, "m-new")

    run(scenario())


def test_facts_that_are_not_current_are_left_without_an_embedding(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({})
    inference.down = True

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            replaced, invalid, current = await memory.apply(home, talk, [Add(fact(TEXTS[0])), Add(fact(TEXTS[1])),
                                                                         Add(fact(TEXTS[2]))], AT)
            await memory.apply(home, talk, [Update(replaced, fact(TEXTS[3])), Invalidate(invalid)], LATER)
            inference.down = False
            assert await memory.embed_missing(10) == 2
            assert [embedding_state(db_url, i)[0] for i in (replaced, invalid, current)] == [False, False, True]

    run(scenario())


def test_similar_finds_a_paraphrase_of_a_current_fact_of_any_visibility_and_never_another_households(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    elodie, zed = person(db_url, home, "elodie"), person(db_url, other, "zed")
    talk, foreign = conversation(db_url, home), conversation(db_url, other)
    texts = {"para": "Recycling pickup is Tuesday evenings", "private": "Recycling money jar is hidden",
             "foreign": "Recycling pickup is Friday mornings", "old": "Recycling pickup was Monday",
             "forgotten": "Recycling was a secret", "unrelated": "Alana plays piano"}
    inference = Dictated({"bin thing today": {0: 1.0}} | {t: {0: 1.0, 1: 0.1} for t in texts.values()}
                         | {texts["unrelated"]: {9: 1.0}})

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 4)) as memory:
            _, _, old, forgotten, _ = await memory.apply(home, talk, [
                Add(fact(texts["para"])), Add(fact(texts["private"], elodie, "private")),
                Add(fact(texts["old"])), Add(fact(texts["forgotten"])), Add(fact(texts["unrelated"]))], AT)
            await memory.apply(other, foreign, [Add(fact(texts["foreign"], zed))], AT)
            await memory.apply(home, talk, [Invalidate(old), Forget(forgotten)], LATER)
            said = conversation_of(home, talk, [("person", "bin thing today"), ("ashley", "Recycling talk")])
            say(db_url, talk, "bin thing today")
            got = {f.text for f in await memory.similar(said, 10)}
            assert {texts["para"], texts["private"]} <= got
            assert not got & {texts["old"], texts["forgotten"]}
            assert [f.household_id for f in await memory.similar(said, 10)] == [home] * len(got)

    run(scenario())


def test_similar_searches_what_people_said_and_not_what_she_said(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({"The kettle is blue": {5: 1.0}, "hello there": {6: 1.0}, "kettle": {5: 1.0}})

    async def scenario() -> None:
        async with memory_with(db_url, inference, RecallPolicy(10, 0)) as memory:
            await memory.apply(home, talk, [Add(fact("The kettle is blue"))], AT)
            assert await memory.similar(conversation_of(home, talk, [("person", "hello there"), ("ashley", "kettle")]),
                                        10) == ()
            assert await memory.similar(conversation_of(home, talk, []), 10) == ()
            found = await memory.similar(conversation_of(home, talk, [("person", "kettle")]), 10)
            assert [f.text for f in found] == ["The kettle is blue"]
            await memory.apply(home, talk, [Add(fact("A kettle for tea")), Add(fact("Kettle descaled monthly"))], LATER)
            assert len(await memory.similar(conversation_of(home, talk, [("person", "kettle")]), 2)) == 2
            assert len(await memory.similar(conversation_of(home, talk, [("person", "kettle")]), 1)) == 1

    run(scenario())


def test_closed_facts_never_take_the_backfill_batch_from_current_ones(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = Dictated({})
    inference.down = True

    async def scenario() -> None:
        async with memory_with(db_url, inference) as memory:
            [invalid] = await memory.apply(home, talk, [Add(fact(TEXTS[0]))], AT.replace(day=1))
            [replaced] = await memory.apply(home, talk, [Add(fact(TEXTS[1]))], AT.replace(day=2))
            [current] = await memory.apply(home, talk, [Add(fact(TEXTS[2]))], AT.replace(day=3))
            await memory.apply(home, talk, [Invalidate(invalid)], AT.replace(day=4))
            [newer] = await memory.apply(home, talk, [Update(replaced, fact(TEXTS[3]))], AT.replace(day=5))
            inference.down = False
            assert await memory.embed_missing(1) == 1
            assert await memory.embed_missing(1) == 1
            assert [embedding_state(db_url, i)[0] for i in (invalid, replaced, current, newer)] == [False, False, True, True]
            assert await memory.embed_missing(1) == 0

    run(scenario())
