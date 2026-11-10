"""The URLs the people of a conversation have written in it, for her bench tools to check a site or video URL she gives
against (`tools.bench_reference`), and the ids of their turns, for a choice row she cites one in
(`tools.bench_citations`): read when asked, from the conversation's person turns, so a turn of hers or the household's
never vouches for a link or a choice."""

from collections.abc import Awaitable, Callable

from .. import services
from ..conversations.conversations import Conversations, ConversationsUnavailable
from ..tools.bench_reference import SaidUnavailable, links_in


def by_people(conversation_id: int) -> Callable[[], Awaitable[frozenset[str]]]:
    """A reader of the URLs in conversation `conversation_id`'s person turns. Raises SaidUnavailable when called while
    the conversation cannot be read."""
    async def read() -> frozenset[str]:
        try:
            conversation = await services.get(Conversations).get(conversation_id)
        except ConversationsUnavailable as e:
            raise SaidUnavailable() from e
        found: set[str] = set()
        for turn in () if conversation is None else conversation.turns:
            if turn.author == "person":
                found |= links_in(turn.text)
        return frozenset(found)
    return read


def turns_by_people(conversation_id: int) -> Callable[[], Awaitable[frozenset[int]]]:
    """A reader of the ids of conversation `conversation_id`'s person turns, which a choice row of hers may cite
    (`tools.bench_citations`). Raises SaidUnavailable when called while the conversation cannot be read."""
    async def read() -> frozenset[int]:
        try:
            conversation = await services.get(Conversations).get(conversation_id)
        except ConversationsUnavailable as e:
            raise SaidUnavailable() from e
        turns = () if conversation is None else conversation.turns
        return frozenset(t.id for t in turns if t.author == "person")
    return read
