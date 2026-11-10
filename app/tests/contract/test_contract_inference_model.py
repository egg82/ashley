"""`model.Prompt` validation and `system_for`, and the Null Object `Inference` the locator answers when nothing is
wired."""

from collections.abc import Mapping
from typing import TypeVar

import pytest
from ashley import services
from ashley.inference.routes import TASKS
from ashley.inference.model import Task, ToolCalls
from ashley.inference.inference import Inference, InferenceUnavailable, NullInference
from ashley.inference.model import DEFAULT_VARIANT, Message, Prompt, SystemPrompt
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from inference_support import prompt, settle
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

GOOD = (Message("person", "hello"),)


def test_a_valid_prompt_keeps_what_it_was_given() -> None:
    system = {"default": SystemPrompt("base"), "gemini": SystemPrompt("tuned")}
    messages = (Message("person", "hi"), Message("ashley", "hello"), Message("person", "again"))
    made = Prompt(system, messages)
    assert dict(made.system) == system
    assert made.messages == messages


def test_system_for_answers_the_variant_when_there_is_one_else_the_default() -> None:
    made = Prompt({"default": SystemPrompt("base"), "gemini": SystemPrompt("tuned")}, GOOD)
    assert made.system_for("gemini") == SystemPrompt("tuned")
    assert made.system_for("default") == SystemPrompt("base")
    assert made.system_for("never-heard-of") == SystemPrompt("base")
    assert made.system_for("") == SystemPrompt("base")


def test_a_prompt_with_only_a_default_answers_it_for_every_variant() -> None:
    made = Prompt({DEFAULT_VARIANT: SystemPrompt("base")}, GOOD)
    assert {made.system_for(v) for v in ("default", "claude", "x")} == {SystemPrompt("base")}


@pytest.mark.parametrize("system", [
    {}, {"gemini": "tuned"}, {"Default": "wrong case"},
    {"default": ""}, {"default": "  \n\t "},
    {"default": "ok", "gemini": ""}, {"default": "ok", "gemini": " \n"},
])
def test_a_system_without_a_default_or_with_an_empty_prompt_is_refused(system: Mapping[str, str]) -> None:
    with pytest.raises(ValueError):
        Prompt({k: SystemPrompt(v) for k, v in system.items()}, GOOD)


@pytest.mark.parametrize("messages", [
    (),
    (Message("person", ""),),
    (Message("person", "  \n "),),
    (Message("ashley", ""), Message("person", "hi")),
    (Message("person", "hi"), Message("ashley", "\t")),
    (Message("person", "hi"), Message("ashley", "hello")),
    (Message("ashley", "hello"),),
])
def test_messages_that_are_empty_blank_or_do_not_end_on_a_person_are_refused(messages: tuple[Message, ...]) -> None:
    with pytest.raises(ValueError):
        Prompt({"default": SystemPrompt("base")}, messages)


def test_each_refusal_has_a_valid_twin_so_the_cause_is_the_one_changed_thing() -> None:
    """Controls for the parametrised refusals above: the same shapes made valid are accepted."""
    Prompt({"default": SystemPrompt("base"), "gemini": SystemPrompt("tuned")},
           (Message("ashley", "a"), Message("person", "p")))
    Prompt({"default": SystemPrompt("base")}, (Message("person", "x"), Message("ashley", "y"), Message("person", "z")))


@given(st.text(alphabet=" \t\n\r\x0b\x0c  ", min_size=0, max_size=6))
def test_whitespace_alone_is_never_a_system_prompt_or_a_message(blank: str) -> None:
    with pytest.raises(ValueError):
        Prompt({"default": SystemPrompt(blank)}, GOOD)
    with pytest.raises(ValueError):
        Prompt({"default": SystemPrompt("base")}, (Message("person", blank),))


@given(st.text(min_size=1).filter(lambda s: s.strip() != ""), st.text(min_size=1).filter(lambda s: s.strip() != ""))
def test_any_text_with_a_visible_character_is_accepted_unchanged(system: str, text: str) -> None:
    made = Prompt({"default": SystemPrompt(system)}, (Message("person", text),))
    assert made.system_for("any") == SystemPrompt(system)
    first = made.messages[0]
    assert isinstance(first, Message) and first.text == text


def test_the_helper_builds_valid_prompts_that_end_on_a_person() -> None:
    """Control for the support helper the router and provider suites lean on."""
    for texts in (("a",), ("a", "b"), ("a", "b", "c")):
        last = prompt(*texts).messages[-1]
        assert isinstance(last, Message) and last.author == "person"


def test_the_null_object_refuses_every_kind() -> None:
    null = NullInference()
    for task in TASKS:
        with pytest.raises(InferenceUnavailable):
            settle(null.generate(task, prompt("hello"), Reply))


def test_the_locator_answers_the_null_object_when_nothing_is_registered() -> None:
    services.unregister(Inference)
    found = services.get(Inference)
    assert isinstance(found, NullInference)
    with pytest.raises(InferenceUnavailable):
        settle(found.generate("chat", prompt("hello"), Reply))


def test_a_registered_inference_is_what_the_locator_answers_until_it_is_removed() -> None:
    class Fixed(Inference):
        async def generate(self, task: Task, prompt: Prompt, output: type[T], *,
                           conversation_id: int | None = None) -> T:
            return output.model_validate({"spoken": "fixed", "text": "fixed"})

        async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                       conversation_id: int | None = None) -> T | ToolCalls:
            return output.model_validate({"spoken": "fixed", "text": "fixed"})

        async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
            return Transcript("fixed", "fixed", "fixed")

        async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
            raise AssertionError("not used")

    mine = Fixed()
    services.register(Inference, mine)
    try:
        assert services.get(Inference) is mine
    finally:
        services.unregister(Inference)
    assert isinstance(services.get(Inference), NullInference)
