"""The Proposals service (`ashley.services`): what she proposed to a person and nobody has agreed to yet, a typed payload
(`proposal_payloads`: a money rule, a reminder or a change to one, a change to the house). She proposes in one person turn
and takes the proposal back out only in a later person turn of the same conversation, within `ttl_s`
(`proposal_gate.gate`), so she cannot propose and agree in one breath. A person has one pending proposal per
conversation and `Topic` (one per person for a topic whose scope is `person`): a new one replaces the earlier of its topic (`decisions.md`, "Her proposals are one store")."""

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..services import Service
from .proposal_gate import Refusal, gate
from .proposal_payloads import Payload, Topic, lapsed


class ProposalsUnavailable(Exception):
    """The database could not be reached or written. Transient."""


@dataclass(frozen=True)
class Proposal[P: Payload]:
    """`payload` proposed to the person `made_by` in the person turn `turn_id` of `conversation_id` at `proposed_at`, for
    `household_id`. `id` is the stored row's, set on a proposal read back and None on one about to be proposed; it is not part of a
    proposal's equality."""

    household_id: int
    made_by: int
    conversation_id: int
    turn_id: int
    proposed_at: datetime
    payload: P
    id: int | None = field(default=None, compare=False)


class ProposalRefused(Exception):
    """A proposal cannot be taken now; `reason` is a `Refusal`."""

    def __init__(self, reason: Refusal) -> None:
        super().__init__(reason)
        self.reason: Refusal = reason


def refusal[P: Payload](proposal: Proposal[P], turn_id: int, now: datetime, ttl_s: float) -> Refusal | None:
    """Why `proposal` cannot be taken in the person turn `turn_id` of its conversation at `now`, None when it can: from a
    turn stored after the one it was proposed in, within `ttl_s` of proposing it (`proposal_gate.gate`), and for a
    reminder to schedule, before the time it was proposed for."""
    why = gate(proposal.turn_id, proposal.proposed_at, turn_id, now, ttl_s)
    if why is None and lapsed(proposal.payload, now):
        return "expired"
    return why


class Proposals(Service):
    @classmethod
    def null(cls) -> "Proposals":
        return NullProposals()

    @abstractmethod
    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        """Store `proposal`, replacing `made_by`'s earlier ones of its topic in its conversation (the latest is the one that
        can be taken), and drop the topic's that are older than `ttl_s`; its id. Raises ValueError for a payload
        `proposal_payloads.check` refuses, ProposalsUnavailable."""

    @abstractmethod
    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        """The latest proposal of `topic` `made_by` made in `conversation_id` (in any, for a `person`-scoped topic) and
        nobody has taken, None when there is none.
        Raises ProposalsUnavailable."""

    @abstractmethod
    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        """The latest proposal of `topic` `made_by` made in `conversation_id` (in any, for a `person`-scoped topic), taken in the person turn `turn_id` and
        consumed: the caller then carries it out. Raises ProposalRefused (`none` when there is no proposal; `refusal` says
        when else), ProposalsUnavailable."""

    @abstractmethod
    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        """The proposal `proposal_id` of `topic`, whoever made it, while nobody has taken it and it has not been replaced;
        None otherwise. Raises ProposalsUnavailable."""

    @abstractmethod
    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        """`find`'s proposal, taken in the person turn `turn_id` by `made_by` and consumed: the caller then carries it
        out. Raises ProposalRefused (`none` when it is gone, `expired`, `same_turn`, `not_yours` when `made_by` did not
        make it), ProposalsUnavailable."""


class NullProposals(Proposals):
    """What an unwired process sees: every call raises, so nothing is agreed against nothing."""

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        raise ProposalsUnavailable("proposals are not wired")

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise ProposalsUnavailable("proposals are not wired")

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        raise ProposalsUnavailable("proposals are not wired")

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise ProposalsUnavailable("proposals are not wired")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise ProposalsUnavailable("proposals are not wired")
