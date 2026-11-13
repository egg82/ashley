"""A provider is one way to reach a model (Strategy): the Anthropic API, an OpenAI-compatible API (ChatGPT, Gemini,
a local server), the Claude CLI. Each wired instance has its own name, so two OpenAI-compatible endpoints are two
providers. Only `RoutedInference` calls them; everyone else asks `Inference`."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from .model import Entry, SystemPrompt, ToolCalls, ToolChoice, ToolSpec, Usage

T = TypeVar("T", bound=BaseModel)

Failure = Literal["unavailable", "invalid_output", "error"]
"""Why a call produced nothing usable. `unavailable`: the provider could not be reached, timed out, was overloaded
or rate-limited, or refused the account (no credit, bad key); the router stops trying it for a while. `invalid_output`:
it answered, but not with the schema (including a reply cut off at the token limit). `error`: anything else, such as a
request it rejected as malformed."""


@dataclass(frozen=True)
class Completion(Generic[T]):
    """A call that produced `output`, already validated against the schema it was asked for."""

    output: T
    usage: Usage


@dataclass(frozen=True)
class ToolUse:
    """A call that asked for tools instead of replying: `calls` non-empty, ids unique."""

    calls: ToolCalls
    usage: Usage


UNAVAILABLE_STATUS = frozenset({401, 402, 403, 408, 409, 429})


def status_failure(status: int) -> Failure:
    """How an HTTP error status fails a call: `unavailable` for the ones that say the provider or the account cannot
    serve it now (no credit, bad key, rate limit, timeout, overload), else `error`."""
    return "unavailable" if status in UNAVAILABLE_STATUS or status >= 500 else "error"


class ProviderFailed(Exception):
    """The call produced nothing usable. `usage` is what was billed anyway, None when nothing was or it is unknown.
    The message names the exception type and status code and, for a 4xx that is not about the account, the provider's
    cut-down message (`providers._status_reason`); never the request. `cut_off`: the reply stopped at the token limit
    (an `invalid_output`)."""

    def __init__(self, failure: Failure, message: str, usage: Usage | None = None, cut_off: bool = False) -> None:
        super().__init__(message)
        self.failure: Failure = failure
        self.usage = usage
        self.cut_off = cut_off


class ProviderRefused(Exception):
    """The model declined to answer (its own safety stop). Not something another route should be asked to get around."""

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class Wired(ABC):
    """Anything a route can name: a text `Provider`, or a speech `Transcriber` or `Speaker`. One object may be
    several."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The name routes use for this instance (`anthropic`, `openai`, `gemini`, `local`, `wyoming`)."""


class Provider(Wired):
    """One reachable model API."""

    @property
    def takes_tools(self) -> bool:
        """Whether it can be offered tools. One that cannot may be routed only for a task in `model.TOOLLESS`, which
        the routes check when they load."""
        return True

    @abstractmethod
    def check_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take or a value it would reject.
        Called once per route when the routes load, so a typo fails at start-up rather than on a call."""

    @abstractmethod
    async def complete(self, model: str, params: Mapping[str, object], system: SystemPrompt, messages: tuple[Entry, ...],
                       tools: tuple[ToolSpec, ...], tool_choice: ToolChoice, output: type[T],
                       timeout_s: float) -> Completion[T] | ToolUse:
        """Ask `model` for one reply shaped as `output`, or, when `tools` is non-empty and `tool_choice` is `auto`, for
        the tool calls it wants instead; giving up after `timeout_s` with no retry of its own. `messages` arrive valid
        (`Prompt`'s rules). Tool calls sent with no tools offered, or under `none`, fail `invalid_output`.
        Raises ProviderRefused when the model declines, ProviderFailed for every other way it produces nothing usable;
        never anything else."""
