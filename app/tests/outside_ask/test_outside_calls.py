"""`Outside`: what a tainted turn does with each call, what taints a turn and how the taint is recorded."""

from dataclasses import replace

from ashley.inference.model import ToolResult
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.tools.outside import Outside
from ashley.tools.outside_config import load
from outside_ask_support import (CONVERSATION, SPEAKER, STANDING, TURN, Fake, Memory, Tainted, asked, build, run, small,
                                 spec)

CONFIG = load()


def held(memory: Memory) -> tuple[str, ...]:
    found = memory.rows.get((SPEAKER, OUTSIDE.name, None))
    return () if found is None else tuple(c.tool for c in found.payload.calls)


def test_an_origin_taint_holds_a_change_from_the_first_call() -> None:
    async def go() -> None:
        outside, inner, memory = build(tainted="watch")
        got = await outside.call(asked("lamp", on="yes"))
        assert not got.is_error and "held" in got.content and inner.ran == []
        stored = memory.rows[(SPEAKER, OUTSIDE.name, None)]
        assert stored.payload.calls[0].arguments == {"on": "yes"} and stored.turn_id == TURN
        assert stored.conversation_id == CONVERSATION and outside.held == 1

    run(go())


def test_a_read_that_taints_then_a_change_in_one_round_holds_the_change() -> None:
    async def go() -> None:
        steps = Tainted()
        outside, inner, memory = build(steps=steps)
        await outside.call(asked("peek"))
        assert outside.tainted is None
        await outside.call(asked("look", "c2"))
        assert outside.tainted == "look" and steps.seen == ["look"]
        await outside.call(asked("lamp", "c3"))
        assert [c.name for c in inner.ran] == ["peek", "look"] and held(memory) == ("lamp",)

    run(go())


def test_a_result_says_whether_it_taints_over_its_spec() -> None:
    async def go() -> None:
        fake = Fake((spec("quiet", reads=True, outside=True), spec("loud", reads=True, outside=False)),
                    {"quiet": ToolResult("x", "", outside=False), "loud": ToolResult("x", "", outside=True)})
        outside, _, _ = build(fake)
        await outside.call(asked("quiet"))
        assert outside.tainted is None
        await outside.call(asked("loud", "c2"))
        assert outside.tainted == "loud"

    run(go())


def test_an_unknown_tool_taints_and_a_tainted_turn_holds_it() -> None:
    async def go() -> None:
        outside, inner, memory = build()
        await outside.call(asked("mystery"))
        assert outside.tainted == "mystery" and inner.ran[0].name == "mystery"
        await outside.call(asked("mystery", "c2"))
        assert len(inner.ran) == 1 and held(memory) == ("mystery",)

    run(go())


def test_the_taint_is_recorded_once_and_before_the_result_returns() -> None:
    async def go() -> None:
        steps = Tainted()
        outside, _, _ = build(steps=steps)
        await outside.call(asked("look"))
        await outside.call(asked("look", "c2"))
        assert steps.seen == ["look"]

    run(go())


def test_a_runner_that_loses_the_turn_at_the_taint_raises_and_the_turn_stays_untainted() -> None:
    async def go() -> None:
        outside, _, _ = build(steps=Tainted(raises=True))
        try:
            await outside.call(asked("look"))
        except RuntimeError:
            pass
        else:
            raise AssertionError("the loss must propagate")
        assert outside.tainted is None

    run(go())


def test_a_resumed_tainted_turn_holds_a_change() -> None:
    async def go() -> None:
        outside, inner, memory = build(tainted="look")
        await outside.call(asked("lamp"))
        assert inner.ran == [] and held(memory) == ("lamp",)

    run(go())


def test_held_calls_accumulate_without_doubles_up_to_the_most() -> None:
    async def go() -> None:
        outside, inner, memory = build(tainted="look", config=small(max_calls=2))
        await outside.call(asked("lamp", "a", n=1))
        await outside.call(asked("lamp", "b", n=1))
        assert held(memory) == ("lamp",)
        await outside.call(asked("garage", "c"))
        refused = await outside.call(asked("lamp", "d", n=2))
        assert refused.is_error and held(memory) == ("lamp", "garage") and inner.ran == []

    run(go())


def test_the_same_arguments_in_another_order_are_the_same_call() -> None:
    async def go() -> None:
        outside, _, memory = build(tainted="look")
        await outside.call(asked("lamp", "a", x=1, y=2))
        await outside.call(asked("lamp", "b", y=2, x=1))
        assert held(memory) == ("lamp",)

    run(go())


def test_arguments_too_long_to_show_are_refused_not_held() -> None:
    async def go() -> None:
        outside, _, memory = build(tainted="look", config=small(max_argument_chars=30))
        got = await outside.call(asked("lamp", text="x" * 200))
        assert got.is_error and held(memory) == ()
        assert not (await outside.call(asked("lamp", "c2", text="x"))).is_error

    run(go())


def test_a_tool_that_agrees_is_refused_in_a_tainted_turn_and_runs_in_a_clean_one() -> None:
    async def go() -> None:
        outside, inner, memory = build(tainted="look")
        assert (await outside.call(asked("confirm"))).is_error
        assert inner.ran == [] and held(memory) == ()
        clean, inner, _ = build()
        assert not (await clean.call(asked("confirm"))).is_error and [c.name for c in inner.ran] == ["confirm"]

    run(go())


def test_where_the_reply_is_not_private_a_change_is_refused() -> None:
    async def go() -> None:
        for standing in (replace(STANDING, private=False), None):
            outside, inner, memory = build(standing=standing, tainted="look")
            got = await outside.call(asked("lamp"))
            assert got.is_error and inner.ran == [] and held(memory) == ()

    run(go())


def test_a_clean_turn_runs_its_changes() -> None:
    async def go() -> None:
        outside, inner, memory = build()
        assert not (await outside.call(asked("lamp"))).is_error
        assert [c.name for c in inner.ran] == ["lamp"] and held(memory) == ()

    run(go())


def test_the_receipts_name_each_held_call_in_full_and_only_for_this_turn() -> None:
    async def go() -> None:
        outside, inner, _ = build(tainted="look")
        assert await outside.receipts() is None
        await outside.call(asked("lamp", "a", room="the porch"))
        await outside.call(asked("garage", "b"))
        receipts = await outside.receipts()
        assert receipts is not None and receipts.done == ()
        assert [h.detail for h in receipts.held] == [f'{CONFIG.unlabelled} (room: "the porch")', CONFIG.unlabelled]
        other = Outside(inner, STANDING, (CONVERSATION, TURN + 1))
        assert await other.receipts() is None

    run(go())
