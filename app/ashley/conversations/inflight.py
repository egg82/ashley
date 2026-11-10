"""A turn's work in flight (`docs/decisions.md`, "Work in flight survives its pod"): one row per person turn being
answered, claimed by one runner at a time and holding that runner's checkpoint, until her turn is stored. The
checkpoint is the caller's text, never read here. Every time is the database's clock."""

from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from .. import services
from ..services import Service
from .conversations import Conversations
from .model import AgreedOutcome, NewTurn, Turn


class InFlightError(Exception):
    """Base of what `InFlight` raises on purpose."""


class InFlightUnavailable(InFlightError):
    """The database could not be reached or written. Transient."""


class ClaimLost(InFlightError):
    """The work is no longer this claim's: its claim ran out and another runner took it, or it was finished or
    dropped. Nothing was written."""


@dataclass(frozen=True)
class Claim:
    """One runner's hold on the work answering person turn `said_id` of `conversation_id`. `holder` is unique to the
    runner."""

    said_id: int
    conversation_id: int
    holder: str


@dataclass(frozen=True)
class Orphan:
    """Work whose runner stopped, now claimed for the caller: the checkpoint as last saved, how many runners have
    claimed it (this one included), and how long ago the person's turn was stored, in seconds."""

    claim: Claim
    checkpoint: str
    attempts: int
    age_s: float


@dataclass(frozen=True)
class Leaving:
    """What a turn of a thread whose messages steer leaves when its work is dropped with no answer: the person turns of
    `conversation_id` after `after` (`model.unhanded`), handed to it or not, unless her final answer to `after` is
    stored there. The oldest gets work of its own, its checkpoint `seed` of that turn, claimable at once by any runner
    (`orphaned`); the rest are after it, so its turn is handed them."""

    conversation_id: int
    after: int
    seed: Callable[[Turn], str]


class InFlight(Service):
    @classmethod
    def null(cls) -> "InFlight":
        return NullInFlight()

    @property
    @abstractmethod
    def claim_s(self) -> float:
        """How long a claim lasts past its last renewal."""

    @abstractmethod
    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        """Claim new work answering person turn `said_id` of `conversation_id`, with its first checkpoint. Raises
        InFlightUnavailable; ValueError when work for `said_id` already exists, her answer to it is stored, or the
        conversation does not exist."""

    @abstractmethod
    async def save(self, claim: Claim, checkpoint: str) -> None:
        """Replace the checkpoint and renew the claim. Raises ClaimLost, InFlightUnavailable."""

    @abstractmethod
    async def renew(self, claim: Claim) -> None:
        """Renew the claim for another `claim_s`. Raises ClaimLost, InFlightUnavailable."""

    async def defer(self, claim: Claim, seconds: float) -> None:
        """Hold the claim for `seconds` from now in place of `claim_s`, so the work is orphaned, and resumed, no sooner.
        Raises ClaimLost, InFlightUnavailable. This default renews the claim for `claim_s`."""
        await self.renew(claim)

    @abstractmethod
    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        """Add `turn` (hers, said while the work goes on: a held line) to the claim's conversation and renew the claim,
        in one transaction, only while `claim` holds it; the work is kept. Raises ClaimLost; ConversationClosed;
        InFlightUnavailable; ValueError for a turn `Conversations.add_turn` refuses."""

    @abstractmethod
    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        """Add `turn` (hers) to the claim's conversation and delete the work, in one transaction, only while `claim`
        holds it; with `after`, the work is kept instead, still the claim's and renewed, its checkpoint `after` of the
        stored turn: what is left to do once her turn is stored (a memory act). Raises ClaimLost; ConversationClosed when the conversation has closed (the work is kept, for
        `drop`); InFlightUnavailable; ValueError for a turn `Conversations.add_turn` refuses."""

    @abstractmethod
    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        """Set `outcome` on the claim's person turn (`Turn.agreed`, an agreeing turn of a person's) and delete the work,
        in one transaction, only while `claim` holds it; no turn of hers is stored. Raises ClaimLost,
        InFlightUnavailable."""

    @abstractmethod
    async def drop(self, claim: Claim) -> bool:
        """Delete the work while `claim` holds it, with no turn; nothing when it does not. Whether no work for the turn
        remains: false when another runner holds it. Raises InFlightUnavailable."""

    async def drop_leaving(self, claim: Claim, leaving: Leaving) -> bool:
        """`drop`, and in the same transaction, under the lock of `leaving.conversation_id` that a person turn's store
        takes, the work `leaving` gives the turn left without an answer, so a message is either left to that work or
        stored after it. Raises InFlightUnavailable."""
        return await self.drop(claim)

    @abstractmethod
    async def orphaned(self, limit: int) -> list[Orphan]:
        """Claim for a new runner each piece of work (at most `limit`, oldest first) whose claim has run out, adding one
        to its attempts. Two callers at once never claim the same piece. Raises InFlightUnavailable."""

    @abstractmethod
    async def working(self, conversation_id: int) -> frozenset[int]:
        """The ids of the person turns of `conversation_id` still owed their answer that have work: being answered by a
        runner, or waiting for one to resume it; an ask carried there from a turn that landed on its bench
        (`NewTurn.carried_from`) counts while that turn's work is unanswered there. Work kept only for a memory act after her answer is stored is not
        counted. Raises InFlightUnavailable."""


class NullInFlight(InFlight):
    """Keeps nothing, so nothing survives its pod: every claim holds, a turn is said and finished by
    `Conversations.add_turn`, an agreed outcome is not kept, and nothing is ever orphaned."""

    @property
    def claim_s(self) -> float:
        return 15.0

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        return Claim(said_id, conversation_id, "")

    async def save(self, claim: Claim, checkpoint: str) -> None:
        return None

    async def renew(self, claim: Claim) -> None:
        return None

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        return await services.get(Conversations).add_turn(claim.conversation_id, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        return await services.get(Conversations).add_turn(claim.conversation_id, turn)

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        return None

    async def drop(self, claim: Claim) -> bool:
        return True

    async def orphaned(self, limit: int) -> list[Orphan]:
        return []

    async def working(self, conversation_id: int) -> frozenset[int]:
        return frozenset()
