"""Helpers for the blind `mail_inbox` watch-kind tests (`decisions.md`, "The inbox watch and the sort", build part 7):
the real `MailInbox` kind driven through the real `watches` job against a recording fake of the `Watches` store, a fake
`Mailbox` port and a fake `ConnectionResources`, so no database is needed except for the store's `Later` tests.

The implementation did not exist when these were written. Every guess beyond the spec is a numbered G in the ASSUMPTIONS
block below and in `assumptions.txt` beside this file; a reconciler adjusts it here and nowhere else.

ASSUMPTIONS (the spec phrase each rests on is in `assumptions.txt`):
  G1  `ashley.watches.model.Later` is a frozen dataclass built with no arguments, `Later()`, and the store's `record`
      takes it like the other four checks.
  G2  The kind finds a watch's mailbox by `ConnectionResources.usable(use, False)` (kind "mailbox"), the resource whose
      `ref` is the watch's `target`, and reads it through `Mailbox.search(Account(connection.id, ...), query)`.
  G3  The inbox is read with `MailQuery(folder="inbox")` and further pages with `MailQuery.page`, until `max_items`
      headers are had or `Page.cursor` is empty; a header's `folder` is "inbox" for an inbox message.
  G4  An item's fields are `from` (Header.sender), `subject`, `unread` (bool) and `labels` as ONE text scalar holding the
      label names (items hold scalars only); `labels_of` below reads the names back from it.
  G5  A mailbox that answers `MailFailed("syncing")` makes the kind's read for that watch a `Later` check by the job
      (however the read says so); any other `MailFailed` is a `Failed` check, `unreachable` for `unreachable`.
  G6  A target that none of the person's usable mailboxes has fails the read `not_connected` and the Mailbox is not asked.
  G7  `ashley.watches.registry.KINDS.get("mail_inbox")` is the kind, and `watches.json` has a `mail_inbox` entry."""

import asyncio
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from ashley import services
from ashley.criteria.items import ItemPredicate
from ashley.connections.connections import ConnectionsUnavailable
from ashley.connections.model import Connection, Resource, ResourceKind
from ashley.connections.resources import ConnectionResources, Usable, Use
from ashley.mail import config as mail_config
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target
from ashley.watches import job
from ashley.watches.config import CONFIG
from ashley.watches.kinds import Registry
from ashley.watches.mail_inbox import MailInbox
from ashley.watches.model import Counts, Watch
from ashley.watches.watches import Watches

KIND = "mail_inbox"
HOUSEHOLD, PERSON = 1, 7
ADDRESS = "zq-box-4471@example.test"
OTHER_ADDRESS = "zq-other-9083@example.test"
SENDER = "zq-sender-2290@strangers.test"
SUBJECT = "zq-subject-7715"
LABEL = "zq-label-3318"
T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)
PAGE = 20  # the fake answers pages of at most this many, so a read of max_items ends mid-page
TRACK = ("from", "subject", "unread", "labels")


CONF = replace(CONFIG, tick_s=0.01, batch=10, read_timeout_s=0.5, fail_after=3, retry_s=60.0, keep_s=1000.0)
EPOCH = datetime(2026, 11, 1, tzinfo=UTC)
FAR = EPOCH + timedelta(days=30)


def run(scenario: Coroutine[Any, Any, None], limit: float = 15.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())


def pred(kind: str, field_: str | None = None, **extra: Any) -> ItemPredicate:
    fields: dict[str, Any] = dict(kind=kind, field=field_, **extra)
    return ItemPredicate(**fields)


def watch_of(id_: int = 1, **over: Any) -> Watch:
    """A due, armed watch of PERSON with every column a `Watch` has; `over` replaces any."""
    fields: dict[str, Any] = dict(
        id=id_, household_id=HOUSEHOLD, person_id=PERSON, kind=KIND, target=f"s{id_}", label="label", bench_id=None,
        armed_by="ashley", track=TRACK, when=(), until=None, tools=None, interval_s=15, expires_at=FAR, state="armed",
        reason=None, failures=0, version=3, series=0, baseline=None, next_check_at=EPOCH, armed_at=EPOCH,
        last_woke_at=None, ended_at=None)
    fields.update(over)
    return Watch(**fields)


class FakeWatches(Watches):
    """The Watches store in memory: `queue` is what `due` offers, every call is recorded, `record` answers True."""

    def __init__(self) -> None:
        self.queue: list[Watch] = []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def checks(self) -> dict[int, Any]:
        return {args[0]: args[2] for name, args in self.calls if name == "record"}

    async def expire(self, keep_s: float) -> Counts:
        return Counts(0, 0)

    async def due(self, limit: int) -> tuple[Watch, ...]:
        return tuple(self.queue[:limit])

    async def record(self, watch_id: int, version: int, check: Any) -> bool:
        self.calls.append(("record", (watch_id, version, check)))
        return True

    async def arm(self, arm: Any) -> Any:
        raise AssertionError("the job never arms")

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("the job never disarms")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        raise AssertionError("the job never lists")

    async def get(self, watch_id: int) -> Watch | None:
        raise AssertionError("the job never reads one")


