"""`tool_loop.answer` with `hold`: a reply that is not the answer (`answers=False`) under tool choice `auto` while tools
are offered is returned as `Held` (the prompt entries so far, the round it came in, the tool calls made before it) when
`hold` is set, and dropped and asked again under `auto` when it is not; `resume` asks the held step again under
`auto` on the same entries plus the act note, the tools offered as a holdable turn offers them (`aside.offered`), and goes on as
`answer` would, never holding again."""

from ashley.channels import aside, unsaid
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held, answer, resume
from ashley.inference.model import Message, SystemPrompt, ToolCalls, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from inference_support import settle
from turns_support import OTHER_SPEC, SPEC, World, asks, world as world

HISTORY = (Message("person", "is it raining"),)
SYSTEM = {"default": SystemPrompt("you are her")}
TOOLS = (SPEC, OTHER_SPEC)
LIMITS = Limits(max_tool_rounds=3, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0)
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
FINAL = Reply(spoken="No rain.", text="No rain.")


def ask(hold: bool, tools: tuple[ToolSpec, ...] = TOOLS, limits: Limits = LIMITS) -> Answer | Held:
    return settle(answer("chat", SYSTEM, HISTORY, tools, limits, hold=hold))


def held_of(result: Answer | Held) -> Held:
    assert isinstance(result, Held), f"expected Held, got {result!r}"
    return result


def answered(result: Answer | Held) -> Answer:
    assert isinstance(result, Answer), f"expected Answer, got {result!r}"
    return result


def choices(world: World) -> list[str]:
    return [a.prompt.tool_choice for a in world.inference.asked]


def test_without_hold_a_non_answer_is_asked_again_under_auto(world: World) -> None:
    world.inference.script = [CHECKING, FINAL]
    result = answered(ask(hold=False))
    assert choices(world) == ["auto", "auto"]
    assert result.reply == FINAL and result.required == 1


def test_an_answer_needs_no_further_step_and_counts_no_required(world: World) -> None:
    world.inference.script = [FINAL]
    result = answered(ask(hold=True))
    assert result == Answer(FINAL, 0, 0, 0)
    assert choices(world) == ["auto"]


def test_with_hold_the_first_non_answer_is_returned_and_nothing_more_is_asked(world: World) -> None:
    world.inference.script = [CHECKING, FINAL]
    held = held_of(ask(hold=True))
    assert held == Held(CHECKING, HISTORY, 0, 0)
    assert choices(world) == ["auto"]


def test_a_held_reply_after_tool_rounds_carries_the_rounds_calls_and_entries(world: World) -> None:
    one = asks("lights", "weather", round_=1)
    world.inference.script = [one, CHECKING]
    held = held_of(ask(hold=True))
    assert held.reply == CHECKING
    assert held.rounds == 1 and held.calls == 2
    assert held.entries[:1] == HISTORY
    assert [type(e) for e in held.entries[1:]] == [ToolCalls, ToolResults]
    assert held.entries[1] == one
    assert choices(world) == ["auto", "auto"]


def test_two_rounds_before_the_hold_are_counted(world: World) -> None:
    world.inference.script = [asks("lights", round_=1), asks("weather", round_=2), CHECKING]
    held = held_of(ask(hold=True))
    assert (held.rounds, held.calls) == (2, 2)
    assert len(held.entries) == 1 + 2 * 2


def test_no_hold_when_no_tools_are_offered(world: World) -> None:
    world.inference.script = [CHECKING, FINAL]
    result = ask(hold=True, tools=())
    assert isinstance(result, Answer), "with no tools to call, a non-answer cannot be re-asked into one"
    assert not isinstance(result, Held)


def test_a_non_answer_under_the_closing_step_is_not_held_but_asked_once_to_say_where_it_stands(world: World) -> None:
    limits = Limits(max_tool_rounds=1, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0)
    world.inference.script = [asks("lights"), CHECKING, FINAL]
    result = answered(ask(hold=True, limits=limits))
    assert choices(world) == ["auto", "none", "none"]
    assert result.reply == FINAL


def test_resume_asks_the_held_step_again_under_auto_on_the_same_entries(world: World) -> None:
    world.inference.script = [asks("lights", round_=1), CHECKING]
    held = held_of(ask(hold=True))
    world.inference.asked.clear()
    world.inference.script = [FINAL]
    result = settle(resume(held, "chat", SYSTEM, TOOLS, LIMITS))
    (again,) = world.inference.asked
    assert again.prompt.tool_choice == "auto"
    assert again.prompt.messages == (*held.entries, unsaid.ACT)
    assert again.prompt.tools == aside.offered(TOOLS)
    assert result.reply == FINAL and result.required == 1


def test_resume_goes_on_from_the_held_round_as_answer_would(world: World) -> None:
    world.inference.script = [asks("lights", round_=1), CHECKING]
    held = held_of(ask(hold=True))
    world.inference.asked.clear()
    world.tools.called.clear()
    world.inference.script = [asks("weather", round_=2), FINAL]
    result = settle(resume(held, "chat", SYSTEM, TOOLS, LIMITS))
    assert choices(world) == ["auto", "auto"]
    assert [c.name for c in world.tools.called] == ["weather"]
    assert result.reply == FINAL and result.required == 1
    assert (result.rounds, result.calls) == (2, 2)


def test_resume_counts_the_rounds_already_made_against_the_limit(world: World) -> None:
    limits = Limits(max_tool_rounds=2, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0)
    world.inference.script = [asks("lights", round_=1), CHECKING]
    held = held_of(ask(hold=True, limits=limits))
    world.inference.asked.clear()
    world.inference.script = [asks("weather", round_=2)]
    world.inference.then = FINAL
    result = settle(resume(held, "chat", SYSTEM, TOOLS, limits))
    assert choices(world) == ["auto", "none"]
    assert result.reply == FINAL


def test_after_resume_a_later_non_answer_is_asked_again_never_held(world: World) -> None:
    world.inference.script = [CHECKING]
    held = held_of(ask(hold=True))
    world.inference.asked.clear()
    world.inference.script = [asks("lights", round_=1), CHECKING, FINAL]
    result = settle(resume(held, "chat", SYSTEM, TOOLS, LIMITS))
    assert choices(world) == ["auto", "auto", "auto"]
    assert isinstance(result, Answer) and result.reply == FINAL and result.required == 2
