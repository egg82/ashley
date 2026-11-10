"""Recall and `similar` by words and by meaning over a migrated database, with embeddings from a stand-in that says
which texts are near. What is under test is the SQL: the visibility filter before the vector, the order, the fallback."""

from datetime import UTC, datetime

import psycopg
from ashley import services
from ashley.inference.inference import Inference
from ashley.conversations.model import Conversation, Turn
from ashley.memory.model import Add, Asker, NewFact, Visibility
from ashley.memory.postgres import PostgresMemory
from ashley.memory.recall_policy import RecallPolicy
from embed_support import ConceptInference

from conversations_support import household, person, run
from memory_support import conversation, pool

AT = datetime(2026, 3, 1, tzinfo=UTC)
CONCEPTS = {"recycling": 0, "bin": 0, "vet": 1, "tea": 2}


def new(owner: int | None, text: str, visibility: Visibility = "shared") -> Add:
    return Add(NewFact(owner, owner, visibility, True, "other", False, text))


def embeddings(url: str) -> list[tuple[str, str | None]]:
    with psycopg.connect(url) as conn:
        return [(r[0], r[1]) for r in conn.execute("SELECT text, embedding_model FROM facts ORDER BY id").fetchall()]


def test_a_paraphrase_is_found_by_meaning_after_the_word_matches_and_not_across_visibility(db_url: str) -> None:
    home = household(db_url)
    alana, elodie = person(db_url, home, "alana"), person(db_url, home, "elodie")
    talk = conversation(db_url, home)
    inference = ConceptInference(CONCEPTS)
    services.register(Inference, inference)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db, RecallPolicy(limit=10, vector_k=2))
            recycling, _, _, milk, secret = await memory.apply(home, talk, [
                new(None, "The recycling goes out on Tuesday nights"), new(None, "Mochi has a vet visit"),
                new(None, "Alana likes tea"), new(None, "Elodie wants milk"),
                new(alana, "Alana hides the recycling money", "private")], AT)
            asked = Asker(home, elodie, True, AT)
            found = [r.fact.id for r in await memory.recall(asked, "bin schedule")]
            assert found[0] == recycling and secret not in found
            assert [r.fact.id for r in await memory.recall(asked, "milk and bin schedule")][:2] == [milk, recycling]
            assert {recycling, secret} <= {r.fact.id for r in await memory.recall(Asker(home, alana, True, AT),
                                                                                  "bin schedule")}
            assert set(inference.roles) == {"passage", "query"}
            said = Conversation(talk, home, "chat", frozenset(), AT, AT, "idle",
                                (Turn(1, "person", None, "is it bin night", AT),))
            assert {recycling, secret} <= {f.id for f in await memory.similar(said, 1)}

    run(scenario())


def test_a_fact_written_while_the_embedder_is_down_is_kept_and_filled_in_later(db_url: str) -> None:
    home = household(db_url)
    talk = conversation(db_url, home)
    inference = ConceptInference(CONCEPTS)
    services.register(Inference, inference)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            inference.down = True
            await memory.apply(home, talk, [new(None, "The recycling goes out on Tuesday nights")], AT)
            assert embeddings(db_url) == [("The recycling goes out on Tuesday nights", None)]
            assert await memory.embed_missing(10) == 0
            assert [r.fact.text for r in await memory.recall(Asker(home, None, False, AT), "recycling")] == [
                "The recycling goes out on Tuesday nights"]
            inference.down = False
            assert await memory.embed_missing(10) == 1
            assert embeddings(db_url)[0][1] == "fake-1"
            assert await memory.embed_missing(10) == 0
            inference.model = "fake-2"
            await memory.recall(Asker(home, None, False, AT), "recycling")
            assert await memory.embed_missing(10) == 1
            assert embeddings(db_url)[0][1] == "fake-2"

    run(scenario())
