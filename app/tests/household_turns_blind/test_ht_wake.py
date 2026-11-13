"""A wake over real Postgres: the stored turn is the household's with only the event fields; her brief reaches her as
the turn's note and never the page, and a later turn carries the household turn as the household's."""

from ashley.channels.prompt import messages
from ashley.channels.wake import runner
from ashley.conversations.conversations import Conversations
from ashley import services
from ashley.inference.reply import Reply
from contract.conversations_support import run, scalar
from ht_support import BRIEF, HOME, NAME, last_message, turn, world

SAYS = Reply(spoken="Welcome home.", text="Welcome home, Alana.", says="reply")


def test_the_stored_wake_turn_is_the_households_with_only_the_event_fields(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            wake_id = await w.woken()
            w.model.script = [SAYS]
            assert await runner.sweep() == 1
            [said, hers] = w.turns()
            assert said == ("household", None, f"wake:{wake_id}", "alana_arrived · Alana · front_door")
            assert hers[0] == "ashley"
            for stored in (t[3] for t in w.turns()):
                assert BRIEF not in stored and "`says`" not in stored and "happened at" not in stored
            assert scalar(db_url, "SELECT count(*) FROM turns WHERE author = 'person'") == 0
    run(go())


def test_the_brief_reaches_her_on_the_answered_message_and_names_the_event(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
            [prompt] = w.model.prompts
            said = last_message(prompt)
            assert BRIEF in said and "alana_arrived · Alana · front_door" in said and NAME in said
            assert "Alana:" not in said.split(BRIEF)[0]
    run(go())


def test_the_wake_turn_is_in_the_conversation_of_the_person_it_is_about_with_her_reply(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
            assert len(w.conversation_of_turns()) == 1
            cid = w.conversation_of_turns()[0]
            got = await services.get(Conversations).get(cid)
            assert got is not None and got.participants == frozenset({w.alana})
            assert [t.author for t in got.turns] == ["household", "ashley"]
    run(go())


def test_the_same_event_id_twice_is_one_household_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            await w.woken("ctx-1")
            await w.woken("ctx-1")
            w.model.script = [SAYS, SAYS]
            await runner.sweep()
            await runner.sweep()
            assert scalar(db_url, "SELECT count(*) FROM turns WHERE author = 'household'") == 1
    run(go())


def test_a_later_turn_carries_the_wake_as_the_households_and_never_the_brief(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.rule()
            await w.woken()
            w.model.script = [SAYS]
            await runner.sweep()
            cid = w.conversation_of_turns()[0]
            got = await services.get(Conversations).get(cid)
            assert got is not None
            carried = messages(got.turns, turn(99, "person", "thanks", w.alana), HOME)
            texts = " ".join(m.text for m in carried)
            assert BRIEF not in texts and "[From the" in texts and NAME in carried[0].text
            assert carried[0].author == "person" and "not words anyone said" in carried[0].text
    run(go())
