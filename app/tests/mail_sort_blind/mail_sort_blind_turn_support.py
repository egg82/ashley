"""The sort's woken turn, for the blind tests of the tiers and the held changes (`decisions.md`, "The inbox watch and the
sort"): the real `watch_turn.inbound` builds the turn from a `Watch`, the real `Landing` (which stands `Outside` in front
of the turn's tools) runs the calls, `MailTools` runs a call that gets through, and the mail port, the resource gate and
the proposals are in memory. So a test sees only whether a mail call reached the port or was held, and what the person is
shown.

  G3  `watch_turn.inbound(wake_id, watch, wake, on_bench)` builds the turn; the `Landing` of that `Inbound` is the turn's tool
      source. A resumed turn is a `Landing` of the same `Inbound` built with `tainted="watch"`, as `channels.resume` builds it.
  G4  A mail call is a `ToolCall("mail_label", {"mailbox", "messages": [{id, from, subject}], "add", "remove", "folder",
      "unread"})` as the shipped spec says (`ashley.tools.mail_change_specs`); a call that names a label the household has
      not made is the tool's to refuse, so every label a test names here is one `RecordingMailbox` lists.
  G9  The watch's `brief` reaches her in the woken `Inbound.note` and is never part of `Inbound.text`, the household's
      stored message (as a reminder's brief is her note alone).
  G5  Holding a call is observable as the shipped held result (`outside_config.load().held`) and no call reaching the port;
      running one as a result that is not that text, and a call recorded on `RecordingMailbox.changes`."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, TypeVar

from ashley import services
from ashley.channels import limits
from ashley.channels.landing import Landing
from ashley.channels.model import Inbound
from ashley.channels.wake import watch_turn
from ashley.connections.connections import Connections
from ashley.connections.model import Connection, Resource, ResourceKind
from ashley.connections.resources import ConnectionResources, Usable, Use
from ashley.criteria.record import Change
from ashley.inference.model import ToolCall, ToolResult
from ashley.inference.reply import Reply, Says
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, Label, MailChange, Message, MailQuery, Page, Header, Target
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposal_payloads import HOUSE, OUTSIDE, REMINDERS, Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused, Proposals, refusal
from ashley.senses.wakes import WatchWake
from ashley.tools import outside_config
from ashley.watches.config import CONFIG
from ashley.watches.model import Watch
from ashley.watches.rows import changed_wake
from money_support import HeldConnections
from outside_record_support import MemoryRecord
from mail_sort_blind_support import ADDRESS, BRIEF, KIND, OTHER_ADDRESS, TRACK

T = TypeVar("T")
HOUSEHOLD, PERSON, CONVERSATION, TURN = 1, 7, 5, 40
SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)
BOXES = {ADDRESS: 11, OTHER_ADDRESS: 12}
LABELS = ("School", "School trips", "Work", "Receipts")
SORT_TOOLS = ("mail_boxes", "mail_labels", "mail_search", "mail_read", "mail_label", "mail_draft", "mail_send")
EPOCH = datetime(2026, 11, 1, tzinfo=UTC)
TOPICS: dict[str, Topic[Any]] = {t.name: t for t in (REMINDERS, HOUSE, OUTSIDE)}
HELD = outside_config.load().held


def entry(ident: str, sender: str = "Alice <alice@school.test>", subject: str = "Field trip") -> dict[str, str]:
    return {"id": ident, "from": sender, "subject": subject}


M1, M2 = entry("m1"), entry("m2", "Bob <bob@shop.test>", "Invoice")


def label_args(*messages: dict[str, str], mailbox: str = ADDRESS, **over: object) -> dict[str, object]:
    return {"mailbox": mailbox, "messages": list(messages), **over}


@dataclass
class RecordingMailbox(Mailbox):
    """A mail port that accepts every change and records it: connection id, targets, change; and every draft and send."""

    changes: list[tuple[int, tuple[Target, ...], MailChange]] = field(default_factory=list[tuple[int, tuple[Target, ...], MailChange]])
    written: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        return Page((), False, "")

    async def address(self, account: Account) -> str:
        raise AssertionError("not asked")

    async def labels(self, account: Account) -> tuple[Label, ...]:
        return tuple(Label(n, False) for n in LABELS)

    async def read(self, account: Account, message_id: str) -> Message:
        raise AssertionError("not asked")

    async def draft(self, account: Account, draft: Draft) -> str:
        self.written.append(("draft", account.connection_id))
        return "d1"

    async def send(self, account: Account, draft: Draft) -> str:
        self.written.append(("send", account.connection_id))
        return "s1"

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        self.changes.append((account.connection_id, targets, change))
        return len(targets)


class TwoBoxes(ConnectionResources):
    """The person's two mailboxes, address to connection id (`BOXES`), both usable for a change."""

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        return tuple(Usable(Connection(cid, use.household_id, "google", "", PERSON, EPOCH, EPOCH, PERSON, "", None, SCOPES),
                            Resource(address, "mailbox", address, True)) for address, cid in BOXES.items())

    async def of_household(self, household_id: int, person_id: int | None = None) -> Any:
        return {}

    async def listed(self, connection_id: int, household_id: int, found: Any) -> Any:
        raise AssertionError("not used")

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str, shared: bool) -> Any:
        raise AssertionError("not used")


