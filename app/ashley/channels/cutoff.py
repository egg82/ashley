"""A step cut off at the token limit, asked again to act small (`docs/decisions.md`, "Tool use is a step"):
`unsaid.TOO_BIG`, or `unsaid.TOO_BIG_HAND_OFF` where `bench_hand_off` is offered; logged `respond.cutoff` with the
conversation, the round and whether it was asked again (`reask`). A cut-off not asked again closes the turn as too big."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace

from .. import logs
from ..inference.inference import InferenceCutOff
from ..inference.model import Prompt, Task, ToolCalls
from ..inference.reply import Reply
from . import hand_off, unsaid
from .steps import Steps

log = logging.getLogger("ashley.channels")


async def asked(step: Callable[[Task, Prompt, int | None], Awaitable[Reply | ToolCalls]], steps: Steps, rounds: int,
                kind: Task, prompt: Prompt, conversation_id: int | None) -> Reply | ToolCalls:
    """`step` of `prompt`; when every route's reply was cut off at the token limit (`InferenceCutOff`) under tool choice
    `auto`, it is asked once more on the same route with the too-big note after the entries (`unsaid.TOO_BIG_HAND_OFF`
    when `bench_hand_off` is among the tools, else `unsaid.TOO_BIG`), once per turn (`Steps.cut_off`); the tool choice
    stays `auto`. A second cut-off, or one under any other choice, is the turn's answer: `unsaid.too_big()`."""
    try:
        return await step(kind, prompt, conversation_id)
    except InferenceCutOff:
        again = steps.cut_off == 0 and prompt.tool_choice == "auto" and bool(prompt.tools)
        logs.info(log, "respond.cutoff", conversation=conversation_id, round=rounds, reask=int(again))
        if not again:
            return unsaid.too_big()
    await steps.cut()
    note = unsaid.TOO_BIG_HAND_OFF if hand_off.offered(prompt.tools) else unsaid.TOO_BIG
    try:
        return await step(kind, replace(prompt, messages=(*prompt.messages, note)), conversation_id)
    except InferenceCutOff:
        logs.info(log, "respond.cutoff", conversation=conversation_id, round=rounds, reask=0)
        return unsaid.too_big()
