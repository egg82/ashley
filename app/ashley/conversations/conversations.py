"""The Conversations service (`ashley.services`): start a conversation, add a turn to it, read it back. Callers
import only this module and `model`; the Postgres implementation lives beside it.

Every conversation and every person in it belong to one household, enforced by the schema: a person from another
household can neither take part nor speak. Conversation content (turn text) is stored, and is never logged."""

from abc import abstractmethod
from collections.abc import Iterable

from ..services import Service
from .model import Carried, Channel, Conversation, Cursor, Hearer, Kind, NewTurn, Page, Turn


class ConversationError(Exception):
    """Base of what the service raises on purpose."""


class ConversationsUnavailable(ConversationError):
    """No writable primary could be reached, or it stopped being one mid-call (a failover). Nothing was written.
    Transient: the caller may retry."""


class ConversationNotFound(ConversationError):
    """No conversation has that id."""


class ConversationClosed(ConversationError):
    """The conversation was closed when the turn arrived, by the database's clock; start a new one."""


class RefusedTurn(ConversationError, ValueError):
    """A turn that carries `spoken` and is not hers, or whose `spoken` is blank. Nothing was written. A ValueError too,
    as `add_turn` refuses every other turn no conversation stores."""


class UnknownHousehold(ConversationError):
    """No household has that id."""


class Unhanded(Exception):
    """Her answer was not stored: a person turn after the one it answers was not handed to it (`NewTurn.handed`), so
    the turn goes on with it. Nothing was written. Not a ConversationError, which callers take as the turn refused."""


class UnknownPerson(ConversationError):
    """A participant or speaker is not a person in the conversation's household."""


