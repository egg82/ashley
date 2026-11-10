"""Her arming of a sort (`decisions.md`, "The inbox watch and the sort"): `watch` takes a brief and standing; a
watch that acts is a proposal the person agrees with `arm_reminder`; and the brief is never logged."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.model import Connection, Needs, Resource, ResourceKind
from ashley.connections.resources import ConnectionResources, NullConnectionResources, Usable, Use
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.logs import Logfmt
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, Header, Label, MailChange, MailQuery, Message, Page, Target
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import REMINDERS, WatchSchedule, check, encode
from ashley.senses.proposals import Proposals
from ashley.senses.wakes import Reminder
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Catalogue, Tools
from ashley.tools.watches import WatchTools
from ashley.watches.mail_inbox import MailInbox
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from money_support import HeldConnections
from test_reminder_turn import Home

BOX = "me@example.test"
SECRET = "zq-brief-4471"
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
TOOLS = ("mail_search", "mail_label")
SORT: dict[str, object] = {"kind": "mail_inbox", "target": BOX, "tools": list(TOOLS), "brief": SECRET, "standing": True,
                           "hours": 48}


class Board(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("mail_search", "x", {"type": "object"}, reads=True, outside=True),
                          ToolSpec("mail_label", "x", {"type": "object"}, outside=False)), "")

    async def call(self, call: ToolCall) -> ToolResult:
        raise AssertionError("arming runs no tool")


class Inbox(Mailbox):
    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        return Page((Header("m1", "Pat", BOX, "Trip", NOW, "s", (), "inbox", True, 0),), False, "")

    async def address(self, account: Account) -> str:
        raise AssertionError

    async def labels(self, account: Account) -> tuple[Label, ...]:
        raise AssertionError

    async def read(self, account: Account, message_id: str) -> Message:
        raise AssertionError

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def draft(self, account: Account, draft: Draft) -> str:
        raise AssertionError

    async def send(self, account: Account, draft: Draft) -> str:
        raise AssertionError

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        raise AssertionError


class Boxes(ConnectionResources):
    def __init__(self, person_id: int, needs: Needs | None = None, none: bool = False) -> None:
        self.person_id = person_id
        self.needs: Needs | None = needs
        self.none = none

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        if self.none:
            return ()
        connection = Connection(11, use.household_id, "google", "", self.person_id, NOW, NOW, self.person_id,
                                needs=self.needs, scopes=("https://www.googleapis.com/auth/gmail.readonly",))
        return (Usable(connection, Resource(BOX, "mailbox", BOX, True)),)

    async def of_household(self, household_id: int, person_id: int | None = None) -> Any:
        return {}

    async def listed(self, connection_id: int, household_id: int, found: Any) -> Any:
        raise AssertionError

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str, shared: bool) -> Any:
        raise AssertionError


@dataclass
class World:
    url: str
    home: int
    alana: int

    def tools(self) -> WatchTools:
        return WatchTools(self.home, self.alana, turn=(1, 5), usable=Board)

    def rows(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = scalar(self.url, "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT kind, "
                                                       "target, tools, brief, standing_s IS NOT NULL AS standing "
                                                       "FROM watches ORDER BY id) t")
        return found


@asynccontextmanager
async def world(url: str, boxes: ConnectionResources | None = None) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana = person(url, home, "Alana")
    wired = {People: Home(Household(home, "home", "America/Denver", "", (Person(alana, home, "Alana"),))),
             Watches: PostgresWatches(db), Proposals: PostgresProposals(db), Connections: HeldConnections(),
             ConnectionResources: boxes or Boxes(alana), Mailbox: Inbox()}
    for interface, provider in wired.items():
        services.register(interface, provider)
    try:
        yield World(url, home, alana)
    finally:
        for interface in wired:
            services.unregister(interface)
        await db.close()


async def call(tools: Tools, name: str, args: dict[str, object]) -> ToolResult:
    return await tools.call(ToolCall("c", name, args))


def properties_of(spec: ToolSpec) -> set[str]:
    parameters: dict[str, Any] = dict(spec.parameters)
    properties: dict[str, Any] = parameters["properties"]
    return set(properties)


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def test_a_sort_is_proposed_and_armed_with_its_fields_when_they_agree(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = body(await call(w.tools(), "watch", SORT))
            assert made["armed"] is False and made["standing"] is True
            assert w.rows() == []
            later = ReminderTools(w.home, w.alana, private=True, turn=(1, 6))
            armed = body(await call(later, "arm_reminder", {}))
            assert armed["armed"] is True and armed["standing"] is True
            assert w.rows() == [{"kind": "mail_inbox", "target": BOX, "tools": list(TOOLS), "brief": SECRET,
                                 "standing": True}]
            left = scalar(db_url, "SELECT extract(epoch FROM expires_at - now()) FROM watches")
            assert 47.9 * 3600 < left <= 48 * 3600
    run(go())


def test_arming_again_with_another_brief_replaces_it_and_one_without_clears_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            for turn, brief in ((5, "first brief"), (7, "second brief")):
                await call(WatchTools(w.home, w.alana, turn=(1, turn), usable=Board), "watch", {**SORT, "brief": brief})
                body(await call(ReminderTools(w.home, w.alana, private=True, turn=(1, turn + 1)), "arm_reminder", {}))
                [row] = w.rows()
                assert row["brief"] == brief
            await call(WatchTools(w.home, w.alana, turn=(1, 9), usable=Board), "watch",
                       {"kind": "mail_inbox", "target": BOX, "tools": ["mail_search", "mail_label"]})
            body(await call(ReminderTools(w.home, w.alana, private=True, turn=(1, 10)), "arm_reminder", {}))
            [row] = w.rows()
            assert (row["brief"], row["standing"]) == (None, False)
    run(go())


@pytest.mark.parametrize("over", [
    {"kind": "claude_session", "target": "s1"},
    {"brief": ""}, {"brief": "x" * 501}, {"brief": 3}, {"standing": "yes"}])
def test_a_bad_brief_or_standing_is_refused_and_nothing_is_proposed_or_stored(
        db_url: str, over: dict[str, object]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args = {k: v for k, v in {**SORT, **over}.items() if v is not None}
            refused = await call(w.tools(), "watch", args)
            assert refused.is_error and refused.content.startswith("bad_arguments"), refused.content
            assert w.rows() == []
            assert scalar(db_url, "SELECT count(*) FROM proposals") == 0
    run(go())


def test_a_standing_sort_that_only_reads_is_armed_at_once_and_listed_with_what_it_is(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args: dict[str, object] = {"kind": "mail_inbox", "target": BOX, "tools": ["mail_search"], "brief": SECRET, "standing": True}
            assert body(await call(w.tools(), "watch", args))["armed"] is True
            [row] = w.rows()
            assert (row["brief"], row["standing"]) == (SECRET, True)
            [shown] = body(await call(w.tools(), "watches", {}))["watches"]
            assert shown["standing"] is True and shown["brief"] == SECRET
    run(go())


def test_the_watch_tool_offers_brief_and_standing_always_and_tools_only_where_a_watch_may_act(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            acting = {s.name: s for s in (await w.tools().catalogue()).specs}["watch"]
            plain = {s.name: s for s in (await WatchTools(w.home, w.alana).catalogue()).specs}["watch"]
            assert {"brief", "standing", "tools"} <= properties_of(acting) and "grant" not in properties_of(acting)
            assert {"brief", "standing"} <= properties_of(plain)
            assert "tools" not in properties_of(plain)
    run(go())


def test_mail_inbox_is_offered_only_while_a_connected_mailbox_can_be_read(db_url: str) -> None:
    async def go() -> None:
        for boxes, offered in ((None, True), (Boxes(0, needs="reconnect"), False), (Boxes(0, none=True), False),
                               (NullConnectionResources(), False)):
            async with world(db_url, boxes) as w:
                if boxes is not None:
                    services.register(ConnectionResources, boxes)
                assert await MailInbox().available(w.home, w.alana) is offered
                kinds = {s.name for s in (await w.tools().catalogue()).specs}
                assert ("watch" in kinds) is offered
    run(go())


def test_the_proposal_survives_its_stored_form_and_an_old_one_reads_as_no_brief() -> None:
    r = Reminder(1, 2, 2, "inbox", NOW + timedelta(days=1), None, tools=TOOLS)
    schedule = WatchSchedule(r, "mail_inbox", BOX, None, 48.0, None, SECRET, True)
    topic, form = encode(schedule)
    assert topic == REMINDERS.name and REMINDERS.decode(json.loads(json.dumps(form))) == schedule
    form["grant"] = ["School"]
    assert REMINDERS.decode(form) == schedule, "a grant an old proposal stored is ignored"
    for key in ("brief", "standing", "grant"):
        del form[key]
    old = REMINDERS.decode(form)
    assert isinstance(old, WatchSchedule) and (old.brief, old.standing) == (None, False)
    check(schedule)
    for bad in ("", "x" * 501, "a\x00"):
        with pytest.raises(ValueError):
            check(WatchSchedule(r, "mail_inbox", BOX, None, None, None, bad))


def test_the_brief_is_in_no_log_line(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def go() -> None:
        async with world(db_url) as w:
            await call(w.tools(), "watch", SORT)
            body(await call(ReminderTools(w.home, w.alana, private=True, turn=(1, 6)), "arm_reminder", {}))
            await call(w.tools(), "watches", {})
            await call(w.tools(), "unwatch", {"kind": "mail_inbox", "target": BOX})
    run(go())
    text = "\n".join(Logfmt().format(r) for r in caplog.records)
    assert "event=watches.armed" in text and "event=tools.call" in text
    assert SECRET not in text and BOX not in text and "School" not in text
