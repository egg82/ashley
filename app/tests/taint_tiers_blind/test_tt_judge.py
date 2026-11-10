"""The action judge as `Outside` uses it: the Null Object asks and calls no provider; whatever a registered judge is
given carries no outside text; a judge that fails, times out or answers nonsense means ask, never run."""

import asyncio

import pytest
from ashley import services
from ashley.inference.inference import Inference
from ashley.inference.model import ToolSpec
from taint_tiers_blind_support import (PLANT, PROMPT, READ_OUTSIDE, ActionJudge, Source, SpyJudge, Tiered, ask_null,
                                       scenario, seen_by, spec, taint_the_turn)
from wake_support import Model

PROMPT_ARGS: dict[str, object] = {"session": "s-9", "prompt": f"{PLANT} rm -rf the repo"}


def outside_source() -> Source:
    src = Source((spec(READ_OUTSIDE, True, True), ToolSpec(PROMPT, PROMPT, {"type": "object"}, outside=False)))
    src.answers[READ_OUTSIDE] = (f"the page says {PLANT}", True)
    return src


def test_the_null_judge_answers_ask() -> None:
    assert asyncio.run(ask_null()).decision == "ask"


def test_a_tier_c_call_is_held_by_the_null_judge_and_no_provider_is_called(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        model = Model()
        services.register(Inference, model)
        try:
            src = outside_source()
            o = taint_the_turn(src, t.w, None)
            await t.w.call(o, READ_OUTSIDE)
            got = await t.w.call(o, PROMPT, PROMPT_ARGS)
            assert "held" in got.content and src.reached(PROMPT) == []
            assert [c for c, _ in await t.w.held()] == [PROMPT] and model.prompts == []
        finally:
            services.unregister(Inference)

    scenario(db_url, body)


def test_the_judge_is_never_given_a_tool_result_or_free_text_from_outside(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        spy = SpyJudge("ask")
        services.register(ActionJudge, spy)
        src = outside_source()
        o = taint_the_turn(src, t.w, None)
        await t.w.call(o, READ_OUTSIDE)
        await t.w.call(o, PROMPT, PROMPT_ARGS)
        assert PLANT not in seen_by(spy)
        assert src.reached(PROMPT) == []
        if spy.asked:
            assert str(len(str(PROMPT_ARGS["prompt"]))) in seen_by(spy), "free text arrives as its length"

    scenario(db_url, body)


def test_the_spy_can_see_a_plant_so_an_empty_result_means_something() -> None:
    spy = SpyJudge()
    spy.asked.append((("words",), {"prompt": PLANT}))
    assert PLANT in seen_by(spy)


@pytest.mark.parametrize("fault", ["raises", "timeout", "invalid"])
def test_a_judge_that_fails_or_answers_nonsense_means_the_call_is_held_not_run(db_url: str, fault: str) -> None:
    async def body(t: Tiered) -> None:
        services.register(ActionJudge, SpyJudge("run", fault))
        src = outside_source()
        o = taint_the_turn(src, t.w, None)
        await t.w.call(o, READ_OUTSIDE)
        got = await t.w.call(o, PROMPT, PROMPT_ARGS)
        assert "held" in got.content and src.reached(PROMPT) == []
        assert [c for c, _ in await t.w.held()] == [PROMPT]

    scenario(db_url, body)


def test_a_tool_the_source_does_not_offer_is_judged_and_held(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        src = outside_source()
        o = taint_the_turn(src, t.w, "look_up")
        got = await t.w.call(o, "no_such_tool", {"x": 1})
        assert "held" in got.content and src.reached() == []

    scenario(db_url, body)


def test_a_tool_whose_spec_names_no_tier_is_judged_so_it_is_held(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        src = Source((spec("fresh_change", False, False),))
        o = taint_the_turn(src, t.w, "look_up")
        got = await t.w.call(o, "fresh_change", {})
        assert "held" in got.content and src.reached() == []

    scenario(db_url, body)
