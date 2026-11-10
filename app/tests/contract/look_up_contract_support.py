"""Helpers for the blind `look_up` tests: the shipped config values, a scripted `Inference` that records each step's task,
prompt and output type, and a `Tools` source that offers `search_web` and `find_places` and records what it was asked."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, TypeVar

from ashley import services
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.tools.look_up import LookedUp, LookUpTools
from ashley.tools.look_up_config import LookUpConfig
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from pydantic import BaseModel
from search_contract_support import run, spec

T = TypeVar("T", bound=BaseModel)
CONFIG = LookUpConfig(max_rounds=3, result_chars=4000, answer_chars=500, max_sources=3, page_timeout_s=6,
                      max_redirects=3, page_bytes=1000000, page_chars=6000)
WEB = spec("search_web")
PLACES = spec("find_places")
MARK = "zqLOOKUP5521"
"""A text that must reach the model or the result, and never a log line."""
RUNAWAY = 20
"""Steps after which the scripted model gives up, so a loop that never ends fails instead of hanging."""


def cfg(**changes: Any) -> LookUpConfig:
    return replace(CONFIG, **changes)


def answer(text: str = "Open until nine.", found: bool = True, sources: list[str] | None = None) -> LookedUp:
    return LookedUp(found=found, answer=text, sources=["example.org"] if sources is None else sources, references=[])


def ask(*names: str, first: str = "c") -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"{first}{i}", n, {"query": f"q{i}"}) for i, n in enumerate(names)))


def gave_up_answer() -> LookedUp:
    return answer("gave up", False, [])


@dataclass
class Seen:
    task: Task
    prompt: Prompt
    output: type[BaseModel]
    conversation_id: int | None


@dataclass
class Brain(Inference):
    """Answers each `step` with the next of `script`: a LookedUp or ToolCalls is returned, an exception is raised. Past
    the end of the script it asks again for `repeat` (fresh ids) while tools are allowed and answers `gave_up` under
    `none`. Every step is kept in `seen`."""

    script: list[LookedUp | ToolCalls | Exception] = field(default_factory=list[LookedUp | ToolCalls | Exception])
    repeat: tuple[str, ...] | None = None
    gave_up: LookedUp = field(default_factory=gave_up_answer)
    seen: list[Seen] = field(default_factory=list[Seen])

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.seen.append(Seen(task, prompt, output, conversation_id))
        if len(self.seen) > RUNAWAY:
            raise InferenceUnavailable("the scripted model was asked too often")
        n = len(self.seen) - 1
        item = self.script[n] if n < len(self.script) else self.past_the_script(prompt, n)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, ToolCalls):
            return item
        return output.model_validate(item.model_dump())

    def past_the_script(self, prompt: Prompt, n: int) -> LookedUp | ToolCalls:
        if prompt.tool_choice == "none" or self.repeat is None:
            return self.gave_up
        return ask(*self.repeat, first=f"r{n}_")

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("look_up steps; it never calls generate")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    @property
    def tool_choices(self) -> list[str]:
        return [s.prompt.tool_choice for s in self.seen]


@dataclass
class Sources(Tools):
    """The inner sources: offers `search_web` and `find_places` (or raises `down`), answers a call with
    `contents[name]` as `(text, is_error)`, else `result:<name>`; keeps the calls."""

    contents: Mapping[str, tuple[str, bool]] = field(default_factory=dict[str, tuple[str, bool]])
    down: bool = False
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        if self.down:
            raise ToolsUnavailable("sources are down")
        return Catalogue((WEB, PLACES), "inner instructions")

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        text, bad = self.contents.get(call.name, (f"result:{call.name}", False))
        return ToolResult(call.id, text, bad)


def look_up(brain: Brain, question: object = "does Target close early on Sundays?", sources: Sources | None = None,
            config: LookUpConfig = CONFIG, arguments: dict[str, object] | None = None,
            name: str = "look_up") -> ToolResult:
    """One `look_up` call with `brain` as the registered Inference; the locator is left as it was found."""
    given = sources or Sources()
    tools = LookUpTools(lambda: given, config)
    services.register(Inference, brain)
    try:
        return run(tools.call(ToolCall("k1", name, {"question": question} if arguments is None else arguments)))
    finally:
        services.unregister(Inference)


def reply(result: ToolResult) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(result.content)
    return out


def results_of(prompt: Prompt) -> ToolResults:
    last = prompt.messages[-1]
    assert isinstance(last, ToolResults)
    return last
