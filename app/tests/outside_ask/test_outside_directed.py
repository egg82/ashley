"""Directed tests for what the blind suite's mutant run left alive: the taint a `Landing` starts with, a held call that
is not offered at agreeing time, what `outside.carried_out` logs, and the count in `outside.held`."""

import logging
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import Proposals
from ashley.tools.outside import CARRY_OUT, Outside
from outside_ask_support import HOUSEHOLD, SPEAKER, STANDING, TURN, Fake, Memory, asked, build, run, TOOLS

LIMITS = load_limits()
WEB = Inbound(household_id=HOUSEHOLD, thread="person:7:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=SPEAKER, shared=False, place=None, channel="web", taint=None)


async def held_by(landing: Landing) -> list[str]:
    memory = Memory()
    services.register(Proposals, memory)
    await landing.call(ToolCall("c", "mystery_change", {}))
    found = await memory.pending(SPEAKER, 40, OUTSIDE)
    return [] if found is None else [c.tool for c in found.payload.calls]


@pytest.mark.parametrize(("inbound", "saved", "held"), [
    (WEB, None, []),
    (replace(WEB, taint="watch"), None, ["mystery_change"]),
    (replace(WEB, taint="stranger"), None, ["mystery_change"]),
    (WEB, "look_up", ["mystery_change"]),
])
def test_a_landing_starts_tainted_by_its_origin_or_by_its_checkpoint(inbound: Inbound, saved: str | None,
                                                                     held: list[str]) -> None:
    async def go() -> None:
        assert await held_by(Landing(inbound, (40, 100), LIMITS, saved)) == held

    run(go())


def test_a_held_call_the_source_no_longer_offers_does_not_stop_the_ones_after_it() -> None:
    async def go() -> None:
        outside, _, _ = build(tainted="look")
        await outside.call(asked("garage", "a"))
        await outside.call(asked("lamp", "b"))
        fake = Fake(tuple(s for s in TOOLS if s.name != "garage"))
        await Outside(fake, STANDING, (40, TURN + 1)).call(asked(CARRY_OUT, "x"))
        assert [c.name for c in fake.ran] == ["lamp"]

    run(go())


def test_carrying_out_logs_no_result_text(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        fake = Fake(TOOLS, {"lamp": ToolResult("", "PLANTED-result-text")})
        outside, _, _ = build(fake, tainted="look")
        await outside.call(asked("lamp", "a"))
        await Outside(fake, STANDING, (40, TURN + 1)).call(asked(CARRY_OUT, "x"))
        assert any(r.getMessage() == "outside.carried_out" for r in caplog.records)
        assert "PLANTED-result-text" not in repr([r.__dict__ for r in caplog.records])

    run(go())


def test_the_held_log_counts_the_calls_not_the_proposal_it_stored(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        first, _, _ = build(tainted="look")
        await first.call(asked("lamp", "a"))
        await first.call(asked("garage", "b"))
        later = Outside(Fake(TOOLS), STANDING, (40, TURN + 1), tainted="look")
        await later.call(asked("lamp", "c"))
        counts = [getattr(r, "fields", {}).get("calls") for r in caplog.records if r.getMessage() == "outside.held"]
        assert counts == [1, 2, 1]

    run(go())