class Held(Proposals):
    """Proposals in memory, the latest per (maker, conversation, topic), taken through the real gate."""

    def __init__(self) -> None:
        self.held: dict[tuple[int, int, str], Proposal[Any]] = {}
        self.proposed: list[Proposal[Any]] = []

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        self.proposed.append(proposal)
        topic, stored = encode(proposal.payload)
        self.held[(proposal.made_by, proposal.conversation_id, topic)] = replace(
            proposal, payload=TOPICS[topic].decode(stored), id=len(self.proposed))
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


def sort_watch(**over: Any) -> Watch:
    """The sort: a standing `mail_inbox` watch on ADDRESS of PERSON, its turn offered SORT_TOOLS."""
    fields: dict[str, Any] = dict(
        id=3, household_id=HOUSEHOLD, person_id=PERSON, kind=KIND, target=ADDRESS, label="inbox", bench_id=None,
        armed_by="ashley", track=TRACK, when=CONFIG.kinds[KIND].when, until=None, tools=SORT_TOOLS,
        interval_s=60, expires_at=EPOCH, state="armed", reason=None, failures=0, version=3, series=1, baseline=None,
        next_check_at=EPOCH, armed_at=EPOCH, last_woke_at=None, ended_at=None, brief=BRIEF, standing=True)
    fields.update(over)
    return Watch(**fields)


def woken(watch: Watch) -> Inbound:
    """The turn a wake of `watch` for one new message starts."""
    new = Change("m2", "new", None, {"from": "Bob <bob@shop.test>", "subject": "Invoice", "unread": True, "labels": ""})
    wake = WatchWake(watch.household_id, watch.person_id, watch.id, "changed", changed_wake(1, EPOCH, False, (new,)))
    return watch_turn.inbound(9, watch, wake, False)


@dataclass
class Rig:
    mailbox: RecordingMailbox
    proposals: Held

    def turn(self, inbound: Inbound, tainted: str | None = None) -> "Turn":
        return Turn(Landing(inbound, (CONVERSATION, TURN), limits.load(), tainted), self)


@dataclass
class Turn:
    landing: Landing
    rig: Rig
    serial: int = 0

    async def call(self, name: str, **arguments: object) -> ToolResult:
        self.serial += 1
        return await self.landing.call(ToolCall(f"c{self.serial}", name, dict(arguments)))

    async def label(self, *messages: dict[str, str], **change: Any) -> ToolResult:
        return await self.call("mail_label", **label_args(*messages, **change))

    async def names(self) -> set[str]:
        return {s.name for s in (await self.landing.catalogue()).specs}

    async def ends(self, text: str = "Sorted.", says: Says = "none") -> Reply:
        """Her reply as the turn stores it."""
        return await self.landing.closing(Reply(spoken=text, text=text, says=says))

    def ran(self) -> list[tuple[int, tuple[str, ...], tuple[str, ...]]]:
        """Each change that reached the port: connection id, the ids it named, the labels it added."""
        return [(c, tuple(t.id for t in targets), change.add) for c, targets, change in self.rig.mailbox.changes]


def held(result: ToolResult) -> bool:
    return not result.is_error and result.content.startswith(HELD)


def inbound_without(inbound: Inbound, **over: Any) -> Inbound:
    return replace(inbound, **over)


async def with_rig(body: Callable[[Rig], Awaitable[T]]) -> T:
    """Run `body` with the services of the woken turn wired and unwired after."""
    rig = Rig(RecordingMailbox(), Held())
    wired: dict[Any, Any] = {Mailbox: rig.mailbox, ConnectionResources: TwoBoxes(), Proposals: rig.proposals,
                             Connections: HeldConnections(), OutsideRecord: MemoryRecord()}
    for interface, provider in wired.items():
        services.register(interface, provider)
    try:
        return await body(rig)
    finally:
        for interface in wired:
            services.unregister(interface)
