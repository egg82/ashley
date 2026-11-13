"""What a conversation is, as values. Every id is a Postgres identity; every time is timezone-aware UTC."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ..receipts import AgreedCall, AgreedOutcome, Receipt, Receipts

__all__ = ["AgreedCall", "AgreedOutcome", "Receipt", "Receipts"]

Kind = Literal["command", "chat", "brainstorm"]
"""Set in code by whoever opens the conversation; it decides length, model and channels downstream."""

Channel = Literal["voice", "discord", "device", "web"]
"""Where a conversation started: a voice satellite, Discord, a device's message API, or the web app. Written once, when
the conversation is created."""

State = Literal["open", "idle", "closed"]
"""Derived, never stored: a function of the kind, the last turn's time and now (`policy.Policy.state_of`). Open takes
turns as one flowing exchange; idle still takes turns (a reply reopens it) and is when the memory write may run;
closed takes none, and the next message starts a new conversation."""

Author = Literal["person", "ashley", "household"]
"""Who a turn is by. `household` is the household speaking as itself (a wake: an event it reported): no speaker, shown by the
household's name, never a person's words wherever turns are carried and never learned from."""

Heard = Literal["shared", "private"]
"""Who could hear a turn where it was said: `shared`, the household (a shared room, a household channel); `private`,
only its owner (a DM, their web login, a reply sent to their phone). A reply carries a turn only where the same people
would hear it (`ashley.hearing.MAY_HEAR`)."""


@dataclass(frozen=True)
class Attachment:
    """A block a person pasted with a message, kept with its turn: `text` is non-blank, `title` names it or is None."""

    title: str | None
    text: str


@dataclass(frozen=True)
class NewTurn:
    """A turn to add. `speaker_id` is the person talking when `author` is `person` and the channel knows who that is,
    None when it does not (a shared device with no signal naming anyone); always None when `author` is `ashley` or
    `household`.
    `text` is what was said, in real spellings. `heard` is who could hear it and `owner_id` whose it is when `private`;
    the default, private to no one, is carried by no reply. `follows` is set on a turn of hers that went out while her
    answer was still to come (a held "let me check"); the answer is a later turn. `answers` is the id of the person turn a turn of hers answers, a held
    line included, None for one that answers none (her own initiative); a person turn with it set is refused. `source`
    is a person turn's id for the message on its channel (`discord:<message id>`), set only by a channel that may hand
    one message in twice, so it is stored once per household; one of hers with it set is refused. `carried_from` is the
    id of the chat turn a person turn carries onto a bench's talk, stored once per carried turn; `continued_on` is the
    bench a turn of hers hands the reader on to, its `text` the label of that link; each refused on the other author.
    `handed` is set on her final answer in a thread whose messages steer the running turn: the ids of the person turns
    it was handed. The turn is stored only while every person turn after the one it answers is among them
    (`unhanded`), else refused with `Unhanded`, the check made under the conversation's lock that a person turn's
    store takes too, so a message is either handed or stored after her answer. A turn of the household (`author`
    `household`) takes `source` as a person's does (`wake:<id>`) and refuses `follows`, `answers`, `carried_from`
    and `continued_on`. `attachment` is a block the person pasted with the message, only on a person's turn (the
    turn's `text` is what they typed, never the paste). `spoken` is what she chose to say aloud with her turn, in real
    spellings (`Reply.aloud`), only on a turn of hers and never empty; the page that spoke to her plays it
    (`Conversations.spoken`). `receipts` is what code shows beside her answer (`Receipts`), only on a turn of hers;
    refused on another author."""

    author: Author
    text: str
    speaker_id: int | None = None
    heard: Heard = "private"
    owner_id: int | None = None
    follows: bool = False
    answers: int | None = None
    source: str | None = None
    carried_from: int | None = None
    continued_on: int | None = None
    handed: tuple[int, ...] | None = None
    attachment: Attachment | None = None
    spoken: str | None = None
    receipts: Receipts | None = None


@dataclass(frozen=True)
class Turn:
    """A stored turn. `at` is when the database recorded it. `follows`, `answers`, `carried_from`, `continued_on`, `attachment`, `spoken` and `receipts` as on `NewTurn`. `conversation_id`
    is the conversation it was said in, None on a turn built by hand; it is not part of a turn's equality. `agreed` is
    what became of the held calls a person's agreeing turn carried out (`InFlight.agreed`), set once they are done; None
    on every other turn. `heard` and `owner_id` as on `NewTurn`; a hand-built turn is `shared`."""

    id: int
    author: Author
    speaker_id: int | None
    text: str
    at: datetime
    follows: bool = False
    conversation_id: int | None = field(default=None, compare=False)
    answers: int | None = None
    carried_from: int | None = None
    continued_on: int | None = None
    attachment: Attachment | None = None
    spoken: str | None = None
    receipts: Receipts | None = None
    agreed: AgreedOutcome | None = None
    heard: Heard = "shared"
    owner_id: int | None = None


@dataclass(frozen=True)
class Conversation:
    """One conversation as read at one moment. `channel` and `place` are where it started, None when not recorded. `participants` are the people in it: those it was started with, plus
    every known speaker of a turn since. `turns` are oldest first. `last_activity_at` is the newest turn's `at`, or
    `started_at` before the first turn. `state` is as of the read, by the database's clock."""

    id: int
    household_id: int
    kind: Kind
    participants: frozenset[int]
    started_at: datetime
    last_activity_at: datetime
    state: State
    turns: tuple[Turn, ...]
    channel: Channel | None = None
    place: str | None = None


