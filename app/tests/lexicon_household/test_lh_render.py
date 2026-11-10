"""`render` for a household: its own words apply to spoken replies, another household's and no household's do not, and
the text a person reads is never respelled."""

import pytest
from ashley import services
from ashley.channels.lexicons import Lexicons, LexiconUnavailable
from ashley.channels.render import render
from ashley.inference.reply import Reply
from contract.conversations_support import run, scalar
from lexicon_household_support import lexicons, unreachable

def home(url: str, name: str) -> int:
    return int(scalar(url, "INSERT INTO households (name, timezone) VALUES (%s, 'UTC') RETURNING id", (name,)))


def _person(url: str, household: int) -> int:
    return int(scalar(url, "INSERT INTO people (household_id, name) VALUES (%s, 'P') RETURNING id", (household,)))


REPLY = Reply(spoken="Mochi and Nuuk are asleep.", text="Mochi and Nuuk are asleep.")


def test_a_household_hears_its_own_words_and_no_other(db_url: str) -> None:
    moore, other, fresh = home(db_url, "moore"), home(db_url, "other"), home(db_url, "fresh")
    alana, kim = _person(db_url, moore), _person(db_url, other)

    async def scenario() -> None:
        async with lexicons(db_url) as store:
            services.register(Lexicons, store)
            await store.put(moore, alana, "Mochi", "Mowchi")
            await store.put(other, kim, "Nuuk", "Nook")
            assert await render(REPLY, "spoken", moore) == "Mowchi and Nuuk are asleep."
            assert await render(REPLY, "spoken", other) == "Mochi and Nook are asleep."
            assert await render(REPLY, "spoken", fresh) == REPLY.spoken, "a new household starts with none"
            assert await render(REPLY, "spoken", None) == REPLY.spoken, "no household has none"
            assert await render(REPLY, "text", moore) == REPLY.text
            await store.put(moore, alana, "Nuuk", "Nook")
            assert await render(REPLY, "spoken", moore) == "Mowchi and Nook are asleep.", "read at render, not held"
            await store.remove(moore, alana, "Mochi")
            assert await render(REPLY, "spoken", moore) == "Mochi and Nook are asleep."

    run(scenario())


def test_words_that_cannot_be_read_leave_the_reply_as_spoken() -> None:
    async def scenario() -> None:
        async with lexicons(unreachable(), connect_timeout_s=0.5) as store:
            services.register(Lexicons, store)
            assert await render(REPLY, "spoken", 1) == REPLY.spoken
            with pytest.raises(LexiconUnavailable):
                await store.entries(1)

    run(scenario())


def test_unwired_there_are_no_words() -> None:
    async def scenario() -> None:
        assert await render(REPLY, "spoken", 1) == REPLY.spoken

    run(scenario())
