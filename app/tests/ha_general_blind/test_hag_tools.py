"""`house_change` and `house_confirm` (`tools.house_change.HouseChangeTools`) and the house tools (`tools.house_tools`)
over a recording House and the Postgres proposals store: what she does on her own is done, what `irreversible.json`
covers is only proposed in the turn it is asked and taken only from a later person turn of the same conversation by the
person who proposed it, within the limit; reads are never gated; nothing she is shown reaches the log."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley.home_assistant.change import Change
from ashley.home_assistant.house import State
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.proposal_payloads import HOUSE, HouseChange
from ashley.senses.proposals import Proposal
from ashley.tools.house_change import CHANGE, CONFIRM, HouseChangeTools
from contract.conversations_support import run, scalar
from hag_world_support import RecordingHouse, World, world

CONVERSATION = 41
ONE_HOUR = 3600.0
SAUNA = {"name": "Sauna", "aliases": ["steam room"]}


def tools(w: World, who: int | None = None, turn: int | None = 1, conversation: int = CONVERSATION, private: bool = True,
          ttl_s: float | None = None) -> HouseChangeTools:
    return HouseChangeTools(w.home, who or w.alana, private=private, turn=None if turn is None else (conversation, turn), ttl_s=ttl_s)


async def say(t: HouseChangeTools, tool: str, /, **arguments: Any) -> ToolResult:
    return await t.call(ToolCall("c1", tool, arguments))


async def change(t: HouseChangeTools, op: str, kind: str, **rest: Any) -> ToolResult:
    arguments = {k: (json.dumps(v) if k == "data" else v) for k, v in rest.items()}
    return await say(t, CHANGE, op=op, kind=kind, **arguments)


async def offered(t: HouseChangeTools) -> set[str]:
    return {s.name for s in (await t.catalogue()).specs}


UNCOVERED: list[tuple[str, str, dict[str, Any], tuple[str, tuple[object, ...]]]] = [
    ("write", "automation", {"id": "porch", "data": {"alias": "Porch", "triggers": [], "actions": []}},
     ("write_config", ("automation", "porch", {"alias": "Porch", "triggers": [], "actions": []}))),
    ("write", "script", {"id": "bye", "data": {"alias": "Bye", "sequence": []}},
     ("write_config", ("script", "bye", {"alias": "Bye", "sequence": []}))),
    ("write", "helper", {"data": {"type": "input_boolean", "name": "Guests"}},
     ("write_config", ("helper", None, {"type": "input_boolean", "name": "Guests"}))),
    ("create", "area", {"data": SAUNA}, ("create_record", ("area", SAUNA))),
    ("create", "label", {"data": {"name": "Guest"}}, ("create_record", ("label", {"name": "Guest"}))),
    ("update", "entity", {"id": "light.lamp", "data": {"name": "Bedside", "aliases": ["lamp"]}},
     ("update_record", ("entity", "light.lamp", {"name": "Bedside", "aliases": ["lamp"]}))),
    ("update", "device", {"id": "dev1", "data": {"area": "Kitchen"}}, ("update_record", ("device", "dev1", {"area": "Kitchen"}))),
]

COVERED: list[tuple[str, str, dict[str, Any], Change]] = [
    ("delete", "automation", {"id": "porch"}, Change("delete", "automation", "porch")),
    ("delete", "script", {"id": "bye"}, Change("delete", "script", "bye")),
    ("delete", "helper", {"id": "input_boolean:guests"}, Change("delete", "helper", "input_boolean:guests")),
    ("delete", "area", {"id": "kitchen"}, Change("delete", "area", "kitchen")),
    ("delete", "entity", {"id": "light.lamp"}, Change("delete", "entity", "light.lamp")),
    ("delete", "device", {"id": "dev1"}, Change("delete", "device", "dev1")),
    ("delete", "integration", {"id": "entry_hue"}, Change("delete", "integration", "entry_hue")),
    ("perform", "action", {"id": "homeassistant.restart"}, Change("perform", "action", "homeassistant.restart")),
    ("perform", "action", {"id": "recorder.purge", "data": {"keep_days": 1}},
     Change("perform", "action", "recorder.purge", {"keep_days": 1})),
    ("perform", "action", {"id": "backup.create"}, Change("perform", "action", "backup.create")),
]


def test_house_change_is_offered_to_a_known_speaker_and_house_confirm_only_with_a_proposal_to_take(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            for t in (tools(w), tools(w, turn=None)):
                assert CHANGE in await offered(t) and CONFIRM not in await offered(t)
            specs = {s.name: s for s in (await tools(w).catalogue()).specs}
            assert specs[CHANGE].reads is False
            assert {"op", "kind"} <= set(json.loads(json.dumps(specs[CHANGE].parameters))["required"])
            assert (await tools(w).catalogue()).instructions
    run(go())


@pytest.mark.parametrize("op,kind,arguments,expected", UNCOVERED)
def test_what_she_changes_on_her_own_is_done_at_once_and_nothing_is_proposed(
        db_url: str, op: str, kind: str, arguments: dict[str, Any], expected: tuple[str, tuple[object, ...]]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await change(tools(w), op, kind, **arguments)
            assert not got.is_error and got.call_id == "c1"
            assert w.house.calls == [expected]
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
    run(go())


@pytest.mark.parametrize("op,kind,arguments,asked", COVERED)
def test_what_is_covered_is_proposed_and_never_carried_out_in_the_turn_it_is_asked(
        db_url: str, op: str, kind: str, arguments: dict[str, Any], asked: Change) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await change(tools(w, turn=7), op, kind, **arguments)
            assert not got.is_error and got.content
            assert w.house.calls == []
            kept = await w.proposals.pending(w.alana, CONVERSATION, HOUSE)
            assert kept is not None and kept.payload.change == asked
            assert (kept.household_id, kept.made_by, kept.conversation_id, kept.turn_id) == (w.home, w.alana, CONVERSATION, 7)
            assert kept.payload.summary.strip()
    run(go())


def test_a_summary_and_the_log_say_what_would_happen_and_never_the_changes_contents(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=3), "perform", "action", id="recorder.purge", data={"note": "marker-data-9034"})
            kept = await w.proposals.pending(w.alana, CONVERSATION, HOUSE)
            assert kept is not None and "marker-data-9034" not in kept.payload.summary
            await change(tools(w, turn=4), "write", "automation", id="marker-id-9034",
                         data={"alias": "marker-alias-9034", "description": "marker-description-9034", "triggers": [], "actions": []})
            await change(tools(w, turn=5), "delete", "automation", id="marker-id-9035")
            await say(tools(w, turn=6), CONFIRM)
            await say(tools(w, turn=8), CONFIRM)
    run(go())
    lines = [f"{r.name} {r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("ashley")]
    assert any("house_change" in line for line in lines), "no line was logged for the calls, so the probe could see nothing"
    for secret in ("marker-data-9034", "marker-id-9034", "marker-id-9035", "marker-alias-9034", "marker-description-9034"):
        assert not any(secret in line for line in lines), secret


def test_she_cannot_confirm_in_the_turn_she_proposed_or_an_earlier_one_and_the_proposal_stays(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="kitchen")
            for turn in (5, 4, 1):
                t = tools(w, turn=turn)
                assert CONFIRM not in await offered(t)
                got = await say(t, CONFIRM)
                assert got.is_error
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is not None
    run(go())


def test_in_a_later_turn_she_is_offered_house_confirm_and_it_carries_out_what_was_proposed_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="kitchen")
            later = tools(w, turn=6)
            assert CONFIRM in await offered(later) and CHANGE in await offered(later)
            specs = {s.name: s for s in (await later.catalogue()).specs}
            assert specs[CONFIRM].reads is False
            got = await say(later, CONFIRM)
            assert not got.is_error
            assert w.house.calls == [("delete_record", ("area", "kitchen"))]
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
            again = await say(tools(w, turn=7), CONFIRM)
            assert again.is_error and w.house.calls == [("delete_record", ("area", "kitchen"))]
            assert CONFIRM not in await offered(tools(w, turn=7))
    run(go())


def test_house_confirm_does_what_was_proposed_and_nothing_else_whatever_it_is_given(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "automation", id="porch")
            got = await say(tools(w, turn=6), CONFIRM, op="delete", kind="area", id="everything", data="{}", ids=["light.x"])
            assert not got.is_error
            assert w.house.calls == [("delete_config", ("automation", "porch"))]
    run(go())


def test_a_confirmed_action_runs_with_the_data_and_things_it_was_proposed_with(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "perform", "action", id="backup.create", data={"name": "before-update"})
            await say(tools(w, turn=6), CONFIRM)
            assert w.house.calls == [("perform", ("backup.create", (), {"name": "before-update"}))]
    run(go())


def test_only_the_person_who_proposed_it_in_its_conversation_can_take_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="kitchen")
            for who, conversation in ((w.sam, CONVERSATION), (w.alana, CONVERSATION + 1), (w.sam, CONVERSATION + 1)):
                other = tools(w, who=who, turn=9, conversation=conversation)
                assert CONFIRM not in await offered(other)
                assert (await say(other, CONFIRM)).is_error
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is not None
            assert not (await say(tools(w, turn=6), CONFIRM)).is_error
            assert w.house.calls == [("delete_record", ("area", "kitchen"))]
    run(go())


def test_a_proposal_past_its_limit_is_not_offered_or_carried_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(Proposal(w.home, w.alana, CONVERSATION, 5, datetime.now(UTC),
                                               HouseChange(Change("delete", "area", "kitchen"), "s")), 86400.0)
            assert scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = created_at - interval '2 hours' RETURNING 1) "
                                  "SELECT count(*) FROM u") == 1
            late = tools(w, turn=6, ttl_s=ONE_HOUR)
            assert CONFIRM not in await offered(late)
            assert (await say(late, CONFIRM)).is_error
            assert w.house.calls == []
            fresh = tools(w, turn=6, ttl_s=3 * ONE_HOUR)
            assert not (await say(fresh, CONFIRM)).is_error
            assert w.house.calls == [("delete_record", ("area", "kitchen"))]
    run(go())


def test_a_newer_proposal_replaces_the_older_and_only_it_is_carried_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="old-area")
            await change(tools(w, turn=6), "delete", "label", id="new-label")
            await say(tools(w, turn=7), CONFIRM)
            assert w.house.calls == [("delete_record", ("label", "new-label"))]
            assert (await say(tools(w, turn=8), CONFIRM)).is_error
            assert w.house.calls == [("delete_record", ("label", "new-label"))]
    run(go())


def test_a_proposal_is_not_replaced_by_one_in_another_conversation(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="here")
            await change(tools(w, turn=2, conversation=CONVERSATION + 1), "delete", "area", id="there")
            await say(tools(w, turn=6), CONFIRM)
            assert w.house.calls == [("delete_record", ("area", "here"))]
    run(go())


def test_where_the_reply_may_be_heard_by_others_nothing_is_proposed_or_confirmed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            shared = tools(w, turn=5, private=False)
            got = await change(shared, "delete", "area", id="kitchen")
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
            assert got.is_error or "kitchen" not in got.content
            await change(tools(w, turn=5), "delete", "area", id="kitchen")
            heard = tools(w, turn=6, private=False)
            assert CONFIRM not in await offered(heard)
            assert (await say(heard, CONFIRM)).is_error
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is not None
    run(go())


def test_with_no_turn_to_answer_she_can_propose_nothing_and_a_covered_change_is_not_made(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=None), "delete", "area", id="kitchen")
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
    run(go())


def test_a_call_that_cannot_be_made_is_an_error_result_and_changes_nothing_never_an_exception(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            t = tools(w)
            bad: list[ToolResult] = [
                await say(t, "house_nothing"),
                await say(t, CHANGE, op="nuke", kind="area"),
                await say(t, CHANGE, op="write", kind="area", data="{}", id="x"),
                await say(t, CHANGE, op="write", kind="automation", id="a", data="not json"),
                await say(t, CHANGE, op="write", kind="automation", id="a", data="[1, 2]"),
                await say(t, CHANGE),
            ]
            assert all(r.is_error and r.call_id == "c1" for r in bad), [r.content for r in bad]
            assert w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
    run(go())


def test_no_house_is_an_error_result_and_the_houses_failures_are_too(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            w.homes.homes.clear()
            assert (await change(tools(w), "write", "script", id="s", data={"alias": "x"})).is_error
            assert (await change(tools(w), "delete", "area", id="kitchen")).is_error or w.house.calls == []
        async with world(db_url, RecordingHouse(down=True)) as w:
            got = await change(tools(w), "write", "script", id="s", data={"alias": "x"})
            assert got.is_error
        async with world(db_url, RecordingHouse(refuse=True)) as w:
            got = await change(tools(w), "write", "script", id="s", data={"alias": "x"})
            assert got.is_error and "refused" not in got.call_id
    run(go())


def test_a_confirmed_change_the_house_refuses_or_cannot_reach_is_an_error_result(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await change(tools(w, turn=5), "delete", "area", id="kitchen")
            w.house.refuse = True
            assert (await say(tools(w, turn=6), CONFIRM)).is_error
            w.house.refuse, w.house.down = False, True
            assert (await say(tools(w, turn=6), CONFIRM)).is_error
            assert w.house.calls == []
    run(go())


def test_deleting_what_is_not_there_is_an_error_when_confirmed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, RecordingHouse(there=False)) as w:
            await change(tools(w, turn=5), "delete", "automation", id="gone")
            assert (await say(tools(w, turn=6), CONFIRM)).is_error
    run(go())


PORCHES = (State("light.porch", "Porch light", "off", "light", None, {}, None, (), (), True),
           State("light.porch_lamp", "Porch lamp", "off", "light", None, {}, None, (), (), True),
           State("light.attic", "Attic light", "on", "light", None, {}, None, (), (), True))


def test_an_everyday_action_is_not_for_house_change_it_is_house_dos_and_nothing_is_done_or_proposed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, RecordingHouse(PORCHES)) as w:
            got = await change(tools(w), "perform", "action", id="light.turn_on", ids=["light.attic"])
            assert got.is_error and w.house.calls == []
            assert await w.proposals.pending(w.alana, CONVERSATION, HOUSE) is None
    run(go())


def test_a_covered_action_names_its_things_by_name_in_code_and_a_name_that_fits_several_or_none_proposes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, RecordingHouse(PORCHES)) as w:
            assert not (await change(tools(w, turn=3), "perform", "action", id="recorder.purge_entities", name="attic")).is_error
            kept = await w.proposals.pending(w.alana, CONVERSATION, HOUSE)
            assert kept is not None and kept.payload.change.ids == ("light.attic",)
            for arguments in ({"name": "porch"}, {"name": "garage"}, {"ids": ["light.nowhere"]}):
                got = await change(tools(w, turn=4), "perform", "action", id="recorder.purge_entities", **arguments)
                assert got.is_error, arguments
            again = await w.proposals.pending(w.alana, CONVERSATION, HOUSE)
            assert again is not None and again.turn_id == 3 and again.payload.change.ids == ("light.attic",)
            assert w.house.calls == []
    run(go())
