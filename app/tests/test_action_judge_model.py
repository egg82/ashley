"""`ModelActionJudge` through the real `Inference` and the shipped `action_judge` route: what the model is sent (the
person's words and the call's view, and nothing else), what comes back as a verdict, and every way of not answering."""

import asyncio
from collections.abc import Generator

import pytest
from action_judge_support import Capturing, failed, refused, unwire, wire
from ashley.inference import routes
from ashley.tools.action_judge import JudgeUnavailable, Verdict, View
from ashley.inference.model import Message
from ashley.tools.action_judge_model import EXPLANATION_CHARS, INSTRUCTIONS, Answer
from ashley import services
from ashley.tools.action_judge import ActionJudge

WORDS = ("turn the porch light on", "and lock the back door")
VIEW = View("house_do", {"action": "light.turn_on", "things": "Porch light", "data": "<text, 18 chars>"})


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    yield
    unwire()


def decide(provider: Capturing) -> Verdict:
    wire(provider)
    return asyncio.run(services.get(ActionJudge).decide(WORDS, VIEW))


def test_the_task_has_a_sonnet_route_first() -> None:
    first = routes.load({}).for_task("action_judge")[0]
    assert (first.provider, first.model) == ("anthropic", "claude-sonnet-5-5")


def test_the_request_is_the_instructions_the_words_and_the_view_alone() -> None:
    provider = Capturing()
    decide(provider)
    [sent] = provider.sent
    assert sent.system.stable == INSTRUCTIONS and sent.system.moment == ""
    [message] = sent.messages
    assert isinstance(message, Message)
    text = message.text
    assert "turn the porch light on" in text and "lock the back door" in text
    assert "tool: house_do" in text and "things: Porch light" in text and "data: <text, 18 chars>" in text


def test_a_run_and_an_ask_come_back_with_their_reason_and_explanation() -> None:
    got = decide(Capturing(Answer(decision="run", reason="follows_from_request", explanation="  You asked for the light. ")))
    assert (got.decision, got.reason, got.explanation) == ("run", "follows_from_request", "You asked for the light.")
    got = decide(Capturing(Answer(decision="ask", reason="not_asked", explanation="You did not ask for that.")))
    assert (got.decision, got.reason) == ("ask", "not_asked")


@pytest.mark.parametrize("error", [failed(), refused()])
def test_a_provider_that_is_down_or_declines_is_a_judge_unavailable(error: Exception) -> None:
    with pytest.raises(JudgeUnavailable):
        decide(Capturing(error=error))


def test_an_answer_with_a_blank_explanation_keeps_its_decision() -> None:
    got = decide(Capturing(Answer(decision="run", reason="asked_directly", explanation="  ")))
    assert (got.decision, got.explanation) == ("run", "")


def test_a_reason_only_code_gives_is_not_one_the_model_may_answer() -> None:
    with pytest.raises(ValueError):
        Answer.model_validate({"decision": "run", "reason": "no_judge", "explanation": "x"})


def test_the_call_is_billed_to_the_action_judge_task() -> None:
    provider = Capturing()
    ledger = wire(provider)
    asyncio.run(services.get(ActionJudge).decide(WORDS, VIEW))
    assert [c.task for c in ledger.calls] == ["action_judge"]


def test_an_explanation_is_cut_to_a_sentence_s_length() -> None:
    got = decide(Capturing(Answer(decision="ask", reason="unclear", explanation="x" * 1000)))
    assert len(got.explanation) == EXPLANATION_CHARS
