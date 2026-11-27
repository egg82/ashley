"""What the first step of a turn would send, built before there is a conversation, for an eval to measure."""

from dataclasses import dataclass

from ..inference.model import ToolSpec
from . import aside, speaker, turn_prompt
from .landing import Landing
from .limits import load as load_limits
from .model import Inbound


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
