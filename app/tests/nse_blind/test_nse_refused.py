"""A turn refused after its first line went out is wrapped up on the `wrap_up` task, else the fixed line; never silent."""

import pytest
from ashley.channels import refused, unsaid
from ashley.channels.respond import RespondRefused, respond
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolSpec
from ashley.inference.reply import Reply
from contract.conversations_support import run
from later_support import Logged
from nse_blind_support import CHECKING, WRAPPED, World, database, until


HELD = (CHECKING.text, True)


def _ended(logged: Logged) -> list[dict[str, str]]:
    return logged.events("respond.ended")


def test_a_refusal_after_the_held_line_is_wrapped_up_on_the_wrap_up_task(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.model.script = [CHECKING, InferenceRefused("no"), WRAPPED]

    async def go() -> None:
        async with database(world):
            out = await respond(world.inbound())
            assert out.follows
            await until(lambda: len(world.hers()) >= 2)
            await until(lambda: world.work() == 0)

    run(go())
    assert world.hers() == [HELD, (WRAPPED.text, False)]
    assert world.model.tasks() == ["chat", "chat", "wrap_up"]
    prompt = world.model.calls[2][1]
    assert prompt.tool_choice == "none"
    assert prompt.messages[-1] == unsaid.ASK
    assert [(e["reason"], e["recovery"]) for e in _ended(logged)] == [("refused", "wrap_up")]


def test_the_wrap_up_step_carries_the_exchange_so_far_and_the_same_tools_listed(world: World) -> None:
    world.model.script = [CHECKING, InferenceRefused("no"), WRAPPED]

    async def go() -> None:
        async with database(world):
            await respond(world.inbound("turn on the lamp"))
            await until(lambda: len(world.hers()) >= 2)

    run(go())
    chat_prompt = world.model.calls[0][1]
    wrap_prompt = world.model.calls[2][1]
    assert wrap_prompt.messages[:-1] == chat_prompt.messages
    assert wrap_prompt.system == chat_prompt.system


@pytest.mark.parametrize("second", [InferenceRefused("again"), InferenceUnavailable("down"),
                                    Reply(spoken="", text=""), ToolCalls((ToolCall("c1", "look", {}),))])
def test_a_wrap_up_that_fails_or_says_nothing_ends_on_the_fixed_line(world: World, capsys: pytest.CaptureFixture[str],
                                                                      second: Exception | Reply | ToolCalls) -> None:
    logged = Logged(capsys)
    world.model.script = [CHECKING, InferenceRefused("no"), second]

    async def go() -> None:
        async with database(world):
            await respond(world.inbound(medium="spoken"))
            await until(lambda: len(world.hers()) >= 2)
            await until(lambda: world.work() == 0)

    run(go())
    assert world.hers() == [HELD, (unsaid.LINE, False)]
    assert [(e["reason"], e["recovery"]) for e in _ended(logged)] == [("refused", "fixed_line")]


def test_a_refusal_before_any_line_went_out_is_not_wrapped_up(world: World) -> None:
    world.model.script = [InferenceRefused("no")]

    async def go() -> None:
        async with database(world):
            with pytest.raises(RespondRefused):
                await respond(world.inbound())

    run(go())
    assert world.model.tasks() == ["chat"]
    assert world.hers() == []


def test_the_wrap_up_task_is_a_task_with_routes() -> None:
    assert refused.TASK == "wrap_up"


# --- wrapped, by itself ------------------------------------------------------------------------------------------

SYSTEM = {"default": SystemPrompt("system")}
TOOLS = (ToolSpec("look", "see", {"type": "object"}, reads=True),)
ENTRIES = (Message("person", "is the door locked"), Message("ashley", "Let me check."), Message("person", "well?"))


class Step:
    """A `step` that records each call and answers from `answers`."""

    def __init__(self, *answers: Reply | ToolCalls | InferenceRefused | InferenceUnavailable) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[Task, Prompt, int | None]] = []

    async def __call__(self, task: Task, prompt: Prompt, conversation_id: int | None) -> Reply | ToolCalls:
        self.calls.append((task, prompt, conversation_id))
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


def test_wrapped_asks_once_on_the_wrap_up_task_under_tool_choice_none() -> None:
    step = Step(WRAPPED)

    async def go() -> Reply:
        return await refused.wrapped(step, SYSTEM, TOOLS, ENTRIES, "text", 7)

    got: list[Reply] = []

    async def collect() -> None:
        got.append(await go())

    run(collect())
    assert got == [WRAPPED]
    assert len(step.calls) == 1
    task, prompt, conversation_id = step.calls[0]
    assert (task, conversation_id) == ("wrap_up", 7)
    assert prompt.system == SYSTEM and prompt.tools == TOOLS and prompt.tool_choice == "none"
    assert prompt.messages == (*ENTRIES, unsaid.ASK)


@pytest.mark.parametrize("answer", [InferenceRefused("x"), InferenceUnavailable("x"), ToolCalls((ToolCall("c", "look", {}),)),
                                    Reply(spoken="", text="")])
def test_wrapped_answers_the_fixed_line_when_the_step_gives_nothing_to_say(answer: Reply | ToolCalls | InferenceRefused | InferenceUnavailable) -> None:
    step = Step(answer)
    got: list[Reply] = []

    async def collect() -> None:
        got.append(await refused.wrapped(step, SYSTEM, TOOLS, ENTRIES, "text", None))

    run(collect())
    assert got == [unsaid.fixed()]
    assert len(step.calls) == 1


def test_wrapped_judges_emptiness_by_the_medium_it_is_said_in() -> None:
    """A reply with only text has nothing to say aloud; the same reply is fine as text."""
    text_only = Reply(spoken="", text="Written only.")
    out: list[Reply] = []

    async def collect() -> None:
        out.append(await refused.wrapped(Step(text_only), SYSTEM, TOOLS, ENTRIES, "text", None))
        out.append(await refused.wrapped(Step(text_only), SYSTEM, TOOLS, ENTRIES, "spoken", None))

    run(collect())
    assert out[0] == text_only
    assert out[1] == unsaid.fixed()


def test_wrapped_logs_one_ending_per_call(capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)

    async def collect() -> None:
        await refused.wrapped(Step(WRAPPED), SYSTEM, TOOLS, ENTRIES, "text", 9)
        await refused.wrapped(Step(InferenceRefused("x")), SYSTEM, TOOLS, ENTRIES, "text", 9)

    run(collect())
    got = [(e["reason"], e["conversation"], e["recovery"]) for e in logged.events("respond.ended")]
    assert got == [("refused", "9", "wrap_up"), ("refused", "9", "fixed_line")]
