"""The action judge over the real `Inference` and the shipped routes, with a provider that keeps every request it is sent:
the instrument the leak tests read, and a scripted model for the verdicts."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ashley import services
from ashley.inference import prices, routes
from ashley.inference.inference import Inference
from ashley.inference.model import Entry, Message, SystemPrompt, ToolChoice, ToolSpec, Usage
from ashley.inference.provider import Completion, Provider, ProviderFailed, ProviderRefused, ToolUse
from ashley.inference.router import RoutedInference
from ashley.tools.action_judge import ActionJudge
from ashley.tools.action_judge_model import Answer, ModelActionJudge
from pydantic import BaseModel
from speech_support import MemoryLedger

USAGE = Usage(input_tokens=300, output_tokens=40)
RUN = Answer(decision="run", reason="asked_directly", explanation="You asked for it.")


@dataclass
class Sent:
    """One request as the provider was handed it: the model, the system prompt and the messages."""

    model: str
    system: SystemPrompt
    messages: tuple[Entry, ...]

    def text(self) -> str:
        said = " ".join(m.text for m in self.messages if isinstance(m, Message))
        return f"{self.model}\n{self.system.stable}\n{self.system.moment}\n{said}"


@dataclass
class Capturing(Provider):
    """Named `anthropic`, so the shipped `action_judge` route reaches it first. Answers `answer`, or raises `error` (a
    ProviderFailed or ProviderRefused), and keeps what it was sent."""

    answer: BaseModel = RUN
    error: Exception | None = None
    sent: list[Sent] = field(default_factory=list[Sent])

    @property
    def name(self) -> str:
        return "anthropic"

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[O: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...], tool_choice: ToolChoice,
                                      output: type[O], timeout_s: float) -> Completion[O] | ToolUse:
        self.sent.append(Sent(model, system, messages))
        if self.error is not None:
            raise self.error
        return Completion(output.model_validate(self.answer.model_dump()), USAGE)


def wire(provider: Provider) -> MemoryLedger:
    """The real `ModelActionJudge` over the shipped routes and `provider`, registered in place of the Null Object."""
    ledger = MemoryLedger()
    services.register(Inference, RoutedInference(routes.load({"anthropic": provider}), [provider], ledger, prices.load()))
    services.register(ActionJudge, ModelActionJudge())
    return ledger


def unwire() -> None:
    services.unregister(Inference)
    services.unregister(ActionJudge)


def failed() -> ProviderFailed:
    return ProviderFailed("unavailable", "down")


def refused() -> ProviderRefused:
    return ProviderRefused("declined")
