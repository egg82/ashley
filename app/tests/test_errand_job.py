"""The errands job through fakes on the locator: which sources it claims for, how each run ends (finish, release,
give up), when a tick stops, and that nothing it logs carries the ask or the outcome."""

import asyncio
import logging
from collections import Counter

import pytest
from ashley import services
from ashley.tools.tools import Catalogue, Tools
from ashley.inference.model import Message
from ashley.logs import Logfmt
from ashley.errands.config import CONFIG
from ashley.errands.model import Counts
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from contract.turns_support import asks
from dataclasses import replace
from ashley.inference.reply import Reply
from errand_job_support import World, reply, sources, world as world


def tick(w: World) -> Counter[str]:
    return asyncio.run(w.job().tick())


def lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [Logfmt().format(r) for r in caplog.records]


def test_a_due_errand_whose_source_answers_is_done_with_the_reply_text(world: World) -> None:
    world.owe()
    world.inference.script = [reply("I put milk on the list.")]
    counts = tick(world)
    row = world.errands.rows[1]
    assert (row.state, row.result) == ("done", "I put milk on the list.")
    assert (counts["claimed"], counts["done"]) == (1, 1)
    assert [call[1] for call in world.errands.calls if call[0] == "claim"][0] == (("house",),)


def test_the_run_is_under_the_errand_task_with_the_conversation_through_the_ask(world: World) -> None:
    world.owe()
    world.inference.script = [reply()]
    tick(world)
    task, prompt = world.inference.asked[0]
    assert task == "errand"
    said = [m for m in prompt.messages if isinstance(m, Message)]
    assert said[-1].text == "Alana: put milk on the list" and len(said) == 3
    assert "# This errand" in prompt.system["default"].text and "Alana" in prompt.system["default"].text
    assert "# Tools" in prompt.system["default"].text and "use the lights tool" in prompt.system["default"].text


def test_context_turns_bounds_the_messages(world: World) -> None:
    world.owe()
    world.inference.script = [reply()]
    asyncio.run(world.job(replace(CONFIG, context_turns=2)).tick())
    assert len(world.inference.asked[0][1].messages) == 2


def test_a_source_in_unreachable_is_not_claimed_for(world: World) -> None:
    world.tools.on_offer = sources(("house",))
    world.owe()
    counts = tick(world)
    assert world.errands.rows[1].state == "due" and counts["claimed"] == 0
    world.owe(2, "search")
    world.inference.script = [reply()]
    assert tick(world)["done"] == 1 and world.errands.rows[1].state == "due"
    assert [c[1] for c in world.errands.calls if c[0] == "claim"] == [(("search",),), (("search",),)]


def test_no_catalogue_means_nothing_answers_and_nothing_is_claimed(world: World) -> None:
    world.tools.on_offer = None
    world.owe()
    tick(world)
    assert world.errands.rows[1].state == "due"
    assert not any(c[0] == "claim" for c in world.errands.calls)
    assert any(c[0] == "sweep" for c in world.errands.calls)


def test_at_most_batch_errands_run_in_a_tick(world: World) -> None:
    for i in range(1, 6):
        world.owe(i)
    world.inference.script = [reply() for _ in range(5)]
    counts = tick(world)
    assert counts["done"] == CONFIG.batch
    assert sum(r.state == "due" for r in world.errands.rows.values()) == 5 - CONFIG.batch


def test_owed_again_releases_and_the_attempt_cap_gives_up(world: World) -> None:
    world.owe()
    world.inference.script = [Reply(spoken="Still no house.", text="Still no house.", owed="house")]
    counts = tick(world)
    assert (world.errands.rows[1].state, counts["released"]) == ("due", 1)
    world.inference.script = [Reply(spoken="Still no house.", text="Still no house.", owed="house")] * 2
    asyncio.run(world.job(replace(CONFIG, max_attempts=2)).tick())
    row = world.errands.rows[1]
    assert (row.state, row.reason) == ("given_up", "attempts")


def test_inference_unavailable_releases_and_ends_the_tick(world: World) -> None:
    world.owe(1)
    world.owe(2)
    world.inference.script = [InferenceUnavailable("down")]
    counts = tick(world)
    assert [r.state for r in world.errands.rows.values()] == ["due", "due"]
    assert (counts["claimed"], counts["released"]) == (1, 1)
    assert len(world.inference.asked) == 1


def test_a_refusal_gives_up_refused_and_the_tick_goes_on(world: World) -> None:
    world.owe(1)
    world.owe(2)
    world.inference.script = [InferenceRefused("no"), reply()]
    counts = tick(world)
    assert (world.errands.rows[1].state, world.errands.rows[1].reason) == ("given_up", "refused")
    assert world.errands.rows[2].state == "done"
    assert (counts["given_up"], counts["done"]) == (1, 1)


def test_an_unreadable_ask_is_released_not_lost(world: World) -> None:
    world.errands.add(1, world.conversation_id, 999_999)
    counts = tick(world)
    assert world.errands.rows[1].state == "due" and counts["released"] == 1


def test_tool_calls_are_counted_in_the_errand_log(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.owe()
    world.inference.script = [asks("lights"), reply("Lights are on, the list is done.")]
    with caplog.at_level(logging.INFO, logger="ashley.errands"):
        tick(world)
    line = next(x for x in lines(caplog) if "errands.done" in x)
    assert "errand=1" in line and "attempt=1" in line and "calls=1" in line
    assert world.tools.called[0].name == "lights"


def test_the_database_down_ends_the_tick_and_logs_it(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.errands.down = True
    with caplog.at_level(logging.INFO, logger="ashley.errands"):
        tick(world)
    assert "stopped=database_unavailable" in "\n".join(lines(caplog))


def test_logs_carry_counts_never_the_ask_or_the_outcome(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.errands.swept = Counts(1, 2)
    world.owe()
    world.inference.script = [reply("I put milk on the list.")]
    with caplog.at_level(logging.INFO, logger="ashley.errands"):
        tick(world)
    text = "\n".join(lines(caplog))
    assert "errands.tick" in text and "swept=3" in text and "claimed=1" in text and "done=1" in text
    assert "milk" not in text


def test_nothing_due_reads_no_catalogue_and_claims_nothing(world: World) -> None:
    asked: list[int] = []

    class Counting(type(world.tools)):
        async def catalogue(self) -> Catalogue:
            asked.append(1)
            return await super().catalogue()

    services.register(Tools, Counting())
    counts = tick(world)
    assert asked == [] and counts["claimed"] == 0
    assert not any(c[0] == "claim" for c in world.errands.calls)
    world.owe()
    world.inference.script = [reply()]
    tick(world)
    assert asked == [1]
