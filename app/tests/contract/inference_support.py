"""Helpers for the blind Inference contract tests: scripted fake `Provider`s over a fake clock, an in-memory
`SpendLedger`, prices and routes built from values, and a router assembled through its public constructor."""

import asyncio
from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ashley.inference.model import Entry, Message, Prompt, Route, SystemPrompt, Task, ToolChoice, ToolSpec, Usage
from ashley.inference.catalogue import ModelCatalogue
from ashley.inference.provider import Completion, Failure, Provider, ProviderFailed, ProviderRefused, ToolUse
from ashley.inference.router import RoutedInference
from ashley.inference.routes import TASKS, Routes
from ashley.inference.spend import Call, SpendLedger
from catalogue_support import flat, of
from pydantic import BaseModel

FAILURES: tuple[Failure, ...] = ("unavailable", "invalid_output", "error")
USAGE = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=200, cache_write_tokens=100)
PRICES = of({"alpha": {"m1": flat(), "m2": flat()}, "beta": {"m1": flat()}})
USAGE_COST = Decimal("0.010935")
"""`USAGE` at `flat()`'s prices: (1000 * 3 + 100 * 3.75 + 200 * 0.3 + 500 * 15) / 1,000,000."""
COOLDOWN_S = 300.0


def settle[R](scenario: Coroutine[Any, Any, R], limit: float = 25.0) -> R:
    """Run `scenario` to its result, failing rather than hanging."""
    async def bounded() -> R:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


class Clock:
    """Monotonic seconds a test moves by hand."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass(frozen=True)
class Step:
    """What one scripted call does: after `seconds` on the clock, return `data` validated as the asked-for output, or
    raise `error`."""

    data: Mapping[str, object] = field(default_factory=dict[str, object])
    error: ProviderFailed | ProviderRefused | None = None
    usage: Usage | None = USAGE
    seconds: float = 0.0


def ok(text: str = "answer", usage: Usage | None = USAGE, seconds: float = 0.0) -> Step:
    return Step({"spoken": text, "text": text}, None, usage, seconds)


def fail(failure: Failure, usage: Usage | None = None, seconds: float = 0.0) -> Step:
    return Step(error=ProviderFailed(failure, f"{failure} (status 000)", usage), seconds=seconds)


def refuse(usage: Usage | None = None, seconds: float = 0.0) -> Step:
    return Step(error=ProviderRefused("declined", usage), seconds=seconds)


@dataclass(frozen=True)
class Asked:
    """One `Provider.complete` call as received."""

    model: str
    params: Mapping[str, object]
    system: SystemPrompt
    messages: tuple[Entry, ...]
    output: type[BaseModel]
    timeout_s: float
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"


class FakeProvider(Provider):
    """Plays its script one step per call (the last step repeats once it runs out), moving the clock as the step says."""

    def __init__(self, name: str, script: Iterable[Step] = (), clock: Clock | None = None) -> None:
        self._name = name
        self._script = list(script) or [ok()]
        self._clock = clock
        self.asked: list[Asked] = []
        self.checked: list[Mapping[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        self.checked.append(params)
        for key in params:
            if key.startswith("bad"):
                raise ValueError(f"{self._name} does not take {key}")

    async def complete[T: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...],
                                      tool_choice: ToolChoice, output: type[T],
                                      timeout_s: float) -> Completion[T] | ToolUse:
        self.asked.append(Asked(model, params, system, messages, output, timeout_s, tools, tool_choice))
        step = self._script[min(len(self.asked), len(self._script)) - 1]
        if self._clock is not None:
            self._clock.advance(step.seconds)
        if step.error is not None:
            raise step.error
        assert step.usage is not None, "a returned reply carries the usage the provider reported"
        return Completion(output.model_validate(step.data), step.usage)


class FakeLedger(SpendLedger):
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.rows: list[Call] = []
        self.attempts = 0
        self.fail_with = fail_with

    async def record(self, call: Call) -> None:
        self.attempts += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.rows.append(call)


def answered[T: BaseModel](result: Completion[T] | ToolUse) -> Completion[T]:
    """`Provider.complete`'s result when it must be a reply."""
    assert isinstance(result, Completion), f"expected a reply, got {type(result).__name__}"
    return result


def route(provider: str, model: str = "m1", timeout_s: float = 10.0, variant: str = "default",
          params: Mapping[str, object] | None = None) -> Route:
    return Route(provider, model, timeout_s, variant, dict(params or {}))


def table(routes: Iterable[Route], cooldown_s: float = COOLDOWN_S,
          overrides: Mapping[Task, Iterable[Route]] | None = None) -> Routes:
    """Every task gets `routes`, except those in `overrides`."""
    given = tuple(routes)
    by_task: dict[Task, tuple[Route, ...]] = {k: given for k in TASKS}
    for task, routes_of in (overrides or {}).items():
        by_task[task] = tuple(routes_of)
    return Routes(by_task, cooldown_s)


def prompt(*texts: str, system: Mapping[str, str] | None = None) -> Prompt:
    """A valid prompt: persons and ashley alternating, ending on a person."""
    spoken = texts or ("hello",)
    messages = tuple(Message("person" if (len(spoken) - 1 - i) % 2 == 0 else "ashley", t) for i, t in enumerate(spoken))
    return Prompt({k: SystemPrompt(v) for k, v in (system or {"default": "be Ashley"}).items()}, messages)


def router(routes: Routes, providers: Iterable[Provider], ledger: SpendLedger | None = None,
           clock: Clock | None = None, prices: ModelCatalogue = PRICES) -> RoutedInference:
    return RoutedInference(routes, providers, ledger if ledger is not None else FakeLedger(), prices,
                           clock if clock is not None else Clock())


def outcomes(ledger: FakeLedger) -> list[tuple[str, str, str]]:
    """(provider, model, outcome) of each recorded call, in order."""
    return [(r.provider, r.model, r.outcome) for r in ledger.rows]


ANY_TASK: Any = "not-a-task"
