"""Support for the blind receipts tests that need no database: `Outside` and `Landing` over an in-memory proposals store
that numbers its proposals, an outside record in a list (or one that is down), and the judge of `receipts_blind_support`.
Names the change adds are guessed in that module's G-list."""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from ashley import services
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.senses.outside_record import DoneAction, OutsideRecord, OutsideRecordUnavailable, Recorded
from ashley.senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls, Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused, Proposals, refusal
from ashley.tools.action_judge import ActionJudge
from ashley.tools.outside import Outside, Standing
from ashley.tools.tools import Catalogue, Tools
from outside_record_support import MemoryRecord
from receipts_blind_support import SPECS, Judge

SPEAKER, HOUSEHOLD, CONVERSATION, TURN = 7, 1, 40, 100
WORDS = ("turn it on",)
LIMITS = load_limits()
WEB = Inbound(household_id=HOUSEHOLD, thread="person:7:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=SPEAKER, shared=False, place=None, channel="web", taint=None)


async def said() -> Sequence[str]:
    """What the person said, as the turn's `words` reads it."""
    return WORDS


@dataclass
class Fake(Tools):
    """Offers `specs`, records each call in `ran`."""

    specs: tuple[ToolSpec, ...]
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, "ok")


class Numbered(Proposals):
    """Proposals in a dict, one outside proposal per person as the Postgres store keeps it, each carrying the id
    `propose` answered."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str, int | None], Proposal[Any]] = {}
        self.proposed = 0

    def _key(self, made_by: int, conversation_id: int, topic: Topic[Any]) -> tuple[int, str, int | None]:
        return made_by, topic.name, None if topic.scope == "person" else conversation_id

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        self.proposed += 1
        name, _ = encode(proposal.payload)
        self.rows[(proposal.made_by, name, None if name == "outside" else proposal.conversation_id)] = replace(
            proposal, id=self.proposed)
        return self.proposed

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return self.rows.get(self._key(made_by, conversation_id, topic))

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        found = self.rows.get(self._key(made_by, conversation_id, topic))
        if found is None:
            raise ProposalRefused("none")
        why = refusal(found, turn_id, datetime.now(UTC), ttl_s)
        if why is not None:
            raise ProposalRefused(why)
        del self.rows[self._key(made_by, conversation_id, topic)]
        return found

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise AssertionError("not used")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise AssertionError("not used")


class Down(OutsideRecord):
    """An outside record that cannot be reached."""

    async def done(self, action: DoneAction) -> None:
        raise OutsideRecordUnavailable("down")

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        raise OutsideRecordUnavailable("down")

    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        raise OutsideRecordUnavailable("down")

    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        raise OutsideRecordUnavailable("down")

    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        raise OutsideRecordUnavailable("down")


class Rig:
    """An `Outside` over tools that record what ran, with the services it reads registered."""

    def __init__(self, private: bool = True, tainted: str | None = "look", record: OutsideRecord | None = None,
                 judge: Judge | None = None) -> None:
        self.proposals = Numbered()
        self.record = record or MemoryRecord()
        self.judge = judge or Judge()
        services.register(Proposals, self.proposals)
        services.register(OutsideRecord, self.record)
        services.register(ActionJudge, self.judge)
        self.source = Fake(SPECS)
        self.outside = Outside(self.source, Standing(HOUSEHOLD, SPEAKER, private=private, agreeing=True),
                               (CONVERSATION, TURN), None, tainted, None, said)

    async def call(self, name: str, call_id: str = "c1", **arguments: object) -> ToolResult:
        args = arguments or {"action": "light.turn_on", "room": "porch"}
        return await self.outside.call(ToolCall(call_id, name, args))

    async def proposal(self) -> Proposal[HeldCalls]:
        found = await self.proposals.pending(SPEAKER, CONVERSATION, OUTSIDE)
        assert found is not None, "nothing was held"
        return found


async def held_landing(inbound: Inbound = WEB, calls: Sequence[HeldCall] = ()) -> tuple[Landing, int]:
    """A `Landing` of a tainted turn with `calls` held for the person, and the proposal's id."""
    proposals = Numbered()
    services.register(Proposals, proposals)
    services.register(OutsideRecord, MemoryRecord())
    landing = Landing(replace(inbound, taint="watch"), (CONVERSATION, TURN), LIMITS)
    held = calls or (HeldCall("lamp", {"room": "porch"}, 'lamp (room: "porch")', "RB-why"),
                     HeldCall("garage", {"door": 2}, "garage (door: 2)"))
    number = await proposals.propose(Proposal(HOUSEHOLD, SPEAKER, CONVERSATION, TURN, datetime.now(UTC),
                                              HeldCalls(tuple(held))), 60)
    return landing, number
