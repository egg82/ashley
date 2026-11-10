"""A turn refused by its model after its first line went out is wrapped up on a route of another provider (the task
`wrap_up`, `routes.json`), under tool choice `none` with the wrap-up note `unsaid.ASK`; when that fails too, or says
nothing, the fixed line of `unsaid.json` stands in. Logged `respond.ended` (`ending.record`)."""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from ..inference.inference import InferenceError
from ..inference.model import Entry, Prompt, SystemPrompt, Task, ToolCalls, ToolSpec
from ..inference.reply import Reply
from . import ending, unsaid
from .model import Medium

TASK: Task = "wrap_up"


async def wrapped(step: Callable[[Task, Prompt, int | None], Awaitable[Reply | ToolCalls]],
                  system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...], entries: Sequence[Entry],
                  medium: Medium, conversation_id: int | None) -> Reply:
    """The reply that ends a turn whose route refused it: one wrap-up step over `entries` by `step`, else the fixed
    line."""
    try:
        got = await step(TASK, Prompt(system, (*entries, unsaid.ASK), tools, "none"), conversation_id)
    except InferenceError:
        got = None
    if isinstance(got, Reply) and not unsaid.empty(got, medium):
        ending.record("refused", conversation_id, "wrap_up")
        return got
    ending.record("refused", conversation_id, "fixed_line")
    return unsaid.fixed()