class Conversations(Service):
    @classmethod
    def null(cls) -> "Conversations":
        return NullConversations()

    @abstractmethod
    async def start(self, household_id: int, kind: Kind, participants: Iterable[int],
                    remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        """Start a conversation with no turns, now. `participants` may be empty (a shared device with no speaker
        known yet) and may repeat an id. `remembered` is whether the memory write job may write it, fixed for the
        conversation's life; the caller takes it from the device that opens it. `channel` and `place` are where it started
        (None when unknown, as for rows from before they were recorded), written now and never changed. Returns it as stored: state `open`,
        `last_activity_at == started_at`. Raises ValueError (before touching the database) for a kind outside `Kind`; UnknownHousehold; UnknownPerson
        when any participant is not in that household. Nothing is written when it raises. Logs
        `conversation.started` with its id, kind and participant count."""

    @abstractmethod
    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        """Append `turn`, now. A turn added to an idle conversation reopens it; one arriving when it is closed is
        refused with ConversationClosed. The check and the write are one transaction, so two turns racing the
        closing moment cannot both see it open after it closed, and concurrent turns to one conversation are all
        stored, each with its own id, in the order the database committed them. A known speaker not yet a
        participant becomes one. A person or house turn whose `source` the household already stored is not added again: that
        turn is returned, whichever conversation holds it and whatever state it is in.
        Raises ValueError (before touching the database) when `author` is `ashley` with a `speaker_id` or a
        `source`, `household` with a `speaker_id`, `follows` or `answers`, or `text` is empty or only whitespace; RefusedTurn when
        `spoken` is set on a turn not hers or is blank; ConversationNotFound; UnknownPerson when the speaker is not in the
        conversation's household. Nothing is written when it raises. Logs `conversation.turn` with the
        conversation id, turn id and author, or `conversation.turn_refused` with the id and the reason."""

    @abstractmethod
    async def for_thread(self, household_id: int, thread: str, kind: Kind, participants: Iterable[int],
                         remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        """The conversation `thread` is carrying, for the next turn on it. `thread` is a channel's own key for where a
        message came from (`device:7`, a Discord channel id), namespaced by the channel; several threads may carry one
        conversation. Returns the conversation the thread last carried when it is not closed by the database's clock,
        as `get` would read it (`participants`, `kind`, `remembered`, `channel` and `place` ignored: it keeps the value it started with); otherwise starts one as
        `start` does, points the thread at it, and returns it with no turns. A thread last carrying another household's conversation is treated
        as carrying none. Two calls racing on one thread return the same conversation: the check and the write are one
        transaction. Raises what `start` raises, ValueError for an empty `thread`, and nothing is written when it
        raises. Logs `conversation.thread` with the conversation id and whether it was `continued` or `started` (and
        `conversation.started` when it was)."""

    @abstractmethod
    async def get(self, conversation_id: int) -> Conversation | None:
        """The conversation with all its turns, its state as of now; None when no conversation has that id. Whoever
        asks decides whether they may read it: its `participants` and `household_id` say who and where."""

    @abstractmethod
    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        """The conversation `thread` last carried, as `get` reads it, whatever its state; None when the thread has
        carried none, or last carried another household's. Reads only: no thread is pointed and nothing is started."""

    @abstractmethod
    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        """The conversations `person_id` took part in (a participant now, whatever their channel), in `household_id`,
        newest activity first, whatever their state; those with no turn are left out. At most `limit` come back; `next`
        is set when more follow, and passing it as `after` reads them. With `thread`, only the conversations that
        started on that thread (`for_thread` records it), so a thread's closed predecessors are listed with its
        current one. A person of another household, or none, has an empty page. Raises ValueError (before touching the
        database) for a `limit` below 1. Reads only; logs
        `conversation.listed` with the person, the count and whether more follow."""

    @abstractmethod
    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        """Her answer to the person turn `household_id` stored with `source` (`NewTurn.source`): her latest turn
        answering it that is not a held line (`follows`); None when there is no such turn or no answer yet. Reads
        only."""

    @abstractmethod
    async def carried(self, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                      relevant: int) -> Carried:
        """The turns of `hearer.household_id` before turn `before` that a reply to it may carry, whatever conversation
        they were said in, each one passing `ashley.hearing.MAY_HEAR` for the hearer by the turn's `heard` and
        `owner_id`, in SQL, so a turn the hearer may not hear is never read out of the database.
        Turns of another conversation are carried only when it is remembered (`start`'s `remembered`).
        `recent`: the latest `recent` such turns of conversation `conversation_id` and of every conversation the
        speaker took part in (only the former for an unknown speaker), oldest first.
        The recent window is the candidates from the oldest carried on, or all of them when fewer than `recent` were
        carried, or none when `recent` is 0.
        `relevant`: up to `relevant` more that match any word of `query`, best match first, from any of the
        household's conversations, outside the recent window.
        `filtered`: how many turns in the recent window and among those matches the hearer may not hear.
        Raises ValueError (before touching the database) for a negative `recent` or `relevant`. Reads only."""

    @abstractmethod
    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        """What she said aloud with turn `turn_id` (`Turn.spoken`), in real spellings, when that turn is in a
        conversation of `household_id` that `thread` last carried, has `spoken`, and was stored at most `within_s`
        seconds ago by the database's clock; None otherwise, whichever condition failed. Ownership and age are one
        query, so no caller can check one and forget the other. Reads only."""


class NullConversations(Conversations):
    """Stores nothing: what an unwired process sees. Every call raises ConversationsUnavailable, so a missing
    registration fails loudly instead of answering "no such conversation"."""

    async def start(self, household_id: int, kind: Kind, participants: Iterable[int],
                    remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        raise ConversationsUnavailable("Conversations is not wired")

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        raise ConversationsUnavailable("Conversations is not wired")

    async def for_thread(self, household_id: int, thread: str, kind: Kind, participants: Iterable[int],
                         remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        raise ConversationsUnavailable("Conversations is not wired")

    async def get(self, conversation_id: int) -> Conversation | None:
        raise ConversationsUnavailable("Conversations is not wired")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        raise ConversationsUnavailable("Conversations is not wired")

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise ConversationsUnavailable("Conversations is not wired")

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise ConversationsUnavailable("Conversations is not wired")

    async def carried(self, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                      relevant: int) -> Carried:
        raise ConversationsUnavailable("Conversations is not wired")

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        raise ConversationsUnavailable("Conversations is not wired")
