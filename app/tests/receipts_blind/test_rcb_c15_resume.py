"""Contract 15: a turn killed after its calls ran and before it was stored is finished by another runner, which stores
the same receipts once, read from the outside record and the proposal and never from the dead runner's memory, and runs
nothing again."""

import asyncio

import pytest
from ashley.channels import resume
from ashley.channels.respond import respond
from contract.conversations_support import run
from receipts_blind_support import (ANSWER, CHECKING, HANG, LAMP_LABEL, OKAY, World, change, database, hers, looked,
                                    settled)


def kill_the_turn() -> int:
    """Cancel every task running the app's own turn code, as a dead pod does; the database's pool is left alone."""
    mine = [t for t in asyncio.all_tasks() if "/ashley/channels/" in str(getattr(getattr(t.get_coro(), "cr_code", None),
                                                                                "co_filename", ""))]
    for task in mine:
        task.cancel()
    return len(mine)


@pytest.mark.parametrize("held", [False, True])
def test_c15_the_resumed_turn_stores_the_same_receipts_once(world: World, held: bool) -> None:
    if held:
        world.judge.answers = {"house_do": "ask"}
    world.first.model.script = [CHECKING, looked(), change(), HANG]
    world.second.model.script = [ANSWER]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.web())
            assert out.follows
            await asyncio.wait_for(world.first.model.asked.wait(), 5)
            assert kill_the_turn() >= 1
            await asyncio.sleep(0.45)
            world.as_pod(world.second)
            assert await resume.sweep() == 1
            turns = await settled(out.conversation_id, 2)
            assert await resume.sweep() == 0
            answers = [t for t in await hers(out.conversation_id) if not t.follows]
            assert len(answers) == 1 and answers[0].text == OKAY and len(turns) == 2
            receipts = answers[0].receipts
            assert receipts is not None
            if held:
                assert receipts.done == () and [r.headline for r in receipts.held] == [LAMP_LABEL]
                assert receipts.proposal_id == world.count("SELECT id FROM proposals ORDER BY id DESC LIMIT 1")
            else:
                assert receipts.held == () and [r.headline for r in receipts.done] == [LAMP_LABEL]
                assert world.count("SELECT count(*) FROM outside_actions WHERE tier = 'judged'") == 1

    run(go())
    assert world.second.tools.ran == [] and len(world.first.tools.ran) == (1 if held else 2)
