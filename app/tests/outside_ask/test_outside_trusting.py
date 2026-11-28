"""What she may just do, at the seam (`ashley.tools.trusting`, `ashley.channels.standing.trusting`): in a turn nobody
asked for, a kind its person set to offer first is held by `Outside`'s one hold path; `act` leaves every kind exactly as
before; choices that cannot be read are offer first; the setting never lowers a tier, so a tainted turn, an `asks` tool
and an irreversible house change stay held whatever is set; and a person's own turn is not offered back to them."""

import logging
from dataclasses import dataclass, replace
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.channels import landing as landing_module
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.channels.standing import trusting
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.inference.model import Tier, ToolCall
from ashley.inference.reply import Reply
from ashley.senses.outside_record import Cause, OutsideRecord
from ashley.senses.proposal_payloads import HOUSE, OUTSIDE
from ashley.senses.proposals import Proposals
from ashley.tools.house_change import HouseChangeTools
from ashley.tools.outside import Outside, Standing
from ashley.tools.outside_config import load as outside_config
from ashley.tools.tools import Tools
from ashley.tools.trusting import Trusting
from ashley.trust.kinds import Value
from ashley.trust.trust import StoredTrust, Trust, TrustUnavailable
from house_double_support import MemoryHouse
from outside_ask_support import CONVERSATION, HOUSEHOLD, SPEAKER, TURN, Fake, Memory, asked, run, said, spec
from outside_record_support import MemoryRecord

UNASKED = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=False, unasked=True, cause=Cause("reminder", 9))
ASKED = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=True)
TOOLS = (spec("look", reads=True, outside=True), spec("todo_change", tier="runs"), spec("remind", tier="runs"),
         spec("change_reminder"), spec("cancel_reminder"), spec("house_change"), spec("mail_send"),
         spec("money_note", tier="asks"), spec("money_categorise", tier="asks"), spec("house_do"))
CHANGES = ("todo_change", "remind", "change_reminder", "cancel_reminder", "house_change", "mail_send", "money_note",
           "money_categorise", "house_do")
ARGUMENTS: dict[str, dict[str, Any]] = {"house_change": {"op": "write", "kind": "automation"}}
HELD = outside_config().held


class Told(Trust):
    """Answers `values` as the person's stored choices, or cannot be read."""

    def __init__(self, values: dict[str, Value] | None = None) -> None:
        self.values, self.reads = values, 0

    async def stored(self, household_id: int, person_id: int) -> StoredTrust:
        self.reads += 1
        if self.values is None:
            raise TrustUnavailable("down")
        assert (household_id, person_id) == (HOUSEHOLD, SPEAKER), "the person the turn is for"
        return StoredTrust(1, self.values)


@dataclass
class Rated(Fake):
    """A Fake whose own tier for every call is `rated`."""

    rated: Tier | None = None

    async def tier(self, call: ToolCall) -> Tier | None:
        return self.rated


@dataclass
class Ran:
    """What one call through the chain came to: the result, what the tools ran, what was held and recorded."""

    result: tuple[str, bool]
    ran: list[str]
    held: list[str]
    recorded: list[tuple[str, str]]


def call_through(tool: str, standing: Standing, told: Trust | None, tainted: str | None = None,
                 trusted: bool = True) -> Ran:
    """`tool` called once through `Outside` in front of `Trusting` (or, with `trusted` false, of the tools alone)."""
    out: list[Ran] = []

    async def go() -> None:
        memory, record = Memory(), MemoryRecord()
        services.register(Proposals, memory)
        services.register(OutsideRecord, record)
        if told is None:
            services.unregister(Trust)
        else:
            services.register(Trust, told)
        fake = Fake(TOOLS)
        source: Tools = Trusting(fake, HOUSEHOLD, SPEAKER) if trusted else fake
        outside = Outside(source, standing, (CONVERSATION, TURN), None, tainted, None, said)
        await outside.catalogue()
        got = await outside.call(asked(tool, **ARGUMENTS.get(tool, {})))
        pending = await memory.pending(SPEAKER, CONVERSATION, OUTSIDE)
        out.append(Ran((got.content, got.is_error), [c.name for c in fake.ran],
                       [] if pending is None else [h.tool for h in pending.payload.calls],
                       [(a.tool, a.tier) for a in record.actions]))

    run(go())
    services.unregister(Trust)
    return out[0]


