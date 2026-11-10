"""`respond` for a channel that delivers later (`Inbound.later`): a reply that is not the answer is returned at once,
rendered for the medium and stored as her turn; the loop goes on in the background from that step, the answer stored as her turn
(the delivered field, before the lexicon) and queued on the `Outbox` for the thread; a failure there is logged
`respond.failed` with `later=True` and queues nothing. Without `later` the reply is asked again and the answer returned.
Logs: `respond.held`, and `later` on `respond.done` and `respond.failed`."""

from dataclasses import replace

import pytest
from ashley.channels import unsaid
from ashley.channels.model import Inbound, Medium, Outbound
from ashley.channels.outbox import OutboxUnavailable
from ashley.channels.respond import respond
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.model import ToolCalls
from ashley.inference.reply import Reply
from inference_support import settle
from later_support import FakeOutbox, Logged, until, outbox as outbox
from turns_support import HOUSE, World, asks, inbound, world as world

MARK = "zqLEAK4471"
UNREACHABLE = unsaid.UNREACHABLE
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me *check*.")
FINAL = Reply(spoken="No rain today.", text="**No rain** today.")
THREAD = "discord:1001"


def later(medium: Medium = "text", **changes: object) -> Inbound:
    return replace(inbound(thread=THREAD, kind="chat", medium=medium, place=None, speaker_id=None), later=True,
                   **changes)


async def held(i: Inbound, outbox: FakeOutbox) -> Outbound:
    """`respond`, then wait for the background part to queue the answer."""
    out = await respond(i)
    await until(lambda: outbox.added)
    return out


def run_held(i: Inbound, outbox: FakeOutbox) -> Outbound:
    return settle(held(i, outbox))


@pytest.mark.parametrize(("medium", "first", "answer"), [("spoken", CHECKING.spoken, FINAL.spoken),
                                                         ("text", CHECKING.text, FINAL.text)])
def test_the_non_answer_is_returned_at_once_and_the_answer_is_queued(
        world: World, outbox: FakeOutbox, medium: Medium, first: str, answer: str) -> None:
    world.inference.script = [CHECKING, FINAL]
    out = run_held(later(medium), outbox)
    assert out == Outbound(out.conversation_id, medium, first, follows=True)
    assert outbox.added == [(HOUSE, THREAD, Outbound(out.conversation_id, medium, answer))]


def test_the_non_answer_is_stored_before_the_answer(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]

    async def scenario() -> None:
        out = await respond(later("text"))
        assert world.conversations.turns_of(out.conversation_id) == [
            ("person", None, "turn on the lights"), ("ashley", None, CHECKING.text)]
        await until(lambda: outbox.added)
        assert world.conversations.turns_of(out.conversation_id) == [
            ("person", None, "turn on the lights"), ("ashley", None, CHECKING.text), ("ashley", None, FINAL.text)]

    settle(scenario())


def test_the_stored_answer_is_the_delivered_field_before_the_lexicon(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, Reply(spoken="Mochi is dry.", text="Mochi is dry.")]

    async def scenario() -> None:
        out = await respond(later("spoken"))
        await until(lambda: outbox.added)
        assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, "Mochi is dry.")

    settle(scenario())


def test_the_background_step_is_the_held_one_asked_again_under_auto(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]
    run_held(later(), outbox)
    first, second = world.inference.asked
    assert (first.prompt.tool_choice, second.prompt.tool_choice) == ("auto", "auto")
    assert second.prompt.messages == (*first.prompt.messages, unsaid.ACT)
    assert second.prompt.tools == first.prompt.tools


