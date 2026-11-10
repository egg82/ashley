"""What a turn's tool loop does to the checkpoint's `tainted` as it reads: the stored checkpoint, as each model step finds
it, names the first tool whose result taints, and a result that does not taint leaves it null. Real Conversations and
`InFlight`; the model and the tools are fakes (`taint_fields_blind_support.SPECS`)."""

import pytest
from ashley.channels.model import Taint as Origin
from ashley.inference.model import ToolCalls
from ashley.inference.reply import Reply
from ashley.channels.respond import respond
from contract.conversations_support import run
from taint_fields_blind_support import (BIG, CHANGE, GHOST, INSIDE, NARROWED, OUTSIDE, OUTSIDE_TOO, PLAIN,
                                        UNSTATED_CHANGE, WIDENED)
from taint_fields_blind_world_support import DONE, World, calls, results_sent, world


async def turn(w: World, *rounds: str | tuple[str, ...], taint: Origin | None = None) -> list[str | None]:
    """A person's turn whose model asks for each of `rounds` (one name, or a tuple of names for one round) and then
    answers; `Checkpoint.tainted` as stored at each model step."""
    w.model.seen.clear()
    script: list[ToolCalls | Reply | Exception] = [calls(*([r] if isinstance(r, str) else r)) for r in rounds]
    w.model.script = [*script, DONE]
    await respond(w.inbound(taint=taint))
    assert w.model.script == [], "control: the model was asked for every step"
    return w.tainted_at_each_step()


@pytest.mark.parametrize("tool", [OUTSIDE, PLAIN, UNSTATED_CHANGE])
def test_the_checkpoint_names_the_tool_whose_result_tainted_the_turn(db_url: str, tool: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, tool) == [None, tool]
            assert results_sent(w.model.prompts[1])["c1"].content == f'{{"ran": "{tool}"}}'

    run(go())


@pytest.mark.parametrize("tool", [INSIDE, CHANGE, NARROWED])
def test_a_result_that_carries_nothing_from_outside_leaves_the_turn_untainted(db_url: str, tool: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, tool) == [None, None]
            assert [c.name for c in w.tools.ran] == [tool], "control: the tool ran"

    run(go())


def test_a_result_can_taint_though_its_spec_says_it_does_not(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, WIDENED) == [None, WIDENED]

    run(go())


def test_a_name_that_is_not_in_the_catalogue_taints(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, GHOST) == [None, GHOST]

    run(go())


def test_a_result_cut_for_length_still_taints(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, BIG) == [None, BIG]
            assert len(results_sent(w.model.prompts[1])["c1"].content) < 1_000_000, "control: it was cut"

    run(go())


def test_a_turn_that_reads_nothing_outside_is_never_tainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w) == [None]
            assert await turn(w, INSIDE, INSIDE) == [None, None, None]

    run(go())


def test_the_first_tainting_tool_of_a_round_is_the_one_named(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, (INSIDE, OUTSIDE, OUTSIDE_TOO)) == [None, OUTSIDE]

    run(go())


def test_a_later_tainting_tool_does_not_replace_the_first(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, OUTSIDE, OUTSIDE_TOO, INSIDE) == [None, OUTSIDE, OUTSIDE, OUTSIDE]

    run(go())


def test_a_taint_is_not_cleared_by_a_household_read(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, OUTSIDE, INSIDE, CHANGE) == [None, OUTSIDE, OUTSIDE, OUTSIDE]

    run(go())


def test_a_read_after_household_reads_taints_from_that_round_on(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, INSIDE, OUTSIDE_TOO, INSIDE) == [None, None, OUTSIDE_TOO, OUTSIDE_TOO]

    run(go())


def test_the_next_turn_of_the_conversation_starts_untainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert await turn(w, OUTSIDE) == [None, OUTSIDE]
            assert await turn(w, INSIDE) == [None, None]

    run(go())


def test_a_turn_started_by_an_outsider_keeps_its_origin_in_the_checkpoint_at_every_step(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await turn(w, INSIDE, OUTSIDE, taint="stranger")
            origins = [c.inbound.taint for c in w.model.seen if c is not None]
            assert origins == ["stranger"] * 3

    run(go())


def test_a_persons_own_turn_has_no_origin_in_the_checkpoint(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await turn(w, OUTSIDE)
            assert [c.inbound.taint for c in w.model.seen if c is not None] == [None, None]

    run(go())