def test_offer_holds_an_unasked_change_as_one_proposal_through_outsides_own_path() -> None:
    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        services.register(Trust, Told({"lists": "offer"}))
        fake = Fake(TOOLS)
        outside = Outside(Trusting(fake, HOUSEHOLD, SPEAKER), UNASKED, (CONVERSATION, TURN), None, None, None, said)
        await outside.catalogue()
        got = await outside.call(asked("todo_change", "a", op="add", list="todo.shop", item="milk"))
        ran = await outside.call(asked("remind", "b"))
        assert (got.content, got.is_error) == (HELD, False)
        assert [c.name for c in fake.ran] == ["remind"], "the offered change never ran; another kind still did"
        pending = await memory.pending(SPEAKER, CONVERSATION, OUTSIDE)
        assert pending is not None and pending.turn_id == TURN
        assert [(h.tool, dict(h.arguments)) for h in pending.payload.calls] == [
            ("todo_change", {"op": "add", "list": "todo.shop", "item": "milk"})]
        assert memory.proposed == 1 and not ran.is_error
        receipts = await outside.receipts()
        assert receipts is not None and len(receipts.held) == 1 and receipts.proposal_id == pending.id
        services.unregister(Trust)

    run(go())


@pytest.mark.parametrize("tool", CHANGES)
@pytest.mark.parametrize(("standing", "tainted"), [(UNASKED, None), (UNASKED, "watch"), (ASKED, None), (ASKED, "watch")])
def test_act_leaves_every_kind_exactly_as_it_was_without_the_setting(tool: str, standing: Standing,
                                                                     tainted: str | None) -> None:
    acting = Told({})
    assert call_through(tool, standing, acting, tainted) == call_through(tool, standing, None, tainted, trusted=False)


def test_offer_changes_what_an_unasked_turn_does_control_for_the_act_test() -> None:
    before = call_through("todo_change", UNASKED, None, trusted=False)
    after = call_through("todo_change", UNASKED, Told({"lists": "offer"}))
    assert before.ran == ["todo_change"] and after.ran == [] and after.held == ["todo_change"]


@pytest.mark.parametrize("told", [Told(None), None], ids=["unreadable", "unwired"])
def test_choices_that_cannot_be_read_are_offer_first(told: Trust | None, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, "ashley.tools"):
        got = call_through("mail_send", UNASKED, told)
    assert got.ran == [] and got.held == ["mail_send"]
    assert any("trust.unreadable" in r.getMessage() for r in caplog.records)


def test_the_choices_are_read_once_a_turn() -> None:
    async def go() -> None:
        told = Told({"lists": "offer"})
        services.register(Trust, told)
        source = Trusting(Fake(TOOLS), HOUSEHOLD, SPEAKER)
        for name in ("todo_change", "remind", "mail_send", "look"):
            await source.tier(asked(name))
        assert told.reads == 1
        services.unregister(Trust)

    run(go())


@pytest.mark.parametrize("rated", [None, "runs", "judged", "asks"])
@pytest.mark.parametrize("told", [Told({}), Told({k: "offer" for k in ("lists", "messages", "reminders", "house_setup")}),
                                  Told({"money": "act", "house_removals": "act"}), Told(None)],
                         ids=["act", "offer", "locked_act", "unreadable"])
def test_the_setting_only_ever_raises_a_tier(rated: Tier | None, told: Told) -> None:
    async def go() -> None:
        services.register(Trust, told)
        source = Trusting(Rated(TOOLS, rated=rated), HOUSEHOLD, SPEAKER)
        for name in (*CHANGES, "look", "unknown_tool"):
            for arguments in ({}, {"op": "delete", "kind": "automation"}):
                got = await source.tier(asked(name, **arguments))
                assert got in (rated, "asks"), (name, arguments, got)
                if rated == "asks":
                    assert got == "asks"
        services.unregister(Trust)

    run(go())


def test_act_never_loosens_a_tainted_turn_nor_an_asks_tool() -> None:
    tainted = call_through("mail_send", UNASKED, Told({"messages": "act"}), tainted="watch")
    assert tainted.ran == [] and tainted.held == ["mail_send"], "the judge (unwired: ask) still holds it"
    for tool in ("money_note", "money_categorise"):
        stored_act = call_through(tool, UNASKED, Told({"money": "act"}))
        assert stored_act.ran == [] and stored_act.held == [tool]


def test_a_persons_own_turn_is_never_offered_back() -> None:
    asked_turn = call_through("todo_change", ASKED, Told({"lists": "offer"}))
    assert asked_turn.ran == ["todo_change"] and asked_turn.held == []

    async def go() -> None:
        services.register(Proposals, Memory())
        rated = Rated(TOOLS, rated="asks")
        outside = Outside(rated, ASKED, (CONVERSATION, TURN), None, None, None, said)
        await outside.catalogue()
        await outside.call(asked("todo_change"))
        assert [c.name for c in rated.ran] == ["todo_change"], "an asked untainted turn holds by the spec alone"

    run(go())


