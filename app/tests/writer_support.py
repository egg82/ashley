"""Fakes for the memory writer's tests: an `Inference` that answers every `generate` with one scripted output, and a
`Provider` that answers each write case's prompt with the ops the case expects and each judge prompt by comparing
the two statements exactly (a judge control as the control says), so the real router, ledger, writer, judge and
harness run end to end with no network."""

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any, TypeVar

from ashley.inference.inference import Inference
from ashley.inference.model import Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice, ToolSpec, Usage
from ashley.inference.provider import Completion, Provider, ToolUse
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.memory.eval import write
from ashley.memory.eval.judge import Verdict
from ashley.memory.writer_output import Written, WrittenOp
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

CONTROL_VERDICTS: dict[tuple[str, str], bool] = {
    (c["expected"], c["written"]): c["same"]
    for c in json.loads(resources.files("ashley.memory.eval").joinpath("judge_controls.json").read_text("utf-8"))["controls"]
}


def op(name: str, target: int | None = None, about: int | None = 1, owner: int | None = 1, text: str = "A fact",
       **fields: Any) -> WrittenOp:
    """A written op with plausible defaults for every field the test does not name."""
    base: dict[str, Any] = {"op": name, "target": target, "about": about, "owner": owner, "visibility": "shared",
                            "visibility_stated": False, "kind": "other", "standing": False, "text": text,
                            "source_turn": None}
    return WrittenOp.model_validate({**base, **fields})


class ScriptedInference(Inference):
    """Answers every `generate` with `answer`, recording each (task, prompt) asked."""

    def __init__(self, answer: BaseModel) -> None:
        self.answer = answer
        self.asked: list[tuple[Task, Prompt]] = []

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        self.asked.append((task, prompt))
        return output.model_validate(self.answer.model_dump())

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        raise AssertionError("the writer never steps")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("the writer never transcribes")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("the writer never speaks")


def _expected_op(expected: dict[str, Any], people: dict[str, int], ids: dict[str, int]) -> WrittenOp:
    def person(key: str) -> int | None:
        name = expected.get(key)
        return None if name is None else people[name]

    target = ids[expected["target"]] if "target" in expected else None
    if expected["op"] in ("invalidate", "forget"):
        return op(expected["op"], target, None, None, "")
    return op(expected["op"], target, person("about"), person("owner"), expected["states"],
              visibility=expected.get("visibility", "shared"),
              visibility_stated=expected.get("visibility_stated", False), kind=expected.get("kind", "other"),
              standing=expected.get("standing", False))


def expected_answers() -> dict[tuple[str, ...], Written]:
    """Each case's expected ops as the model would write them, keyed by the case's turn texts."""
    data = write.load()
    out: dict[tuple[str, ...], Written] = {}
    for case in data["cases"]:
        conversation, _, ids = write.build(data, case)
        ops = tuple(_expected_op(e, data["people"], ids) for e in case["expect"]) or (op("noop", None),)
        out[tuple(t.text for t in conversation.turns)] = Written(ops=ops)
    return out


class ExpectedProvider(Provider):
    """Named `anthropic`, so the shipped routes reach it first. Every call is billed `USAGE`."""

    USAGE = Usage(input_tokens=400, output_tokens=60)

    def __init__(self) -> None:
        self.answers = expected_answers()
        self.calls: list[type[BaseModel]] = []

    @property
    def name(self) -> str:
        return "anthropic"

    def check_params(self, params: Mapping[str, object]) -> None:
        pass

    async def complete[O: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...],
                                      tool_choice: ToolChoice, output: type[O],
                                      timeout_s: float) -> Completion[O] | ToolUse:
        self.calls.append(output)
        text = messages[-1].text if isinstance(messages[-1], Message) else ""
        if output is Verdict:
            expected, written = (line.split(": ", 1)[1] for line in text.splitlines())
            same = CONTROL_VERDICTS.get((expected, written), expected == written)
            return Completion(output.model_validate({"missing_or_changed": "", "same_fact": same}), self.USAGE)
        found = [w for turns, w in self.answers.items() if all(t in text for t in turns)]
        assert len(found) == 1, f"the prompt matches {len(found)} cases"
        return Completion(output.model_validate(found[0].model_dump()), self.USAGE)
