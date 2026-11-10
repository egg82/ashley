"""Contract 4, 5 and 6, blind, over a real database: a tagged turn stores her voice in the same insert as her text,
through `respond` and through a runner that took the turn over from a dead one; the checkpoint keeps the tag, and one
written before the tag existed loads untagged."""

import asyncio
import json
from contextlib import suppress
from dataclasses import replace

import pytest
from ashley.channels import checkpoint, resume
from ashley.channels.checkpoint import Checkpoint
from ashley.channels.respond import respond
from ashley.channels.tool_loop import Progress
from ashley.inference.model import Message, SystemPrompt
from ashley.inference.reply import Reply
from contract.conversations_support import run
from pv_pg_support import HANG, Hang, World, database, kill_the_turn, settled
from pv_pg_support import world as world
from pv_support import aloud_of, chat_inbound_for

CHECKING = Reply(answers=False, spoken="Checking now.", text="Let me check.", aloud=True)
VOICED = Reply(spoken="The lamp is on.", text="The lamp is on!", aloud=True)
PLAIN = Reply(spoken="The lamp is on.", text="The lamp is on!", aloud=False)


def saved(aloud: bool) -> Checkpoint:
    return Checkpoint(chat_inbound_for(aloud=aloud), 3, 4, 1, {"default": SystemPrompt("system")},
                      Progress((Message("person", "hi"),), 0, 0))


def test_c06_the_checkpoint_keeps_the_tag_through_a_round_trip() -> None:
    for tagged in (True, False):
        back = checkpoint.loads(checkpoint.dumps(saved(tagged)))
        assert aloud_of(back.inbound) is tagged and back.inbound == saved(tagged).inbound


def test_c06_a_checkpoint_written_without_the_tag_loads_untagged() -> None:
    raw = json.loads(checkpoint.dumps(saved(True)))
    assert raw["inbound"].pop("said_aloud") is True, "control: the tag was in the JSON"
    old = checkpoint.loads(json.dumps(raw))
    assert aloud_of(old.inbound) is False
    assert old.inbound == replace(saved(True).inbound, said_aloud=False)


def test_c04_a_tagged_turn_over_postgres_stores_the_voice_with_the_text(world: World) -> None:
    world.first.script = [VOICED]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await asyncio.sleep(0.2)

    run(go())
    assert world.rows() == [("person", "turn on the lamp", False, None),
                            ("ashley", "The lamp is on!", False, "The lamp is on.")]


def test_c01_the_same_reply_on_a_typed_turn_stores_none(world: World) -> None:
    world.first.script = [VOICED]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound(aloud=False))
            await asyncio.sleep(0.2)

    run(go())
    assert world.hers() == [("The lamp is on!", False, None)]


def test_c05_a_held_line_and_its_answer_each_store_their_own_voice(world: World) -> None:
    world.first.script = [CHECKING, VOICED]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.follows
            await settled(world, 2)

    run(go())
    assert world.hers() == [("Let me check.", True, "Checking now."), ("The lamp is on!", False, "The lamp is on.")]


def killed_and_resumed(world: World, first: list[Reply | Hang], second: list[Reply], aloud: bool) -> None:
    world.first.script = [*first]
    world.second.script = [*second]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            turn = asyncio.ensure_future(respond(world.inbound(aloud=aloud)))
            await asyncio.wait_for(world.first.asked.wait(), 5)
            assert kill_the_turn() >= 1
            with suppress(asyncio.CancelledError):
                await turn
            await asyncio.sleep(0.45)
            world.as_pod(world.second)
            assert await resume.sweep() == 1

    run(go())


def test_c06_a_tagged_turn_taken_over_by_another_runner_honours_the_offer(world: World) -> None:
    killed_and_resumed(world, [HANG], [VOICED], aloud=True)
    assert world.hers() == [("The lamp is on!", False, "The lamp is on.")]


def test_c06_an_untagged_turn_taken_over_stays_without_a_voice(world: World) -> None:
    killed_and_resumed(world, [HANG], [VOICED], aloud=False)
    assert world.hers() == [("The lamp is on!", False, None)]


def test_c06_the_resumed_runners_choice_is_its_own(world: World) -> None:
    killed_and_resumed(world, [HANG], [PLAIN], aloud=True)
    assert world.hers() == [("The lamp is on!", False, None)]


def test_c06_a_voiced_held_line_is_not_stored_again_by_the_runner_that_resumes(world: World) -> None:
    killed_and_resumed(world, [CHECKING, HANG], [VOICED], aloud=True)
    assert world.hers() == [("Let me check.", True, "Checking now."), ("The lamp is on!", False, "The lamp is on.")]


@pytest.mark.parametrize("aloud", [True, False])
def test_c07_the_stored_person_turn_is_the_typed_one_whatever_the_tag(world: World, aloud: bool) -> None:
    world.first.script = [PLAIN]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound("turn on the lamp", aloud=aloud))
            await asyncio.sleep(0.2)

    run(go())
    assert world.rows()[0] == ("person", "turn on the lamp", False, None)
