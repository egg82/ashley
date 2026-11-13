"""What goes into a model call and what one costs, as values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from .embedding import EmbedTask
from .image import ImageTask
from .speech import SpeechTask
from .voiceprint import VoiceprintTask

DEFAULT_VARIANT = "default"

Role = Literal["person", "ashley"]
"""Who a message is from: `person` for anyone or anything that is not her (an event from the house too), `ashley`."""

Task = Literal["command", "chat", "brainstorm", "escalated", "wrap_up", "memory_write", "memory_judge", "look_up", "bench_tidy", "errand",
        "action_judge", "bench_job", "eval_judge"]
"""What a call is for, which picks its routes: the conversation kinds a reply is for, a turn that escalated from its
fast route to the stronger one (`ashley.channels.escalation`; its own task so the ledger tells its calls apart, its
routes those of `brainstorm`), the one step that wraps up a turn whose route refused it (`ashley.channels.unsaid`; routes
of other providers than chat's), the memory write job's decision, the memory eval's judge, and the look-up sub-agent's
steps and a reader's (`ashley.tools.look_up`, `ashley.tools.readers`), and the tidy pass that points at stale text on a bench (`ashley.tidy.run`), an errand run (`ashley.channels.errand.job`), a step of a bench job's agent (`ashley.tools.bench_agent`), and an eval's grader of her words into
structured fields (`ashley.evals.bench_replay_grader`). A new kind of work (an orchestrator's step) is a new task here, a new entry in
`routes.json`, and a migration widening the spend ledger's check."""


TOOLLESS: frozenset[Task] = frozenset({"memory_write", "memory_judge", "bench_tidy", "action_judge", "eval_judge"})
"""The tasks whose calls never offer tools, which `RoutedInference.step` enforces; only these may be routed to a
provider that takes none (`provider.Provider.takes_tools`)."""


TaskName = Task | SpeechTask | EmbedTask | VoiceprintTask | ImageTask
"""Any task a call can be for: the key of a route list and of a spend row."""


MOMENT_LABEL = "[The facts of this moment, not words anyone said]"
"""Opens the `moment` where a provider sends it after the history, among the turns."""


@dataclass(frozen=True)
class SystemPrompt:
    """A system prompt in two layers: `stable` (the same from one message to the next) and `moment` (what changes per
    message: the clock, who is speaking, what she recalls). Providers send `stable` as the system prompt and `moment`
    after the history (`MOMENT_LABEL`, then the text), so the history stays a cached prefix from one message to the
    next. `text` is the two joined. An empty `moment` makes the prompt just `stable`. Raises ValueError when `stable` is empty or only whitespace."""

    stable: str
    moment: str = ""

    def __post_init__(self) -> None:
        if not self.stable.strip():
            raise ValueError("a system prompt needs a stable part")

    @property
    def text(self) -> str:
        """The whole prompt as one string."""
        return f"{self.stable}\n\n{self.moment}" if self.moment else self.stable


@dataclass(frozen=True)
class Message:
    """One message of the exchange so far. `author` is `person` for anyone talking to her (the caller writes who into
    `text` when it matters), `ashley` for her own replies."""

    author: Role
    text: str


Tier = Literal["runs", "judged"]
"""What a tainted turn does with a change: it runs, or the action judge decides (`ashley.tools.outside`)."""


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may ask for. `name` matches `^[A-Za-z0-9_-]{1,64}$`, the rule every provider shares;
    `parameters` is a JSON Schema object (`{"type": "object", ...}`) for its arguments. `reads` is true only for a tool
    known to change nothing; any other is a change, after which the tool loop (`ashley.channels.tool_loop`) runs a
    read again that it had made. `outside` says whether a result can carry text written outside the household (a web
    page, a payload, a repository), and is true unless the spec says false, so a tool nobody classified taints the turn
    that reads it (`ashley.channels.taint`). `agrees` marks a tool that takes a person's agreement to something held
    (`house_confirm`, `arm_reminder`, `carry_out`): a tainted turn is refused it (`ashley.tools.outside`). Providers are
    not sent any of the three. `tier` says what a tainted turn does with a call to a change: `runs` runs it, `judged`
    asks the action judge, and a name nobody classified is judged. `Tools.tier` refines it per call. `label` is a short
    plain past-tense phrase for a change the tool makes ("Moved an email to a folder"), shown to the person beside her
    reply (`conversations.model.Receipt`); None for a tool with none. Not sent to providers."""

    name: str
    description: str
    parameters: Mapping[str, object]
    reads: bool = False
    outside: bool = True
    agrees: bool = False
    tier: Tier = "judged"
    label: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """One call the model asked for. `id` is the provider's own id for it, unique within its `ToolCalls`; `arguments`
    are as the model sent them, not checked against the tool's schema (the tool's owner does that). `provider_data` is
    what the provider that asked for this call needs back to continue (Gemini's thought signature); other providers
    ignore it, and a loop that moves to another provider may lose it."""

    id: str
    name: str
    arguments: Mapping[str, object]
    provider_data: Mapping[str, object] = field(default_factory=dict[str, object])


@dataclass(frozen=True)
class ToolCalls:
    """Her side of the exchange when the model asked for tools instead of answering: the calls, in the order asked."""

    calls: tuple[ToolCall, ...]


ImageType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
"""The picture types every provider takes."""


@dataclass(frozen=True)
class Image:
    """A picture a tool gives the model to see, as its bytes and type."""

    media_type: ImageType
    data: bytes


@dataclass(frozen=True)
class ToolResult:
    """What one call returned, as text the model reads (usually JSON). `is_error` marks a call that failed, so the
    model can say so rather than read the error as data. `images` are pictures the model sees with the text, in order;
    a provider whose tool results are text alone sends them in a user message right after the results. `outside`
    narrows the tool's `ToolSpec.outside` for this result: None leaves the spec's say, a boolean replaces it."""

    call_id: str
    content: str
    is_error: bool = False
    images: tuple[Image, ...] = ()
    outside: bool | None = None

    def taints(self, spec_outside: bool) -> bool:
        """Whether this result can carry text written outside the household: `outside` when set, else `spec_outside`."""
        return spec_outside if self.outside is None else self.outside


@dataclass(frozen=True)
class ToolResults:
    """The results of the `ToolCalls` just before it, one per call, in the same order."""

    results: tuple[ToolResult, ...]


Entry = Message | ToolCalls | ToolResults
"""One entry of the exchange a prompt carries."""

ToolChoice = Literal["auto", "none"]
"""`auto`: the model may ask for tools or answer. `none`: it must answer now, whatever tools the exchange used. A call
forced to ask for a tool is not offered: the brainstorm models refuse it."""


@dataclass(frozen=True)
class Prompt:
    """What a call sends. `system` holds one system prompt per variant: a route names the variant tuned for its
    provider (`Route.variant`) and gets `system["default"]` when that variant is absent. `messages` are oldest first.
    `tools` are what the model may ask for, under `tool_choice`.

    Raises ValueError on construction when `system` has no `default`; any message text is empty or
    only whitespace; `messages` is empty; the last entry is neither a `person` message nor `ToolResults`; a
    `ToolCalls` is empty, repeats an id, or is not followed directly by `ToolResults` answering exactly its ids in its
    order; a `ToolResults` follows anything else; any `ToolCalls` appear while `tools` is empty; or two tools share a
    name."""

    system: Mapping[str, SystemPrompt]
    messages: tuple[Entry, ...]
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"

    def __post_init__(self) -> None:
        if DEFAULT_VARIANT not in self.system:
            raise ValueError("a prompt needs a default system prompt")
        if not self.messages:
            raise ValueError("a prompt needs at least one message")
        if any(isinstance(m, Message) and not m.text.strip() for m in self.messages):
            raise ValueError("a message is empty")
        last = self.messages[-1]
        if not (isinstance(last, ToolResults) or (isinstance(last, Message) and last.author == "person")):
            raise ValueError("the last message must be from a person or be tool results")
        if len({t.name for t in self.tools}) != len(self.tools):
            raise ValueError("two tools share a name")
        for i, entry in enumerate(self.messages):
            before = self.messages[i - 1] if i else None
            if isinstance(entry, ToolCalls):
                _check_calls(entry, bool(self.tools))
            elif isinstance(entry, ToolResults) and not _answers(entry, before):
                raise ValueError("tool results must answer the tool calls just before them, in order")
            if isinstance(before, ToolCalls) and not isinstance(entry, ToolResults):
                raise ValueError("tool calls must be followed by their results")

    def system_for(self, variant: str) -> SystemPrompt:
        """The system prompt tuned for `variant`, else the default."""
        return self.system.get(variant, self.system[DEFAULT_VARIANT])


def _check_calls(entry: ToolCalls, tools_offered: bool) -> None:
    if not tools_offered:
        raise ValueError("tool calls in a prompt that offers no tools")
    ids = [c.id for c in entry.calls]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("tool calls must be non-empty with unique ids")


def _answers(results: ToolResults, before: Entry | None) -> bool:
    return isinstance(before, ToolCalls) and [r.call_id for r in results.results] == [c.id for c in before.calls]



@dataclass(frozen=True)
class Usage:
    """What one call was billed by, as the provider reported it. `input_tokens` excludes cache reads and writes.
    Speech calls are billed by audio and text instead: `audio_ms`, the duration of the audio transcribed, and
    `characters`, the length of the text spoken (or embedded); their tokens are 0."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    audio_ms: int = 0
    characters: int = 0


@dataclass(frozen=True)
class Route:
    """One way to carry out a task: the named provider (`Provider.name`), its model id, the system
    prompt variant tuned for it, how long to wait, and parameters only that provider understands (checked at load by
    `Provider.check_params`)."""

    provider: str
    model: str
    timeout_s: float
    variant: str = DEFAULT_VARIANT
    params: Mapping[str, object] = field(default_factory=dict[str, object])
