"""Agreeing stays out of a tainted turn whatever the tier: `house_confirm`, `arm_reminder` and `carry_out` are refused."""

import logging

import pytest
from taint_tiers_blind_support import (CARRY_OUT, DO, PROMPT, Source, Tiered, agreeing_spec, events, hold_two, scenario,
                                       taint_the_turn)

AGREEING = ["house_confirm", "arm_reminder"]


@pytest.mark.parametrize("name", AGREEING)
@pytest.mark.parametrize("tainted", ["look_up", "watch", "inherited"])
def test_an_agreeing_tool_is_refused_in_a_tainted_turn_even_labelled_tier_b(db_url: str, name: str, tainted: str) -> None:
    async def body(t: Tiered) -> None:
        src = Source((agreeing_spec(name),))
        got = await t.w.call(taint_the_turn(src, t.w, tainted), name, {})
        assert got.is_error and src.reached() == [] and await t.w.held() == []

    scenario(db_url, body)


@pytest.mark.parametrize("name", AGREEING)
def test_the_refusal_is_logged_as_agreeing_tainted(db_url: str, name: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(t: Tiered) -> None:
        caplog.set_level(logging.INFO)
        await t.w.call(taint_the_turn(Source((agreeing_spec(name),)), t.w, "look_up"), name, {})
        assert [e["reason"] for e in events(caplog, "outside.refused")] == ["agreeing_tainted"]

    scenario(db_url, body)


def test_an_agreeing_tool_still_runs_in_an_untainted_turn(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        src = Source((agreeing_spec("house_confirm"),))
        got = await t.w.call(taint_the_turn(src, t.w, None), "house_confirm", {})
        assert not got.is_error and [c.name for c in src.reached()] == ["house_confirm"]

    scenario(db_url, body)


@pytest.mark.parametrize("tainted", ["look_up", "watch", "inherited"])
def test_carry_out_is_refused_in_a_tainted_turn_and_keeps_what_is_held(db_url: str, tainted: str) -> None:
    async def body(t: Tiered) -> None:
        first, second = await hold_two(t.w)
        src = Source(())
        got = await t.w.call(taint_the_turn(src, t.w, tainted), CARRY_OUT)
        assert got.is_error and src.reached() == []
        assert await t.w.held() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)
