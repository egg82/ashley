"""Blind contract for `GET /api/chat/search`, written from the route's interface and the history decision ("A person
reads back their earlier conversations") alone, over real Postgres conversations: what comes back is what the person
may read back, ranked, at most `limit`, each with ids a client can follow."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from ashley import services
from ashley.api.history_models import PastMatches
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from conversations_support import household, person, run, service

PUBLIC = "https://ashley.test"
WORD = "zeppelin"


@dataclass
class World:
    client: httpx.AsyncClient
    conversations: Conversations
    home: int
    alana: Person
    sam: Person

    async def say(self, conversation: int, speaker: Person | None, text: str, heard: str = "shared",
                  owner: Person | None = None) -> int:
        turn = await self.conversations.add_turn(conversation, NewTurn(
            "person" if speaker else "ashley", text, None if speaker is None else speaker.id,
            "private" if heard == "private" else "shared", None if owner is None else owner.id))
        return turn.id

    async def found(self, query: str = WORD, **params: object) -> PastMatches:
        got = await self.client.get("/api/chat/search", params={"q": query, **params})
        assert got.status_code == 200, got.text
        return PastMatches.model_validate(got.json())


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    home = household(url)
    alana = Person(person(url, home, "Alana"), home, "Alana")
    sam = Person(person(url, home, "Sam"), home, "Sam")
    app = create_app(Settings(database_url="", build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, alana)
    async with service(url) as conversations:
        services.register(Conversations, conversations)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC) as client:
                yield World(client, conversations, home, alana, sam)
        finally:
            services.unregister(Conversations)


def test_a_person_finds_only_what_they_may_read_back(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            kitchen = await w.conversations.start(w.home, "chat", [w.alana.id, w.sam.id], channel="device")
            mine = await w.say(kitchen.id, w.alana, f"the {WORD} is in the garage")
            shared = await w.say(kitchen.id, w.sam, f"sam says the {WORD} is blue")
            await w.say(kitchen.id, w.sam, f"a secret {WORD} just for me", "private", w.sam)
            alone = await w.conversations.start(w.home, "chat", [w.alana.id], channel="web")
            own_private = await w.say(alone.id, w.alana, f"my private {WORD}", "private", w.alana)
            evaluated = await w.conversations.start(w.home, "chat", [w.alana.id], eval=True)
            await w.say(evaluated.id, w.alana, f"an eval {WORD}")
            elsewhere = await w.conversations.start(w.home, "chat", [w.sam.id])
            await w.say(elsewhere.id, w.sam, f"sam alone {WORD}")

            got = await w.found()

            assert {m.turn_id for m in got.matches} == {mine, shared, own_private}
            assert {m.conversation_id for m in got.matches} == {kitchen.id, alone.id}
            assert all(WORD in m.snippet for m in got.matches)

    run(scenario())


def test_the_best_match_comes_first_and_limit_caps_the_list(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            chat = await w.conversations.start(w.home, "chat", [w.alana.id])
            await w.say(chat.id, w.alana, f"{WORD} and a long tail of words about nothing in particular at all, {WORD}")
            near = await w.say(chat.id, w.alana, f"{WORD} {WORD} {WORD}")
            await w.say(chat.id, w.alana, "nothing here")
            both = await w.found()
            assert len(both.matches) == 2 and both.matches[0].turn_id == near
            assert [m.turn_id for m in (await w.found(limit=1)).matches] == [near]

    run(scenario())


def test_a_query_that_matches_nothing_is_an_empty_list_and_a_bad_limit_is_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            assert (await w.found("nothingmatchesthis")).matches == []
            assert (await w.found("the")).matches == []
            assert (await w.client.get("/api/chat/search", params={"q": WORD, "limit": 0})).status_code == 422
            assert (await w.client.get("/api/chat/search")).status_code == 422

    run(scenario())
