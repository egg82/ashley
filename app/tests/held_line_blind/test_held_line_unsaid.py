"""A held line followed by a closing step that says nothing: on a page no line of hers is stored for it (the page shows
the turn as unfinished), and the work is gone."""

from dataclasses import replace

import pytest
from ashley import logs
from ashley.channels import respond as respond_module
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from contract.conversations_support import events, run
from hl_support import CHECKING, World, database, ended, switch_on

EMPTY = Reply(spoken="", text="")


@pytest.fixture(autouse=True)
def one_round(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat", replace(respond_module.LIMITS["chat"], max_tool_rounds=1))


@pytest.mark.parametrize("closing", [[EMPTY, EMPTY], [EMPTY, Reply(spoken="ok", text="")]])
def test_a_held_turn_whose_closing_step_stays_empty_ends_with_no_line_of_hers(
        world: World, closing: list[Reply], capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.first.model.script = [CHECKING, switch_on(), *closing]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await ended(world)

    run(go())
    assert world.hers() == [(CHECKING.text, True)]
    assert world.work() == 0
    assert [e["reason"] for e in events(capsys.readouterr().out, "respond.failed")] == ["unworded"]
