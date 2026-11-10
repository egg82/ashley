"""A turn resumed after its runner was killed (`resume.sweep`) is tainted exactly as it was, and taints as it goes on:
its first model step finds the checkpoint's `tainted` as the dead runner saved it, a taint never clears, and a read that
had no result when the runner died taints when the next runner runs it. Real Conversations and `InFlight`."""

from ashley.channels import resume
from ashley.inference.model import ToolResult
from contract.conversations_support import run
from dataclasses import replace
from taint_fields_blind_support import CHANGE, INSIDE, OUTSIDE, OUTSIDE_TOO
from taint_fields_blind_world_support import DONE, asking, calls, world


def test_a_tainted_turn_resumes_tainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(tainted=OUTSIDE)
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert w.tainted_at_each_step() == [OUTSIDE]

    run(go())


def test_an_untainted_turn_resumes_untainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert w.tainted_at_each_step() == [None]

    run(go())


def test_a_tainted_turn_stays_tainted_through_the_rest_of_its_rounds(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", INSIDE)), tainted=OUTSIDE)
            w.model.script = [calls(INSIDE), calls(CHANGE), DONE]
            await resume.sweep()
            assert w.tainted_at_each_step() == [OUTSIDE, OUTSIDE, OUTSIDE]

    run(go())


def test_the_taint_a_resumed_turn_had_is_not_replaced_by_a_later_tainting_tool(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(tainted=OUTSIDE)
            w.model.script = [calls(OUTSIDE_TOO), DONE]
            await resume.sweep()
            assert w.tainted_at_each_step() == [OUTSIDE, OUTSIDE]

    run(go())


def test_a_read_with_no_result_when_the_runner_died_taints_when_it_runs_again(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", OUTSIDE)))
            w.model.script = [DONE]
            await resume.sweep()
            assert [c.id for c in w.tools.ran] == ["c1"], "control: the read was run by the second runner"
            assert w.tainted_at_each_step() == [OUTSIDE]

    run(go())


def test_a_household_read_that_was_in_flight_leaves_a_resumed_turn_untainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", INSIDE)))
            w.model.script = [DONE]
            await resume.sweep()
            assert [c.id for c in w.tools.ran] == ["c1"], "control: the read was run by the second runner"
            assert w.tainted_at_each_step() == [None]

    run(go())


def test_a_resumed_untainted_turn_taints_when_it_goes_on_to_read_outside(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", INSIDE)))
            w.model.script = [calls(OUTSIDE), DONE]
            await resume.sweep()
            assert w.tainted_at_each_step() == [None, OUTSIDE]

    run(go())


def test_a_result_the_dead_runner_already_has_is_not_run_again_and_the_turn_stays_tainted(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            progress = asking(("c1", OUTSIDE))
            progress = replace(progress, done={"c1": ToolResult("c1", '{"ran": "fetch"}', outside=True)})
            await w.orphan(progress, tainted=OUTSIDE)
            w.model.script = [DONE]
            await resume.sweep()
            assert w.tools.ran == [], "control: the finished read was not run again"
            assert w.tainted_at_each_step() == [OUTSIDE]

    run(go())


def test_the_origin_of_a_resumed_turn_is_the_one_it_began_with(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(taint="stranger")
            w.model.script = [DONE]
            await resume.sweep()
            assert [c.inbound.taint for c in w.model.seen if c is not None] == ["stranger"]

    run(go())


def test_a_resumed_person_turn_has_no_origin(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [DONE]
            await resume.sweep()
            assert [c.inbound.taint for c in w.model.seen if c is not None] == [None]

    run(go())
