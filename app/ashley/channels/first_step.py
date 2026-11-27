"""What the first step of a turn would send, built before there is a conversation: for an eval to measure, and for a
satellite's wake to have the model read into its prompt cache while the person is still talking (`warm`)."""

import logging
from dataclasses import dataclass

from .. import logs, services
from ..inference.inference import Inference
from ..inference.model import Message, Prompt, ToolSpec
from ..inference.reply import Reply
from . import aside, speaker, turn_prompt
from .landing import Landing
from .limits import load as load_limits
from .model import Inbound

log = logging.getLogger("ashley.channels")


@dataclass(frozen=True)
class FirstStep:
    """`prompted` as `turn_prompt.build` reads it for the turn, with no carried turns and no stored person turn, and
    `tools` as `tool_loop.answer` offers them in the first step (with `aside.FIELD` when the turn holds)."""

    prompted: turn_prompt.Prompted
    tools: tuple[ToolSpec, ...]


async def built(inbound: Inbound) -> FirstStep:
    """The first step's system prompt and tools for `inbound`. Reads what a turn reads before its first step (the
    speaker, tools, memory, phone reach) and writes nothing. Raises what `speaker.who` raises."""
    who = await speaker.who(inbound)
    prompted = await turn_prompt.build(inbound, who, Landing(inbound, (0, 0), load_limits()),
                                       turn_prompt.nothing_carried())
    specs = () if prompted.catalogue is None else prompted.catalogue.specs
    return FirstStep(prompted, aside.offered(specs) if inbound.holds and specs else specs)


async def warm(inbound: Inbound) -> bool:
    """Have the model `inbound`'s turn would ask first read the turn's tools, stable system prompt and reply schema into
    its prompt cache (`Inference.prime`), so the turn's first step reads them instead of writing them. True when that
    call was made and answered. Never raises: a failure building the prompt is logged `respond.warm_failed`."""
    try:
        step = await built(inbound)
    except Exception:
        logs.error(log, "respond.warm_failed", exc=True, household=inbound.household_id)
        return False
    prompt = Prompt(step.prompted.system, (Message("person", "."),), step.tools)
    return await services.get(Inference).prime(inbound.kind, prompt, Reply, household_id=inbound.household_id)