class OneHome(Homes):
    def __init__(self, home: Home) -> None:
        self._home = home

    async def of(self, household_id: int) -> Home | None:
        return self._home

    async def check(self, base_url: str, token: str) -> None:
        raise NotImplementedError


@pytest.mark.parametrize("told", [Told({}), Told({"house_setup": "offer"}), Told(None)], ids=["act", "offer", "unreadable"])
def test_an_irreversible_house_change_still_proposes_by_its_own_path_whatever_is_set(told: Told) -> None:
    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        services.register(Trust, told)
        house = MemoryHouse()
        house.configs_of = {"automation": {"arrive": {"alias": "Arrival"}}, "helper": {}, "script": {}}
        http = httpx2.AsyncClient(base_url="http://ha.test:8123")
        services.register(Homes, OneHome(Home(HOUSEHOLD, HomeAssistant(http), house)))
        try:
            tools = HouseChangeTools(HOUSEHOLD, SPEAKER, private=True, turn=(CONVERSATION, TURN))
            outside = Outside(Trusting(tools, HOUSEHOLD, SPEAKER), UNASKED, (CONVERSATION, TURN), None, None, None, said)
            await outside.catalogue()
            got = await outside.call(asked("house_change", op="delete", kind="automation", id="arrive"))
            assert '"proposed"' in got.content and not got.is_error, got.content
            assert await memory.pending(SPEAKER, CONVERSATION, HOUSE) is not None
            assert await memory.pending(SPEAKER, CONVERSATION, OUTSIDE) is None, "left to the floor, not held twice"
            assert "arrive" in house.configs_of["automation"], "nothing was deleted"
        finally:
            services.unregister(Homes)
            services.unregister(Trust)
            await http.aclose()

    run(go())


REMINDER = Inbound(household_id=HOUSEHOLD, thread="device:3", text="milk", kind="chat", medium="text", audience="owner",
                   speaker_id=SPEAKER, shared=False, place=None, channel="device", unprompted=True, author="household",
                   taint=None, cause=Cause("reminder", 9))


def test_only_a_turn_nobody_asked_for_that_names_its_person_is_behind_the_setting() -> None:
    source = Fake(TOOLS)
    assert isinstance(trusting(REMINDER, source), Trusting)
    assert trusting(replace(REMINDER, unprompted=False, author="person"), source) is source
    assert trusting(replace(REMINDER, speaker_id=None), source) is source


def test_a_turn_nobody_asked_for_holds_through_landing_and_shows_it_beside_her_reply(
        monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Fake(TOOLS)
    def for_turn(*_: object) -> Tools:
        return fake

    monkeypatch.setattr(landing_module.turn_tools, "for_turn", for_turn)

    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        services.register(Trust, Told({"lists": "offer"}))
        try:
            landing = Landing(REMINDER, (CONVERSATION, TURN), load_limits())
            await landing.catalogue()
            got = await landing.call(ToolCall("c", "todo_change", {"op": "add"}))
            assert (got.content, fake.ran) == (HELD, [])
            closed = await landing.closing(Reply(spoken="s", text="Shall I?", says="none"))
            assert closed.says == "reply" and landing.held == 1
            asked_turn = Landing(replace(REMINDER, unprompted=False, author="person", thread="person:7:web",
                                         channel="web", cause=None), (CONVERSATION, TURN + 1), load_limits())
            await asked_turn.catalogue()
            assert not (await asked_turn.call(ToolCall("d", "todo_change", {"op": "add"}))).is_error
            assert [c.name for c in fake.ran] == ["todo_change"]
        finally:
            services.unregister(Trust)

    run(go())


def test_a_resumed_unasked_turn_shows_what_it_held_and_one_that_held_nothing_shows_nothing() -> None:
    async def go() -> None:
        memory = Memory()
        services.register(Proposals, memory)
        services.register(Trust, Told({"lists": "offer"}))
        first = Outside(Trusting(Fake(TOOLS), HOUSEHOLD, SPEAKER), UNASKED, (CONVERSATION, TURN), None, None, None, said)
        await first.catalogue()
        await first.call(asked("todo_change"))
        resumed = Outside(Trusting(Fake(TOOLS), HOUSEHOLD, SPEAKER), UNASKED, (CONVERSATION, TURN), None, None, None,
                          said)
        receipts = await resumed.receipts()
        assert receipts is not None and len(receipts.held) == 1
        plain = Fake(tuple(s for s in TOOLS if s.tier != "asks"))
        nothing = Outside(plain, UNASKED, (CONVERSATION, TURN + 5), None, None, None, said)
        await nothing.catalogue()
        assert await nothing.receipts() is None, "an unasked turn that held nothing shows nothing"
        services.unregister(Trust)

    run(go())
