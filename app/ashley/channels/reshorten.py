"""A reply longer than `Limits.reply_chars` is asked for again, shorter (`ashley.channels.tool_loop`): up to
`RESHORTENED` times, and the next one goes out as it is. Logged `respond.reply_long` with the conversation, the length,
the limit and which ask it was."""

import logging
from collections.abc import Awaitable, Callable, Mapping

from .. import logs
from ..inference.model import Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice, ToolSpec
from ..inference.reply import Reply
from .limits import Limits

log = logging.getLogger("ashley.tools")

RESHORTENED = 2
"""How many times a reply longer than `Limits.reply_chars` is asked for again; the next one goes out as it is."""
_SHORTER = ("That is too long for this conversation: at most {limit} characters. Cut the working, not your voice: keep "
            "what changed, what it showed, anything only the person can decide, and the line that is you; the working "
            "belongs in a piece on the "
            "bench. Say it again.")


def too_long(reply: Reply, limits: Limits, shortened: int) -> bool:
    return bool(limits.reply_chars) and len(reply.text) > limits.reply_chars and shortened < RESHORTENED


def ask_shorter(entries: list[Entry], reply: Reply, limits: Limits, asked: int, conversation_id: int | None) -> None:
    """Her draft and the limit it broke, added to `entries` for the step that asks again."""
    logs.info(log, "respond.reply_long", conversation=conversation_id, chars=len(reply.text), limit=limits.reply_chars,
              asked=asked)
    entries += [Message("ashley", reply.text), Message("person", _SHORTER.format(limit=limits.reply_chars))]


async def shorter(step: Callable[[Task, Prompt, int | None], Awaitable[Reply | ToolCalls]], got: Reply | ToolCalls,
                  choice: ToolChoice, kind: Task, system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...],
                  entries: list[Entry], limits: Limits, shortened: int,
                  conversation_id: int | None) -> tuple[Reply | ToolCalls, bool, int]:
    """`got` as long as it may be: while it is a reply that is too long, her draft and the limit are added to `entries`
    and, under tool choice `none`, the step is asked again by `step`. Under `auto` the asking is left to the loop
    (`again` true, the second item). The third is the asks made so far, `shortened` included."""
    again = False
    while isinstance(got, Reply) and too_long(got, limits, shortened):
        shortened += 1
        ask_shorter(entries, got, limits, shortened, conversation_id)
        again = choice == "auto"
        if again:
            break
        got = await step(kind, Prompt(system, tuple(entries), tools, choice), conversation_id)
    return got, again, shortened
