"""Directed tests for the mutants the blind suite let live: the held line when the budget passes mid-round, the
`bench-act` subcommand, and no window for a closing reply at `max_tool_rounds`."""

import asyncio

import pytest
from ashley.channels.checkpoint import Checkpoint
from ashley.channels.tool_loop import NO_STEPS, Held, answer, resume
from ashley.evals.__main__ import parser
from ashley.inference.model import ToolCall, ToolResult
from bgb_support import (CONVERSATION, FINAL, HISTORY, LAST, PROMISE, READ, STOOD, SYSTEM, TOOLS, Rig, Timed, brainstorm,
                         drive, one, round_of)
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint
from later_support import Logged


class Slow(Timed):
    """Each call takes real time, so the hold budget passes while a round's calls run."""

    async def call(self, call: ToolCall) -> ToolResult:
        await asyncio.sleep(0.3)
        return await super().call(call)


def test_d_a_budget_passing_mid_round_holds_the_first_aside_of_that_round(rig: Rig) -> None:
    rig.model.script = [round_of(0, (READ, "First, whole sentence."), (LAST, "And second, a continuation.")), FINAL]
    limits = brainstorm(hold_after_s=0.1)

    async def go() -> list[str]:
        tools = Slow(rig.clock)
        got = await answer("brainstorm", SYSTEM, HISTORY, TOOLS, limits, CONVERSATION, hold=True, source=tools,
                           started=rig.clock.now, clock=rig.clock, steps=NO_STEPS)
        held: list[str] = []
        while isinstance(got, Held):
            held.append(got.reply.text)
            got = await resume(got, "brainstorm", SYSTEM, TOOLS, limits, CONVERSATION, source=tools,
                               started=rig.clock.now, clock=rig.clock, steps=NO_STEPS)
        assert got.reply == FINAL
        return held

    assert settle(go()) == ["First, whole sentence."]


def test_d_the_evals_have_a_bench_act_subcommand_with_a_scripted_mode() -> None:
    got = parser().parse_args(["bench-act", "--scripted", "--case", "E4"])
    assert got.case == "E4" and got.scripted is True


def test_d_a_closing_reply_at_max_tool_rounds_is_stood_not_given_a_window(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    rig.model.script = [one(0), PROMISE, STOOD]
    steps = rig.saved(checkpoint())
    run = settle(drive(rig, brainstorm(max_tool_rounds=1, deadline_s=1000.0), hold=False, steps=steps,
                       started=rig.clock.now))
    assert run.answer.reply == STOOD
    assert log.events("respond.window") == [] and len(log.events("respond.stood")) == 1
    saved: Checkpoint = rig.store.last()
    assert saved.windows == 0
