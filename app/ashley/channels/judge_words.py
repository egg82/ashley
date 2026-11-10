"""The words the action judge judges a call by (`ashley.tools.action_judge`): what the speaker themselves said in the
conversation, read from its stored turns, newest `turns` of them, each cut to `chars` characters. Her own replies are
never among them (they paraphrase what she read), nor a household turn, nor a block the person pasted with a message
(`Turn.attachment`; a paste typed into the message itself is not marked, so it counts).

A turn that started tainted from outside (`stranger`, `watch`), or that a wake started and whose maker was not kept, has
none, so the judge is not asked and the call waits for the person. A `pasted` turn is the person's own message, so it
reads the typed words like any other turn of theirs. A turn a tainted turn's reminder or watch woke (`inherited`) has the speaker's
person turns of the creating turn's conversation up to that turn (`Inbound.made_in`), never the brief: it counts only
once the person agreed to it, which nothing records yet."""

from collections.abc import Awaitable, Callable, Sequence

from .. import services
from ..conversations.conversations import Conversations
from .model import Inbound

Words = Callable[[], Awaitable[Sequence[str]]]


async def _none() -> Sequence[str]:
    return ()


def reader(inbound: Inbound, conversation_id: int, turns: int, chars: int) -> Words:
    """The turn's words, read when called. Raises ConversationsUnavailable when called and they cannot be read."""
    speaker = inbound.speaker_id
    if speaker is None:
        return _none
    if inbound.taint == "inherited":
        if inbound.made_in is None:
            return _none
        return _said(speaker, inbound.made_in[0], inbound.made_in[1], turns, chars)
    if inbound.author != "person" or inbound.unprompted or inbound.taint not in (None, "pasted"):
        return _none
    return _said(speaker, conversation_id, None, turns, chars)


def _said(speaker: int, conversation_id: int, through: int | None, turns: int, chars: int) -> Words:
    """The `speaker`'s person turns of the conversation, up to turn `through` when given."""

    async def read() -> Sequence[str]:
        found = await services.get(Conversations).get(conversation_id)
        said = [] if found is None else [t.text[:chars] for t in found.turns if t.author == "person"
                                         and t.speaker_id == speaker and (through is None or t.id <= through)]
        return tuple(said[-turns:])

    return read
