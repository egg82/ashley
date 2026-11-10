"""The in-memory stand-ins of the blind WatchTools tests: the constants, the kinds swapped into the registry, the store, the proposals, the people and the tool shelf (see `watch_tools_blind_support` for the assumptions)."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ashley import services
from ashley.connections import ports
from ashley.connections.connections import Connections
from ashley.connections.model import Port
from ashley.criteria.condition import Condition
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.proposal_payloads import Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused, Proposals, refusal
from ashley.tools.tools import Catalogue, Tools
from ashley.watches.config import CONFIG, KindConfig
from ashley.watches.diff import Items
from ashley.watches.model import Arm, Armed, State, Watch
from ashley.watches.registry import KINDS
from ashley.watches.watches import Watches

DENVER = ZoneInfo("America/Denver")
HOUSE, ALANA, SAM = 1, 11, 12
CONVERSATION = 5
PLANT = "WTL-PLANTED-qx"
TARGET = "sess-wtl-1"
OTHER = "sess-wtl-2"
LABEL = f"{PLANT}-label"
TRACK = ("status", "seq")
KIND = "claude_session"
READ = ToolSpec("look_up", "look something up", {"type": "object"}, reads=True)
ACT = ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False)
SPEC_NAMES = ("watch", "unwatch", "watches")
_SLOT = "_kinds"


class FakeItems(dict[str, Mapping[str, Any]]):
    """What a kind's successful read answers: item id to tracked fields, and the display label of each."""

    def __init__(self, fields: Mapping[str, Mapping[str, Any]], labels: Mapping[str, str]) -> None:
        super().__init__(fields)
        self.labels = dict(labels)


class Everywhere(Mapping[Any, Any]):
    """A read's answer for whatever key the caller looks it up by: the same result for every watch."""

    def __init__(self, result: Any) -> None:
        self.result = result

    def __getitem__(self, key: Any) -> Any:
        return self.result

    def __contains__(self, key: object) -> bool:
        return True

    def __iter__(self) -> Iterator[Any]:
        return iter((0,))

    def __len__(self) -> int:
        return 1


@dataclass
class FakeKind:
    name: str = KIND
    port: Port = "herdr"
    track: tuple[str, ...] = TRACK
    when: object = CONFIG.kinds[KIND].when
    interval_s: int = 15
    hours: int = 24
    max_hours: int = 168
    empty_is_absent: bool = True
    outside: bool = False
    answer: Any = None
    reads: int = 0
    raises: Exception | None = None

    async def read(self, group: Any) -> Mapping[Any, Any]:
        self.reads += 1
        if self.raises is not None:
            raise self.raises
        if isinstance(self.answer, FakeItems):
            target = group[0].target
            return Everywhere(FakeItems({k: v for k, v in self.answer.items() if k == target}, self.answer.labels))
        return Everywhere(self.answer)

    async def available(self, household_id: int, person_id: int) -> bool:
        return await ports.opened(services.get(Connections), self.port, household_id, person_id) is not None

    async def label(self, watch: Any) -> str:
        labels = getattr(self.answer, "labels", {})
        return str(labels.get(watch.target, watch.target))

    def config(self) -> KindConfig:
        shipped = CONFIG.kinds[KIND]
        return KindConfig(self.interval_s, self.hours, self.max_hours, shipped.handoff_hours, tuple(self.track),
                          shipped.when, shipped.handoff_until, shipped.outside)


def items(status: str = "working", seq: int = 3) -> FakeItems:
    """The read of two sessions, TARGET the one watched."""
    return FakeItems({TARGET: {"status": status, "seq": seq}, OTHER: {"status": "idle", "seq": 1}},
                     {TARGET: LABEL, OTHER: "other"})


def without_target() -> FakeItems:
    return FakeItems({OTHER: {"status": "idle", "seq": 1}}, {OTHER: "other"})


