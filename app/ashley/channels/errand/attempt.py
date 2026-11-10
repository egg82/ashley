"""One run of one errand: her conversation up to the ask, the errand's system prompt, and the tool loop under the
`errand` task. Its tools are behind `tools.outside.Outside` with no speaker, so once a read carries outside words a
change is refused, never held."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ... import services
from .. import prompt, tool_loop
from ..limits import Limits
from ...conversations.conversations import Conversations
from ...inference.model import Message, SystemPrompt
from ...people.people import People
from ...persona import errand as persona
from ...tools.outside import Outside
from ...tools.tools import Catalogue, Tools
from ...errands.config import ErrandsConfig
from ...errands.model import Errand


class Unrunnable(Exception):
    """The errand's conversation, ask, household or asker could not be read, so it cannot run now."""


@dataclass(frozen=True)
class Ran:
    """A finished run: `text` is what she says she did, `calls` how many tool calls it took, `owed` the source key
    she set when it went out of reach again, else None."""

    text: str
    calls: int
    owed: str | None


async def attempt(errand: Errand, catalogue: Catalogue, config: ErrandsConfig, now: datetime) -> Ran:
    """Run `errand` against `catalogue`. Raises Unrunnable, ConversationsUnavailable, PeopleUnavailable,
    InferenceUnavailable, InferenceRefused."""
    household = await services.get(People).household(errand.household_id)
    conversation = await services.get(Conversations).get(errand.conversation_id)
    asker = None if household is None else next((p for p in household.people if p.id == errand.asker_id), None)
    if household is None or asker is None or conversation is None:
        raise Unrunnable("household, asker or conversation missing")
    through = [t for t in conversation.turns if t.id <= errand.turn_id][-config.context_turns:]
    if not through or through[-1].id != errand.turn_id:
        raise Unrunnable("the ask is not in the conversation")
    messages = prompt.messages(through[:-1], through[-1], household)
    system = persona.system(household, asker, errand.source, catalogue.instructions, catalogue.unreachable,
                            now.astimezone(ZoneInfo(household.timezone)))
    limits = Limits(config.max_tool_rounds, config.max_tool_result_chars, config.context_turns, 0)
    got = await _answer(system, messages, catalogue, limits, errand.conversation_id)
    return Ran(got.reply.text, got.calls, got.reply.owed)


async def _answer(system: Mapping[str, SystemPrompt], messages: tuple[Message, ...],
                  catalogue: Catalogue, limits: Limits, conversation_id: int) -> tool_loop.Answer:
    source = Outside(services.get(Tools), None, None)
    got = await tool_loop.answer("errand", system, messages, catalogue.specs, limits, conversation_id, source=source)
    if not isinstance(got, tool_loop.Answer):
        raise Unrunnable("the run held without a hold asked")
    return got
