"""`respond.escalated` carries ids, counts and durations (conversation, trigger, rounds, from_route, to_route,
duration_ms), once per escalation, and nothing of what was said or found."""

import asyncio
from typing import Any

import pytest
from ashley import logs
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from contract.conversations_support import events, run
from escalation_blind_support import SWITCH, World, database, escalating, rounds, settled

SECRET_ASIDE = "Aside about zq7-sentinel-4417."
SENT = "zq7-sentinel-4417"
ANSWER = Reply(spoken=f"Done, {SENT}.", text=f"Done, {SENT}.")


def sentinel_round(n: int) -> ToolCalls:
    return ToolCalls((ToolCall(f"c{n}", SWITCH.name, {"what": f"{SENT}{n}", "aside": SECRET_ASIDE}),))


def logged(w: World, capsys: pytest.CaptureFixture[str]) -> str:
    async def go() -> None:
        async with database(w):
            w.as_pod(w.first)
            await respond(w.inbound(f"please {SENT}"))
            await settled(w, 2)
            await asyncio.sleep(0.2)

    logs.setup()
    capsys.readouterr()
    run(go(), 30)
    got = capsys.readouterr()
    return got.out + got.err


def test_trigger_a_logs_one_line_of_ids_and_counts_and_nothing_said(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.first.model.script = [*[sentinel_round(n) for n in range(1, 7)], ANSWER]
    out = logged(world, capsys)
    (line,) = events(out, "respond.escalated")
    assert (line["trigger"], line["rounds"], line["from_route"], line["to_route"]) == ("a", "6", "chat", "escalated")
    assert line["conversation"].isdigit() and line["duration_ms"].isdigit()
    assert SENT not in out


def test_trigger_b_logs_one_line_and_not_the_line_she_said(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.first.model.script = [escalating(f"One moment, {SENT}."), ANSWER]
    out = logged(world, capsys)
    (line,) = events(out, "respond.escalated")
    assert (line["trigger"], line["rounds"], line["from_route"], line["to_route"]) == ("b", "0", "chat", "escalated")
    assert SENT not in out


def test_trigger_b_after_two_rounds_logs_the_rounds_made(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.first.model.script = [*rounds(2), escalating(), ANSWER]
    (line,) = events(logged(world, capsys), "respond.escalated")
    assert (line["trigger"], line["rounds"]) == ("b", "2")


def test_a_turn_answered_in_time_logs_no_escalation(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    async def go() -> Any:
        async with database(world):
            world.as_pod(world.first)
            world.first.model.script = [*rounds(1), ANSWER]
            await respond(world.inbound(f"please {SENT}"))
            await settled(world, 1)

    logs.setup()
    capsys.readouterr()
    run(go(), 30)
    got = capsys.readouterr()
    assert events(got.out + got.err, "respond.escalated") == [] and SENT not in got.out + got.err