def test_tool_rounds_before_the_non_answer_are_kept_in_the_background_prompt(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [asks("lights", round_=1), CHECKING, FINAL]
    run_held(later(), outbox)
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto", "auto", "auto"]
    assert world.inference.asked[2].prompt.messages == (*world.inference.asked[1].prompt.messages, unsaid.ACT)
    assert [c.name for c in world.tools.called] == ["lights"]


def test_tool_calls_the_background_makes_are_run_and_the_answer_is_still_queued(
        world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, asks("weather", round_=1), FINAL]
    out = run_held(later(), outbox)
    assert [c.name for c in world.tools.called] == ["weather"]
    assert outbox.added[0][2] == Outbound(out.conversation_id, "text", FINAL.text)


def test_a_reply_that_is_the_answer_is_returned_whole_and_nothing_is_queued(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [FINAL]

    async def scenario() -> Outbound:
        out = await respond(later())
        await until(lambda: len(world.conversations.turns_of(out.conversation_id)) == 2)
        return out

    out = settle(scenario())
    assert out.body == FINAL.text and outbox.added == []
    assert len(world.inference.asked) == 1


def test_without_later_the_non_answer_is_asked_again_and_the_answer_returned(world: World, outbox: FakeOutbox) -> None:
    world.inference.script = [CHECKING, FINAL]
    out = settle(respond(replace(later(), later=False)))
    assert out.body == FINAL.text and outbox.added == []
    assert [a.prompt.tool_choice for a in world.inference.asked] == ["auto", "auto"]
    assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, FINAL.text)


def test_later_defaults_to_false() -> None:
    assert inbound().later is False


def test_an_unreachable_model_in_the_background_is_logged_and_queues_only_the_line_that_says_so(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.script = [CHECKING, InferenceUnavailable("none")]
    log = Logged(capsys)

    async def scenario() -> Outbound:
        out = await respond(later())
        await until(lambda: log.events("respond.failed"))
        return out

    out = settle(scenario())
    assert out.body == CHECKING.text
    (line,) = log.events("respond.failed")
    assert line["later"].lower() == "true"
    assert [added[2].body for added in outbox.added] == [UNREACHABLE] and log.events("respond.done") == []


def test_an_outbox_failure_is_logged_and_neither_queues_nor_stores_the_answer(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.script = [CHECKING, FINAL]
    outbox.add_error = OutboxUnavailable("down")
    log = Logged(capsys)

    async def scenario() -> Outbound:
        out = await respond(later())
        await until(lambda: log.events("respond.failed"))
        return out

    out = settle(scenario())
    (line,) = log.events("respond.failed")
    assert line["later"].lower() == "true"
    assert outbox.added == [] and log.events("respond.done") == []
    assert [(a, t) for a, _, t in world.conversations.turns_of(out.conversation_id)] == [
        ("person", "turn on the lights"), ("ashley", CHECKING.text)]


def test_held_is_logged_with_the_conversation_and_duration_and_no_text(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.script = [Reply(answers=False, spoken=MARK, text=MARK), Reply(spoken=MARK, text=MARK)]
    log = Logged(capsys)
    out = run_held(later(text=MARK), outbox)
    (line,) = log.events("respond.held")
    assert str(out.conversation_id) in line.values() and "duration_ms" in line
    assert MARK not in log.read()


def test_done_says_later_when_the_answer_went_through_the_outbox(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.script = [CHECKING, FINAL]
    log = Logged(capsys)

    async def scenario() -> None:
        await respond(later())
        await until(lambda: log.events("respond.done"))

    settle(scenario())
    (line,) = log.events("respond.done")
    assert line["later"].lower() == "true"


@pytest.mark.parametrize("script", [[FINAL], [CHECKING, FINAL]])
def test_done_says_not_later_when_the_answer_was_returned(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str], script: list[Reply | ToolCalls | Exception]) -> None:
    world.inference.script = script
    log = Logged(capsys)
    settle(respond(replace(later(), later=False)))
    (line,) = log.events("respond.done")
    assert line["later"].lower() == "false"
    assert log.events("respond.held") == []


def test_failed_says_not_later_for_a_failure_in_the_response_itself(
        world: World, outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.then = InferenceUnavailable("none")
    log = Logged(capsys)
    with pytest.raises(Exception):
        settle(respond(replace(later(), later=False)))
    (line,) = log.events("respond.failed")
    assert line["later"].lower() == "false"
