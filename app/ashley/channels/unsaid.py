"""A reply with nothing to deliver. Every closing step after a lookup, and the one retry of an empty reply, carries a
wrap-up note (no more lookups; say what was found and what is missing). If the retry is empty too, the turn answers
with the fixed line in `unsaid.json`, so no stored turn is empty and a person after a held line is never left with
nothing (`ashley.channels.tool_loop`, logged `respond.reply_empty`)."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from importlib import resources
from typing import ClassVar

from .. import logs
from ..inference.model import Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice, ToolSpec
from ..inference.reply import Reply
from ..live.events import FailedWhy
from .model import Medium
from .render import delivered

log = logging.getLogger("ashley.tools")
_DATA = json.loads(resources.files("ashley.channels").joinpath("unsaid.json").read_text())
LINE: str = _DATA["line"]
UNREACHABLE: str = _DATA["unreachable"]
REJECTED: str = _DATA["rejected"]
TOO_BIG_LINE: str = _DATA["too_big_line"]
ASK = Message("person", _DATA["wrap_up"])
ACT = Message("person", _DATA["act"])
STAND = Message("person", _DATA["stand"])
TOO_BIG = Message("person", _DATA["too_big"])
TOO_BIG_HAND_OFF = Message("person", _DATA["too_big_hand_off"])
HAND_OFF = Message("person", _DATA["hand_off"])


def empty(reply: Reply, medium: Medium) -> bool:
    """Whether `reply` has nothing for `medium` to deliver, though it was meant to be said (`Reply.worth_saying`)."""
    return reply.worth_saying and not delivered(reply, medium).strip()


class Said(Reply):
    """Words code wrote, not she: a fixed line of `unsaid.json`. On a channel the person reads on a page
    (`Inbound.paged`) it is never stored as her turn (`Unworded`); the page shows the turn's state itself, as `why`."""

    why: ClassVar[FailedWhy] = "unfinished"


class TooBig(Said):
    """The close of a turn whose step was cut off at the token limit and not asked again (`channels.cutoff`)."""

    why: ClassVar[FailedWhy] = "too_big"


class Unworded(Exception):
    """A turn ended with only `Said` words to give on a paged channel: nothing is stored as her turn, and the turn
    fails as any whose work is gone, the page shown `why` (the words' `Said.why`)."""

    def __init__(self, why: FailedWhy) -> None:
        super().__init__(why)
        self.why: FailedWhy = why


def fixed() -> Reply:
    """The answer that stands in for one the model would not give."""
    return Said(spoken=LINE, text=LINE)


def unreachable() -> Reply:
    """The line for a turn whose model could not be reached, said while it is kept to finish later."""
    return Said(spoken=UNREACHABLE, text=UNREACHABLE)


def too_big() -> Reply:
    """The answer of a turn whose work was too big for one reply: said plainly, and not retried."""
    return TooBig(spoken=TOO_BIG_LINE, text=TOO_BIG_LINE)


def rejected() -> Reply:
    """The answer of a turn whose every route rejected the request: something went wrong on her side and the work may
    not be done. Said once and not retried."""
    return Said(spoken=REJECTED, text=REJECTED)


def closing(entries: Sequence[Entry], choice: ToolChoice, calls: int) -> tuple[Entry, ...]:
    """`entries` as a step is asked them: under tool choice `none` after lookups were made (`calls`), ending with
    `ASK`, the wrap-up note every such closing step carries."""
    return (*entries, ASK) if choice == "none" and calls else tuple(entries)


def acting(entries: Sequence[Entry]) -> tuple[Entry, ...]:
    """`entries` with `ACT` added: the note that follows a reply which only said she was about to act, asked under tool
    choice `auto` because neither brainstorm provider accepts a forced call."""
    return (*entries, ACT)


async def asked_again(step: Callable[[Task, Prompt, int | None], Awaitable[Reply | ToolCalls]], kind: Task,
                      system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...], entries: list[Entry],
                      asked: int, medium: Medium, conversation_id: int | None) -> Reply:
    """What follows an empty reply, the `asked`th of the turn: logged `respond.reply_empty`. The first is a wrap-up,
    `entries` with `ASK` added, stepped by `step` under tool choice `none` (the tools stay listed, since the entries
    hold tool calls); an empty or tool-calling answer to it, and every later one, is `fixed()`."""
    logs.info(log, "respond.reply_empty", conversation=conversation_id, asked=asked)
    if asked > 1:
        return fixed()
    entries.append(ASK)
    got = await step(kind, Prompt(system, tuple(entries), tools, "none"), conversation_id)
    return got if isinstance(got, Reply) and not empty(got, medium) else fixed()


async def stood(step: Callable[[Task, Prompt, int | None], Awaitable[Reply | ToolCalls]], promise: Reply, kind: Task,
                system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...], entries: Sequence[Entry], calls: int,
                rounds: int, conversation_id: int | None) -> Reply:
    """What replaces a closing `promise`, a reply whose `answers` is false: logged `respond.stood`. The closing step
    asked once more under tool choice `none` with `STAND` after the promise, so she says where the work stands and
    promises nothing. That reply is the answer whatever its fields say, the loop having to end; `fixed()` when the
    model asks for tools instead."""
    logs.info(log, "respond.stood", conversation=conversation_id, rounds=rounds)
    asked = (*closing(entries, "none", calls), Message("ashley", promise.text), STAND)
    got = await step(kind, Prompt(system, asked, tools, "none"), conversation_id)
    return got if isinstance(got, Reply) else fixed()


def step_prompt(system: Mapping[str, SystemPrompt], entries: list[Entry], tools: tuple[ToolSpec, ...], choice: ToolChoice,
                calls: int, act: bool) -> Prompt:
    """The step's prompt: with the act note (`unsaid.acting`) when `act`, else as `unsaid.closing` shapes it."""
    if act:
        return Prompt(system, acting(entries), tools, "auto")
    return Prompt(system, closing(entries, choice, calls), tools, choice)