@dataclass(frozen=True)
class Summary:
    """A conversation in a list, without its turns. `turns` is how many it has. `channel` and `place` are where it
    started, None when not recorded."""

    id: int
    kind: Kind
    state: State
    started_at: datetime
    last_activity_at: datetime
    channel: Channel | None
    place: str | None
    turns: int


@dataclass(frozen=True)
class Cursor:
    """A place in the newest-first order of `Conversations.of_person`: the last activity and id of the last summary of
    a page."""

    last_activity_at: datetime
    id: int


@dataclass(frozen=True)
class Page:
    """Up to the asked number of summaries, newest activity first. `next` is the cursor of the following page, None
    on the last."""

    items: tuple[Summary, ...]
    next: Cursor | None


@dataclass(frozen=True)
class Hearer:
    """Who will hear a reply: the household, the speaker (None when unknown) and whether only the speaker will hear or
    read it (`owner_only`: a DM, their web login)."""

    household_id: int
    speaker_id: int | None
    owner_only: bool


@dataclass(frozen=True)
class Place:
    """Where a turn was said: its conversation's `thread` (`bench:4`, `person:1:web`), and the title of the bench when
    that thread is a bench's."""

    thread: str
    bench_title: str | None


@dataclass(frozen=True)
class Carried:
    """The earlier turns one reply carries, each one the hearer may hear. `recent` oldest first; `relevant` best match
    first, from outside the recent window. `filtered` is how many turns in the recent window and among the relevant
    matches the hearer may not hear (`Conversations.carried`). `places` is where each recent turn was said, by turn id,
    for those said on a thread other than the replying conversation's; a turn whose conversation has no recorded
    thread is not in it."""

    recent: tuple[Turn, ...]
    relevant: tuple[Turn, ...]
    filtered: int
    places: Mapping[int, Place] = field(default_factory=dict[int, Place])


def unhanded(turns: Iterable[Turn], after: int, handed: Collection[int]) -> list[Turn]:
    """The person turns among `turns`, in their order, said after the turn `after` and not among `handed`, leaving out
    an ask carried from another thread (`carried_from`), which is that turn's own: what a turn steered from `after`
    has yet to be handed (`channels.steering`)."""
    return [t for t in turns if t.author == "person" and t.id > after and t.id not in handed and t.carried_from is None]
