"""What she knows, as values. Every id is a Postgres identity; every time is timezone-aware UTC."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..conversations.model import Channel
from ..conversations.model import Kind as ConversationKind
from ..hearing import Visibility as Visibility


Kind = Literal["preference", "routine", "plan", "person", "health", "finance", "diet", "home", "other"]
"""What a fact is about. `person` is who someone is and who they know; `home` is the house, its things and its pets.
`diet` is what someone can't, won't or shouldn't eat or drink (allergies, intolerances, diets), not `health`.
`finance` is money: balances, accounts, income, debts, what someone spends or saves.
Code pins `health` and `finance` to private, whatever the model set, and `diet` to standing."""


@dataclass(frozen=True)
class NewFact:
    """A fact as the write job states it. `about_id` is the person it is about, None when it is about the household
    (Mochi the cat); `owner_id` is whose it is to share or forget, None for a household fact, which is always shared.
    `visibility_stated` is True when the owner said who may know ("keep that between us", "you can tell Elodie"); code
    pins `health` and `finance` to private only when it is False. `standing` is True when the fact holds of someone for good and
    changes what a good reply looks like without being mentioned; code pins `diet` to standing. `text` is one
    self-contained statement in real spellings, true on its own without the conversation. `source_turn_id` is the
    turn of the conversation it was learned from, None when no turn is named."""

    about_id: int | None
    owner_id: int | None
    visibility: Visibility
    visibility_stated: bool
    kind: Kind
    standing: bool
    text: str
    source_turn_id: int | None = None


@dataclass(frozen=True)
class Fact:
    """A stored fact. Current while `valid_to` is None; a correction closes it and sets `superseded_by` to the fact
    that replaced it. `standing` facts reach every reply through `Memory.profile`, not `recall`.
    `source_conversation_id` is the conversation it was learned in."""

    id: int
    household_id: int
    about_id: int | None
    owner_id: int | None
    visibility: Visibility
    kind: Kind
    standing: bool
    text: str
    source_conversation_id: int
    valid_from: datetime
    valid_to: datetime | None
    superseded_by: int | None


@dataclass(frozen=True)
class Replaced:
    """The fact a current one superseded: what it said, and when it stopped being true."""

    text: str
    valid_to: datetime


@dataclass(frozen=True)
class Source:
    """Where a fact was learned: its conversation's kind and start, the channel and place it started on (None for
    a conversation from before they were recorded, and `place` for a channel with none), and whether the person
    reading took part in it."""

    conversation_id: int
    conversation_kind: ConversationKind
    started_at: datetime
    took_part: bool
    channel: Channel | None = None
    place: str | None = None


@dataclass(frozen=True)
class Held:
    """A current fact as the person it concerns sees it: `replaced` is the fact it superseded, when there was one and
    they may see it."""

    fact: Fact
    replaced: Replaced | None
    source: Source


@dataclass(frozen=True)
class Add:
    """Something new she did not know."""

    fact: NewFact


@dataclass(frozen=True)
class Update:
    """`target` is still about the same thing but has changed: it closes, and `fact` replaces it."""

    target: int
    fact: NewFact


@dataclass(frozen=True)
class Invalidate:
    """`target` stopped being true and nothing replaces it. She can still answer "what did I say before?"."""

    target: int


@dataclass(frozen=True)
class Forget:
    """Its owner asked her to forget `target`: removed, never answered again, not even as history."""

    target: int


@dataclass(frozen=True)
class Noop:
    """The conversation restated `target`, or said nothing worth keeping (`target` None)."""

    target: int | None


Op = Add | Update | Invalidate | Forget | Noop
"""What the write job decides about one thing a conversation said, against the current facts most like it."""


@dataclass(frozen=True)
class Recalled:
    """A fact retrieved for a reply. `may_volunteer` is False for another person's discreet fact: she answers it when
    asked directly and never raises it herself."""

    fact: Fact
    may_volunteer: bool


@dataclass(frozen=True)
class Unwritten:
    """A conversation with turns memory has not learned from yet. `written_through` is the newest turn id already
    written for it, None before its first write; only turns after it are still to write. `newest_turn` is its newest
    turn id when it was picked."""

    conversation_id: int
    household_id: int
    written_through: int | None
    newest_turn: int


@dataclass(frozen=True)
class Asker:
    """Who a recall is for. `speaker_id` is None when no signal names the speaker, who then gets shared facts only.
    `owner_only` is True when only the speaker will hear or read the reply (a DM, the web app): their own private
    facts may come back only then."""

    household_id: int
    speaker_id: int | None
    owner_only: bool
    at: datetime
