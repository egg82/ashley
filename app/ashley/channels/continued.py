"""Her reply said where the person's page now is (`docs/decisions.md`, "Her reply follows the page"). A turn that took
the page to a bench (`Inbound.lands_on`) ends with the bench's talk holding the person's ask, carried from the chat turn
(`NewTurn.carried_from`), and her reply to it; the thread the turn began on keeps the ask and gets, in place of her
reply, a turn that continues on the bench (`NewTurn.continued_on`), whose text is the bench's title and nothing else: the
page words the link itself and shows it as a quiet line, not as something she said. Stored once however
often the turn is finished.

The ask is carried the moment the page lands (`carried`), so the bench shows it while she works, and a held line she
says after that is said there too (`held_on_bench`); one said before stays in the thread.

Logs `respond.continued` with the chat conversation, the bench and the bench's conversation, and
`respond.continue_failed` with the bench and the reason when the bench could not take the reply and it stays in chat."""

import logging
from collections.abc import Mapping
from dataclasses import replace

from .. import logs, services
from ..conversations.conversations import ConversationError, Conversations
from ..conversations.model import NewTurn
from ..inference.model import SystemPrompt
from ..people.model import Person
from ..workshop.model import Owner, thread_of
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import history
from .landing import Landing
from .live_turn import Showing
from .model import Inbound
from .tool_loop import Arrived, Steps

log = logging.getLogger("ashley.channels")


async def carried(inbound: Inbound, speaker: Person | None, chat_said: int, showing: Showing) -> tuple[int, int] | None:
    """The ask of the person turn `chat_said` carried into the bench's talk once the turn's page is on a bench
    (`Inbound.lands_on`): the talk's id and the carried turn's. None while the page has not landed or the bench could
    not take it (logged `respond.continue_failed`; the reply then stays where the turn began). Stored once however
    often called; the open screens are told the talk has a turn."""
    bench = inbound.lands_on
    if bench is None or speaker is None:
        return None
    try:
        _, home, ask = await _asked(inbound, speaker, chat_said, bench)
    except (BenchNotFound, WorkshopUnavailable, ConversationError, ValueError) as e:
        logs.warning(log, "respond.continue_failed", bench=bench, reason=type(e).__name__)
        return None
    showing.stored(thread_of(bench))
    return home, ask


async def arrived(landing: Landing, speaker: Person | None, chat_said: int, showing: Showing, steps: Steps,
                  system: Mapping[str, SystemPrompt]) -> Arrived | None:
    """Before each step of the turn answering `chat_said`, whichever runner has it: the screens told she is still
    working if it has been a while, and once the page has landed on a bench the ask carried there and recorded with
    the turn (`Steps.carried`), so the bench shows it and her work from then on. What `landing.arrived` gives."""
    showing.still_working()
    moved = await landing.arrived(system)
    if moved is not None:
        got = await carried(landing.inbound, speaker, chat_said, showing)
        if got is not None:
            await steps.carried(*got)
    return moved


async def held_on_bench(inbound: Inbound, speaker: Person | None, chat_said: int, held: NewTurn,
                        showing: Showing) -> tuple[int, NewTurn] | None:
    """Where her held line `held` (a line before the answer to the person turn `chat_said`) is said: the bench's
    conversation and the line answering the carried ask, once the turn's page is on a bench; None before, when it is
    said in the thread the turn began on."""
    got = await carried(inbound, speaker, chat_said, showing)
    return None if got is None else (got[0], replace(held, answers=got[1]))


async def said_on_bench(inbound: Inbound, speaker: Person | None, chat_said: int, hers: NewTurn,
                        chat_conversation: int, showing: Showing) -> NewTurn:
    """The turn to store in the thread's conversation for her turn `hers` (an answer to the person turn `chat_said`):
    `hers` itself when the turn did not land on a bench or the bench could not take it, else the turn continuing on
    the bench, after the bench's talk holds the ask and `hers`."""
    bench = inbound.lands_on
    if bench is None or speaker is None:
        return hers
    try:
        title, talk, ask = await _asked(inbound, speaker, chat_said, bench)
        await _answered(talk, ask, hers)
    except (BenchNotFound, WorkshopUnavailable, ConversationError, ValueError) as e:
        logs.warning(log, "respond.continue_failed", bench=bench, reason=type(e).__name__)
        return hers
    showing.stored(thread_of(bench))
    logs.info(log, "respond.continued", conversation=chat_conversation, bench=bench, talk=talk)
    return NewTurn("ashley", title, None, hers.heard, hers.owner_id, answers=chat_said, continued_on=bench)


async def _asked(inbound: Inbound, speaker: Person, chat_said: int, bench: int) -> tuple[str, int, int]:
    """The bench's title, its conversation and the turn in it that carries the ask of `chat_said`. Raises what the
    workshop and `Conversations` raise."""
    title = (await services.get(Workshop).read(Owner(inbound.household_id, speaker.id), bench)).bench.title
    conversations = services.get(Conversations)
    talk = await conversations.for_thread(inbound.household_id, thread_of(bench), "brainstorm", [speaker.id],
                                          remembered=True, channel="web")
    ask = await conversations.add_turn(talk.id, NewTurn("person", inbound.text, speaker.id,
                                                        *history.heard(inbound, speaker), carried_from=chat_said))
    return title, ask.conversation_id if ask.conversation_id is not None else talk.id, ask.id


async def _answered(talk: int, ask: int, hers: NewTurn) -> None:
    """`hers` stored in the talk unless a final answer to the ask is already there."""
    conversations = services.get(Conversations)
    held = await conversations.get(talk)
    if held is None or not any(t.answers == ask and not t.follows for t in held.turns):
        await conversations.add_turn(talk, replace(hers, answers=ask))
