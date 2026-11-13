"""Support for the household-routes suite: a deployment's routes data of known shape, scripted stand-ins for the stored
choices and the providers, and the log reader. Everything here is written from the contract, not an implementation."""

import asyncio
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, get_args

from ashley.inference import routes
from ashley.inference.household_routes import HouseholdRoutes, TaskChoices
from ashley.inference.layered_routes import LayeredRoutes
from ashley.inference.model import Entry, Route, SystemPrompt, Task, TaskName, ToolChoice, ToolSpec, Usage
from ashley.inference.provider import Completion, Failure, Provider, ProviderFailed, ProviderRefused, ToolUse, Wired
from ashley.inference.route_choices import Choice, RouteChoiceReads, RoutesUnavailable
from ashley.inference.routes import Routes
from pydantic import BaseModel

SECRET = "sk-SECRET-route-param-0xBEEF"
TASK_ORDER: tuple[Task, ...] = get_args(Task)
PROVIDERS = ("a", "b", "c", "d")


def route(provider: str, model: str, timeout_s: float = 10, **params: object) -> dict[str, object]:
    out: dict[str, object] = {"provider": provider, "model": model, "timeout_s": timeout_s}
    if params:
        out["params"] = params
    return out


def deployment_data(**tasks: object) -> dict[str, Any]:
    """Routes data with every text task given two plain routes, and `tasks` replacing entries by name. By default
    `chat`, `brainstorm` and `wrap_up` are household tasks, each listing one model the others do not, `escalated` is
    `like` brainstorm, and the rest are plain."""
    plain = [route("a", "m1"), route("b", "m2")]
    entries: dict[str, object] = {t: plain for t in routes.TASKS}
    entries.update({
        "chat": {"household": True, "routes": [route("a", "m1", 30, k=SECRET), route("b", "m2", 30)]},
        "brainstorm": {"household": True, "routes": [route("c", "m3", 120), route("a", "m1", 120)]},
        "wrap_up": {"household": True, "routes": [route("d", "m4", 20), route("b", "m2", 20)]},
        "escalated": {"like": "brainstorm"},
        **tasks})
    return {"cooldown_s": 60, "tasks": entries}


class Stub(Provider):
    """A provider of one name, accepting any params, answering `Answer(text=<model>)` and noting each call."""

    def __init__(self, name: str, fails: Failure | None = None, refuses: bool = False) -> None:
        self._name = name
        self.fails: Failure | None = fails
        self.refuses = refuses
        self.calls = list[str]()

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[T: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                     messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...], tool_choice: ToolChoice,
                                     output: type[T], timeout_s: float) -> Completion[T] | ToolUse:
        self.calls.append(model)
        if self.refuses:
            raise ProviderRefused("scripted")
        if self.fails is not None:
            raise ProviderFailed(self.fails, "scripted")
        return Completion(output.model_validate({"text": f"{self._name}/{model}"}), Usage(1, 1))


def stubs(names: Collection[str] = PROVIDERS) -> dict[str, Stub]:
    return {n: Stub(n) for n in names}


@dataclass
class Store(RouteChoiceReads):
    """The stored choices and the conversations' households, as a test sets them; `down` makes every read raise."""

    choices: dict[int, dict[Task, Choice]] = field(default_factory=dict[int, dict[Task, Choice]])
    households: dict[int, int] = field(default_factory=dict[int, int])
    down: bool = False
    all_reads: int = 0

    def _check(self) -> None:
        if self.down:
            raise RoutesUnavailable("scripted")

    async def all(self) -> Mapping[int, Mapping[Task, Choice]]:
        self.all_reads += 1
        self._check()
        return {h: dict(c) for h, c in self.choices.items() if c}

    async def of_household(self, household_id: int) -> Mapping[Task, Choice]:
        self._check()
        return dict(self.choices.get(household_id, {}))

    async def household_of(self, conversation_id: int) -> int | None:
        self._check()
        return self.households.get(conversation_id)


@dataclass
class World:
    """A `LayeredRoutes` over a `Store`, with the wired names and the clock a test moves."""

    layered: LayeredRoutes
    store: Store
    wired: set[str]
    clock: list[float]

    def at(self, seconds: float) -> None:
        self.clock[0] = seconds

    def for_call(self, conversation_id: int | None) -> Routes:
        return asyncio.run(self.layered.for_call(conversation_id))


def world(data: dict[str, object] | None = None, wired: Collection[str] = PROVIDERS, store: Store | None = None,
          narrow: Any = None) -> World:
    store = store if store is not None else Store()
    names, clock = set(wired), [0.0]
    extra: dict[str, Any] = {} if narrow is None else {"narrow": narrow}
    layered = LayeredRoutes(data if data is not None else deployment_data(), dict[str, Wired](stubs()),
                            lambda: frozenset(names), store, clock=lambda: clock[0], **extra)
    return World(layered, store, names, clock)


def keys(r: Route) -> tuple[str, str]:
    return (r.provider, r.model)


def first(rs: Routes, task: TaskName) -> tuple[str, str]:
    return keys(rs.for_task(task)[0])


def own_choices(service: HouseholdRoutes, household: int) -> dict[str, TaskChoices]:
    return {c.task: c for c in asyncio.run(service.choices(household))}


def logged(caplog: Any) -> list[tuple[str, dict[str, Any]]]:
    """Each structured line captured, as its event and fields."""
    return [(r.getMessage(), dict[str, Any](getattr(r, "fields", {}))) for r in caplog.records
            if isinstance(r, logging.LogRecord)]


def events(caplog: Any, event: str) -> list[dict[str, Any]]:
    return [f for e, f in logged(caplog) if e == event]
