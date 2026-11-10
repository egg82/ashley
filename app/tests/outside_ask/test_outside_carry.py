"""`carry_out`: offered only to a later, untainted person turn that reaches the person alone, run from what was stored,
once, and a tainting result taints the agreeing turn."""

import asyncio
from dataclasses import replace

from ashley.inference.model import ToolResult
from outside_ask_support import STANDING, TURN, Fake, asked, build, run, small, spec, TOOLS
from ashley.tools.outside import CARRY_OUT, Outside


async def holding(fake: Fake | None = None) -> tuple[Fake, Outside]:
    """A tainted turn that holds two calls, and the same store seen from the next turn."""
    outside, inner, _ = build(fake, tainted="look")
    await outside.call(asked("lamp", "a", room="porch"))
    await outside.call(asked("garage", "b", door=2))
    return inner, Outside(inner, STANDING, (40, TURN + 1))


async def names(outside: Outside) -> list[str]:
    return [s.name for s in (await outside.catalogue()).specs]


def test_it_is_offered_in_a_later_untainted_person_turn_only() -> None:
    async def go() -> None:
        _, later = await holding()
        assert CARRY_OUT in await names(later)
        same, _, _ = build(tainted=None)
        assert CARRY_OUT not in await names(same)
        for standing in (replace(STANDING, agreeing=False), replace(STANDING, private=False), None):
            inner, _ = await holding()
            assert CARRY_OUT not in await names(Outside(inner, standing, (40, TURN + 1)))
        tainted = Outside(inner, STANDING, (40, TURN + 1), tainted="look")
        assert CARRY_OUT not in await names(tainted)

    run(go())


def test_it_is_not_offered_in_the_turn_that_held_or_when_nothing_is_held() -> None:
    async def go() -> None:
        outside, inner, _ = build(tainted="look")
        await outside.call(asked("lamp"))
        assert CARRY_OUT not in await names(Outside(inner, STANDING, (40, TURN)))
        empty, _, _ = build()
        assert CARRY_OUT not in await names(Outside(inner, STANDING, (41, TURN + 1)))
        assert CARRY_OUT not in await names(empty)

    run(go())


def test_it_runs_the_stored_calls_in_order_with_the_stored_arguments_once() -> None:
    async def go() -> None:
        inner, later = await holding()
        got = await later.call(asked(CARRY_OUT, "z", room="the roof"))
        assert not got.is_error
        assert [(c.name, dict(c.arguments)) for c in inner.ran] == [("lamp", {"room": "porch"}), ("garage", {"door": 2})]
        assert [c.id for c in inner.ran] == ["z.1", "z.2"]
        again = await later.call(asked(CARRY_OUT, "y"))
        assert again.is_error and len(inner.ran) == 2

    run(go())


def test_a_tool_not_offered_now_is_reported_not_run() -> None:
    async def go() -> None:
        inner, later = await holding()
        inner.specs = tuple(s for s in TOOLS if s.name != "garage")
        got = await later.call(asked(CARRY_OUT))
        assert [c.name for c in inner.ran] == ["lamp"] and "door: 2" in got.content and "not run" in got.content

    run(go())


def test_a_result_that_taints_taints_the_turn_that_agrees() -> None:
    async def go() -> None:
        fake = Fake((*TOOLS, spec("fetch", outside=True)), {"lamp": ToolResult("x", "on", outside=True)})
        _, later = await holding(fake)
        got = await later.call(asked(CARRY_OUT))
        assert got.outside is True and later.tainted == CARRY_OUT
        _, later2 = await holding()
        assert (await later2.call(asked(CARRY_OUT))).outside is False and later2.tainted is None

    run(go())


def test_it_is_refused_in_a_turn_that_has_read_outside_words_and_takes_nothing() -> None:
    async def go() -> None:
        inner, later = await holding()
        await later.call(asked("look", "r"))
        got = await later.call(asked(CARRY_OUT, "c"))
        assert got.is_error and [c.name for c in inner.ran] == ["look"]
        fresh = Outside(inner, STANDING, (40, TURN + 2))
        assert not (await fresh.call(asked(CARRY_OUT))).is_error

    run(go())


def test_without_a_proposal_it_reaches_nothing() -> None:
    async def go() -> None:
        outside, inner, _ = build()
        got = await outside.call(asked(CARRY_OUT))
        assert got.is_error and inner.ran == []

    run(go())


def test_an_expired_proposal_is_not_run() -> None:
    async def go() -> None:
        outside, inner, _ = build(tainted="look")
        await outside.call(asked("lamp"))
        later = Outside(inner, STANDING, (40, TURN + 1), config=small(proposal_ttl_s=0.001))
        await asyncio.sleep(0.01)
        assert (await later.call(asked(CARRY_OUT))).is_error and inner.ran == []

    run(go())