def labels_of(value: Any) -> set[str]:
    """The label names an item's `labels` scalar holds (G4)."""
    return {part.strip() for part in str(value).split(",") if part.strip()}


def msg(n: int, *, folder: str = "inbox", sender: str = SENDER, subject: str | None = None, unread: bool = True,
        labels: tuple[str, ...] = ()) -> Header:
    """A header whose date rises with `n`, so a larger `n` is newer; its id is `m<n>`."""
    return Header(f"m{n:04d}", sender, ADDRESS, subject or f"{SUBJECT}-{n}", T0 + timedelta(minutes=n), "snippet", labels,
                  folder, unread, 0)


class FakeMailbox(Mailbox):
    """A mailbox port in memory: `boxes` maps a connection id to its headers, `syncing` the connection ids that answer
    `MailFailed("syncing")`, `fail` one reason every call raises. A search honours `folder` ('' is every folder), answers
    newest first at most `search_max`, and pages by cursor, as the port says. `queries` records each call."""

    def __init__(self) -> None:
        self.boxes: dict[int, list[Header]] = {}
        self.syncing: set[int] = set()
        self.fail: dict[int, MailFailed] = {}
        self.queries: list[tuple[int, MailQuery]] = []

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        self.queries.append((account.connection_id, query))
        if account.connection_id in self.fail:
            raise self.fail[account.connection_id]
        if account.connection_id in self.syncing:
            raise MailFailed("syncing")
        found = sorted((h for h in self.boxes.get(account.connection_id, []) if query.folder in ("", h.folder)),
                       key=lambda h: h.date, reverse=True)
        start = int(query.page or 0)
        cap = min(mail_config.load().search_max, PAGE)
        more = start + cap < len(found)
        return Page(tuple(found[start:start + cap]), more, str(start + cap) if more else "")

    async def address(self, account: Account) -> str:
        raise AssertionError("the watch kind never asks a mailbox its address")

    async def labels(self, account: Account) -> tuple[Label, ...]:
        raise AssertionError("the watch kind only searches")

    async def read(self, account: Account, message_id: str) -> Message:
        raise AssertionError("the watch kind never reads a body")

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return False

    async def draft(self, account: Account, draft: Draft) -> str:
        raise AssertionError("the watch kind never changes mail")

    async def send(self, account: Account, draft: Draft) -> str:
        raise AssertionError("the watch kind never changes mail")

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        raise AssertionError("the watch kind never changes mail")


class FakeResources(ConnectionResources):
    """The mailboxes the person may use: address to connection id. `down` raises ConnectionsUnavailable."""

    def __init__(self, mailboxes: Mapping[str, int]) -> None:
        self.mailboxes = dict(mailboxes)
        self.down = False

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        if self.down:
            raise ConnectionsUnavailable("down")
        return tuple(Usable(_connection(cid, use), Resource(address, "mailbox", address, True))
                     for address, cid in self.mailboxes.items())

    async def of_household(self, household_id: int, person_id: int | None = None) -> Any:
        raise AssertionError("the watch kind resolves a mailbox through `usable`")

    async def listed(self, connection_id: int, household_id: int, found: Any) -> Any:
        raise AssertionError("not used")

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str, shared: bool) -> Any:
        raise AssertionError("not used")


def _connection(connection_id: int, use: Use) -> Connection:
    return Connection(connection_id, use.household_id, "google", "", PERSON, T0, T0, PERSON, "", None,
                      ("https://www.googleapis.com/auth/gmail.readonly",))


@dataclass
class World:
    """The fakes behind one kind, the store the job records into, and the job's registry."""

    mailbox: FakeMailbox = field(default_factory=FakeMailbox)
    resources: FakeResources = field(default_factory=lambda: FakeResources({ADDRESS: 11}))
    store: FakeWatches = field(default_factory=FakeWatches)

    def __post_init__(self) -> None:
        services.register(Mailbox, self.mailbox)
        services.register(ConnectionResources, self.resources)

    def inbox(self, *headers: Header, connection: int = 11) -> None:
        self.mailbox.boxes[connection] = list(headers)

    async def tick(self, *watches: Any) -> Any:
        """One job tick over `watches` as due, read by the real kind; the checks it recorded, by watch id."""
        self.store.queue = list(watches)
        services.register(Watches, self.store)
        await job.tick(CONF, Registry([MailInbox()]))
        return self.store.checks()

    async def check(self, watch: Any) -> Any:
        return (await self.tick(watch))[watch.id]


def mail_watch(id_: int = 1, **over: Any) -> Any:
    """A due `mail_inbox` watch on ADDRESS with the kind's own default `when` and no `until`."""
    fields: dict[str, Any] = dict(kind=KIND, target=ADDRESS, track=TRACK, when=CONFIG.kinds[KIND].when, until=None,
                                  armed_by="ashley", interval_s=CONFIG.kinds[KIND].interval_s)
    fields.update(over)
    return watch_of(id_, **fields)


def baseline_of(*headers: Header) -> dict[str, dict[str, Any]]:
    """What a read of an inbox of `headers` is, as G4 says, for a watch's stored baseline."""
    return {h.id: {"from": h.sender, "subject": h.subject, "unread": h.unread, "labels": ", ".join(h.labels)}
            for h in headers}