class FakeKinds:
    """The kinds the process has, swapped into the app's one registry and its config for the length of a test."""

    def __init__(self, *kinds: FakeKind) -> None:
        self.kinds = {k.name: k for k in kinds}
        self._kept = (dict(getattr(KINDS, _SLOT)), dict(CONFIG.kinds))

    def install(self) -> None:
        setattr(KINDS, _SLOT, dict(self.kinds))
        self._swap({k: v.config() for k, v in self.kinds.items()})

    def restore(self) -> None:
        setattr(KINDS, _SLOT, self._kept[0])
        self._swap(self._kept[1])

    @staticmethod
    def _swap(configs: Mapping[str, KindConfig]) -> None:
        shipped = CONFIG.kinds
        assert isinstance(shipped, dict)
        shipped.clear()
        shipped.update(configs)


def FakeWatch(kind: str, target: str, label: str, until: Condition, expires_at: datetime, state: State = "armed",
              reason: str | None = None, id: int = 1) -> Watch:
    """A live watch as the store lists it."""
    now = datetime.now(UTC)
    return Watch(id, HOUSE, ALANA, kind, target, label, None, "ashley", TRACK, CONFIG.kinds[KIND].when, until or None,
                 None, 15, expires_at, state, reason, 0, 0, 0, None, now, now, None, None)


@dataclass(frozen=True)
class Taken:
    """An `Arm` as the store took it: no `until` is the empty condition, no baseline an empty read."""

    household_id: int
    person_id: int
    kind: str
    target: str
    label: str
    bench_id: int | None
    armed_by: str
    track: tuple[str, ...]
    when: Condition
    until: Condition
    tools: tuple[str, ...] | None
    interval_s: float
    expires_at: datetime
    baseline: Items


def taken(arm: Arm) -> Taken:
    return Taken(arm.household_id, arm.person_id, arm.kind, arm.target, arm.label, arm.bench_id, arm.armed_by,
                 arm.track, arm.when, arm.until or (), arm.tools, arm.interval_s, arm.expires_at,
                 {} if arm.baseline is None else arm.baseline)


class FakeWatches(Watches):
    """Records each `arm`, `disarm` and `live` it is asked."""

    def __init__(self) -> None:
        self.armed: list[Taken] = []
        self.disarmed: list[tuple[int, int, str, str]] = []
        self.lives: list[tuple[int, int]] = []
        self.rows: list[Watch] = []
        self.disarm_answer = True
        self.arm_raises: Exception | None = None
        self.disarm_raises: Exception | None = None

    async def arm(self, arm: Arm) -> Armed:
        if self.arm_raises is not None:
            raise self.arm_raises
        self.armed.append(taken(arm))
        return Armed(len(self.armed), True)

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        if self.disarm_raises is not None:
            raise self.disarm_raises
        self.disarmed.append((household_id, person_id, kind, target))
        return self.disarm_answer

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        self.lives.append((household_id, person_id))
        return tuple(self.rows)

    async def get(self, watch_id: int) -> Watch | None:
        raise NotImplementedError

    async def due(self, limit: int) -> tuple[Watch, ...]:
        raise NotImplementedError

    async def record(self, watch_id: int, version: int, check: Any) -> bool:
        raise NotImplementedError

    async def expire(self, keep_s: float) -> Any:
        raise NotImplementedError


class FakeProposals(Proposals):
    """The latest proposal per (maker, conversation, topic), taken through the real gate."""

    def __init__(self) -> None:
        self.held: dict[tuple[int, int, str], Proposal[Any]] = {}
        self.proposed: list[Proposal[Any]] = []

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        self.proposed.append(proposal)
        topic = encode(proposal.payload)[0]
        self.held[(proposal.made_by, proposal.conversation_id, topic)] = proposal
        return len(self.proposed)

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return self.held.get((made_by, conversation_id, topic.name))

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        found = self.held.get((made_by, conversation_id, topic.name))
        if found is None:
            raise ProposalRefused("none")
        why = refusal(found, turn_id, datetime.now(UTC), ttl_s)
        if why is not None:
            raise ProposalRefused(why)
        del self.held[(made_by, conversation_id, topic.name)]
        return found

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise AssertionError("not used")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise AssertionError("not used")


class Folk(People):
    def __init__(self, home: Household) -> None:
        self.home = home

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class Shelf(Tools):
    """The tools the speaker has in this turn, which a watch may name."""

    def __init__(self, *specs: ToolSpec) -> None:
        self.specs = specs

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "{}")
