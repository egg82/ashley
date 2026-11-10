"""Through `respond` over Postgres: turn 1 runs code, turn 2's messages to the model carry the run."""

import dataclasses
from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.limits import load
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.db.database import Database
from ashley.inference.model import Message
from ashley.inference.reply import Reply
from ashley.runs.model import Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.signin.model import SignedIn
from ashley.tools.tools import Tools
from contract.conversations_support import run, scalar
from rhb_support import World, RunsTool, build_world, calls_run_code, database, out

SCRIPT = "print(6 * 7)  # SCRIPTMARK"
OUTPUT = "forty-two OUTMARK"


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    yield from build_world(db_url)


def ask(world: World, text: str) -> Inbound:
    return dataclasses.replace(inbound_from(SignedIn(1, world.who), ChatRequest(text=text)), later=False)


def messages_of(world: World, prompt: int) -> list[str]:
    return [m.text for m in world.model.prompts[prompt].messages if isinstance(m, Message)]


async def first_turn(world: World, db: Database, output: Output | None = None) -> None:
    runs = PostgresRuns(db)
    services.register(Runs, runs)
    services.register(Tools, RunsTool(world.url, runs, output or out(OUTPUT), SCRIPT))
    world.model.script = [calls_run_code(), Reply(spoken="It is 42.", text="It is 42.")]
    await respond(ask(world, "what is 6 times 7, run it"))


def stored_texts(world: World) -> list[str]:
    return [t for t in str(scalar(world.url, "SELECT string_agg(text, '|' ORDER BY id) FROM turns")).split("|")]


def test_the_next_reply_is_sent_the_run_of_the_earlier_answer(world: World) -> None:
    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            sent = "\n".join(messages_of(world, -1))
            assert SCRIPT in sent and OUTPUT in sent
            assert "[code run: python, ran, exit 0]" in sent and "[end code run]" in sent
            texts = messages_of(world, -1)
            answer = next(i for i, t in enumerate(texts) if "It is 42." in t)
            assert SCRIPT in texts[answer] and "and again?" in texts[-1] and SCRIPT not in texts[-1]
            assert not any(SCRIPT in t for i, t in enumerate(texts) if i != answer)

    run(go())


def test_the_run_is_never_part_of_her_stored_turn(world: World) -> None:
    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            assert "[code run" not in "|".join(stored_texts(world))
            assert "It is 42." in stored_texts(world)

    run(go())


def test_the_reply_that_made_the_run_was_not_sent_its_own_run(world: World) -> None:
    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            assert not any(SCRIPT in t for t in messages_of(world, 0))

    run(go())


def test_the_output_is_cut_to_the_chat_budget_keeping_its_tail(world: World) -> None:
    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db, out("HEADMARK" + "x" * 2000 + "TAILMARK"))
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            sent = "\n".join(messages_of(world, -1))
            assert "TAILMARK" in sent and "HEADMARK" not in sent

    run(go())


def test_the_output_budget_is_the_chat_kinds_not_another(world: World) -> None:
    budget = load()["chat"].run_output_chars
    assert budget > load()["command"].run_output_chars

    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db, out("HEADMARK" + "x" * (budget - 8)))
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            assert "HEADMARK" in "\n".join(messages_of(world, -1))

    run(go())


def test_a_reply_goes_on_without_runs_when_they_cannot_be_read(world: World) -> None:
    from rhb_support import CountingRuns

    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            services.register(Runs, CountingRuns(broken=True))
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            reply = await respond(ask(world, "and again?"))
            assert reply.body == "Yes."
            sent = "\n".join(messages_of(world, -1))
            assert SCRIPT not in sent and "It is 42." in sent

    run(go())


def test_the_runs_are_read_once_per_reply(world: World) -> None:
    from rhb_support import CountingRuns

    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            counting = CountingRuns()
            services.register(Runs, counting)
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            assert len(counting.reads) == 1

    run(go())


def test_without_a_wired_runs_service_the_reply_just_has_no_runs(world: World) -> None:
    async def go() -> None:
        async with database(world) as db:
            await first_turn(world, db)
            services.unregister(Runs)
            world.model.script = [Reply(spoken="Yes.", text="Yes.")]
            await respond(ask(world, "and again?"))
            assert SCRIPT not in "\n".join(messages_of(world, -1))

    run(go())


