"""The ActionJudge service (`ashley.services`): in a turn that has read outside words, whether a `judged` change follows from
what the person asked (`decisions.md`, "A turn that has read outside words asks before it does anything consequential the
person did not ask for"). It is given the person's own `words` and a `View` of the call that code has reduced to what
cannot carry outside text, never the call's arguments, so there is nothing in its input for a stranger to write.

Code branches only on `Verdict.decision`; `reason` is for logs, and `explanation`, one sentence for the person, for
nothing else. The one implementation so far is the Null Object, which asks about everything."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence, Sized
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from ..inference.model import ToolCall
from ..services import Service

Decision = Literal["run", "ask"]
ModelReason = Literal["asked_directly", "follows_from_request", "follows_from_brief", "not_asked", "target_not_in_request",
                      "exceeds_request", "data_leaves_household", "undoes_safety", "unclear"]
"""The reasons the judge itself gives."""
Reason = Literal[ModelReason, "no_judge", "judge_unavailable", "recipient_unknown", "no_words", "not_junk"]
"""A `ModelReason`, or one code gives when no judge answered: none wired, none reachable, a recipient that is no one the
household knows, no words of the person's to judge by, or a move to spam or trash of a message the provider does not
mark as spam or promotions."""
UNJUDGED = "I couldn't check this one, so it waits for your OK"


class JudgeUnavailable(Exception):
    """The judge could not be reached, timed out, refused, or answered with something that is not a verdict. The caller
    asks."""


@dataclass(frozen=True)
class View:
    """The call as the judge sees it: its `tool`, and for each argument the tool declares its size, never its value (see
    `view_of`)."""

    tool: str
    fields: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: Reason
    explanation: str


@dataclass(frozen=True)
class Vetting:
    """What the source of a tool makes of a call before the judge hears of it (`Tools.vetted`): a `view` that names more
    than sizes, because the source resolved it from the household's own things, or `ask` with the reason code gives for
    holding it without a judge."""

    view: View | None = None
    ask: Reason | None = None


def view_of(call: ToolCall, parameters: Mapping[str, object]) -> View:
    """`call` reduced to what cannot carry outside text: each argument the tool's `parameters` schema declares is shown
    as its kind and size (`<text, 41 chars>`), a number or a flag as itself, and a string as itself only when the schema
    lists it among an `enum`. An argument it does not declare has a name the model chose, so only its size is shown,
    under `other`."""
    found = parameters.get("properties")
    loose: Any = found
    schemas: Mapping[str, object] = {str(k): v for k, v in dict[Any, Any](loose).items()} if isinstance(found, Mapping) else {}
    given = {k: v for k, v in call.arguments.items() if v is not None}
    named = {k for k in given if k in schemas}
    shown = {k: _shown(v, schemas[k]) for k, v in given.items() if k in named}
    undeclared = [_size(v) for k, v in given.items() if k not in named]
    return View(call.name, {**shown, **({"other": ", ".join(undeclared)} if undeclared else {})})


def checked(verdict: object) -> Verdict:
    """`verdict` when it is a well-formed answer; raises JudgeUnavailable otherwise, since a judge's output is data
    from outside this code and nothing but a clean `run` may run a change."""
    if isinstance(verdict, Verdict) and verdict.decision in get_args(Decision) and verdict.reason in get_args(Reason):
        return verdict
    raise JudgeUnavailable("the judge did not answer with a verdict")


def _shown(value: object, schema: object) -> str:
    loose: Any = schema
    choices: Any = loose.get("enum") if isinstance(schema, Mapping) else None
    if isinstance(value, str) and isinstance(choices, list) and value in choices:
        return value
    return _size(value)


def _size(value: object) -> str:
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, str):
        return f"<text, {len(value)} chars>"
    if isinstance(value, Mapping):
        return "<object>"
    if isinstance(value, Sized):
        return f"<list, {len(value)}>"
    return "<value>"


class ActionJudge(Service):
    @classmethod
    def null(cls) -> "ActionJudge":
        return NullJudge()

    @abstractmethod
    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        """Whether the call `view` shows follows from the person's own `words`. Raises JudgeUnavailable."""


class NullJudge(ActionJudge):
    """What an unwired process sees: every call is asked about, so missing wiring fails safe."""

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        return Verdict("ask", "no_judge", UNJUDGED)
