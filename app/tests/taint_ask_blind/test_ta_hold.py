"""A tainted turn's changes become one stored set of calls in the proposals store, per person: what is stored, how calls
accumulate, the limits, where agreement can follow, and which tools are refused rather than held."""

import pytest
from ashley.inference.model import ToolResult
from taint_ask_blind_support import (CONFIRM, DO, MAX_CALLS, MAX_CHARS, PROMPT, READ_HOME, SORT, Source, World, at_info,
                                     events, scenario)

NESTED = {"op": "write", "data": {"alias": "porch", "triggers": [{"at": "07:00"}, {"at": "19:30"}]}, "ids": ["a", "b"]}


def test_a_held_change_is_not_run_and_the_result_is_not_the_tools(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        got = await w.call(o, DO, {"x": 1})
        assert src.reached() == [] and got.call_id == "c1" and got.content != "house_do done"

    scenario(db_url, body)


def test_the_stored_arguments_are_exactly_the_ones_asked_for(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="stranger"))
        await w.call(o, DO, NESTED)
        assert await w.held() == [(DO, NESTED)]

    scenario(db_url, body)


def test_the_proposal_is_the_speakers_in_the_turn_being_answered(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        o = w.wrap(Source(), w.inbound(taint="watch"), turn=turn)
        await w.call(o, DO)
        got = await w.pending()
        assert got is not None and (got.made_by, got.turn_id, got.conversation_id, got.household_id) == (
            w.alana, turn, w.chat, w.hid)

    scenario(db_url, body)


def test_calls_of_a_turn_accumulate_in_one_proposal_in_the_order_asked(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        for n, name in enumerate((PROMPT, DO, SORT)):
            await w.call(o, name, {"n": n})
        assert await w.held() == [(PROMPT, {"n": 0}), (DO, {"n": 1}), (SORT, {"n": 2})]
        assert w.proposal_rows() == 1

    scenario(db_url, body)


def test_a_call_identical_to_one_held_is_not_added_twice(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"a": 1, "b": 2})
        await w.call(o, DO, {"b": 2, "a": 1})
        assert await w.held() == [(DO, {"a": 1, "b": 2})]

    scenario(db_url, body)


def test_the_same_tool_with_other_arguments_is_another_call(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"a": 1})
        await w.call(o, DO, {"a": 2})
        assert await w.held() == [(DO, {"a": 1}), (DO, {"a": 2})]

    scenario(db_url, body)


def test_the_same_arguments_to_another_tool_is_another_call(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"a": 1})
        await w.call(o, SORT, {"a": 1})
        assert len(await w.held()) == 2

    scenario(db_url, body)


def test_a_turn_resumed_after_a_kill_does_not_double_a_call_it_asks_again(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        first = w.wrap(Source(), w.inbound(taint="watch"), turn=turn)
        await w.call(first, DO, {"a": 1})
        again = w.wrap(Source(), w.inbound(taint="watch"), turn=turn)
        await w.call(again, DO, {"a": 1})
        await w.call(again, PROMPT, {"b": 2})
        assert await w.held() == [(DO, {"a": 1}), (PROMPT, {"b": 2})]

    scenario(db_url, body)


def test_calls_up_to_max_calls_are_held_and_the_next_is_refused_unstored(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        for n in range(MAX_CALLS):
            await w.call(o, DO, {"n": n})
        over = await w.call(o, DO, {"n": MAX_CALLS})
        assert over.is_error and src.reached() == []
        assert [a["n"] for _, a in await w.held()] == list(range(MAX_CALLS))

    scenario(db_url, body)


def test_a_call_with_arguments_too_long_to_read_is_refused_and_not_held(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        got = await w.call(o, DO, {"text": "y" * (MAX_CHARS * 2)})
        assert got.is_error and src.reached() == [] and await w.pending() is None

    scenario(db_url, body)


def test_a_refused_long_call_leaves_the_calls_already_held(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"n": 1})
        await w.call(o, DO, {"text": "y" * (MAX_CHARS * 2)})
        assert await w.held() == [(DO, {"n": 1})]

    scenario(db_url, body)


def test_a_later_tainted_turns_first_call_replaces_the_earlier_pending_proposal(db_url: str) -> None:
    async def body(w: World) -> None:
        old = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(old, DO, {"n": 1})
        await w.call(old, PROMPT, {"n": 2})
        new = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(new, SORT, {"n": 3})
        assert await w.held() == [(SORT, {"n": 3})] and w.proposal_rows() == 1

    scenario(db_url, body)


def test_one_person_pending_set_per_person(db_url: str) -> None:
    async def body(w: World) -> None:
        a = w.wrap(Source(), w.inbound(taint="watch"))
        s = w.wrap(Source(), w.inbound(who=w.sam, taint="watch"), conv=w.sam_chat)
        await w.call(a, DO, {"who": "alana"})
        await w.call(s, DO, {"who": "sam"})
        assert await w.held() == [(DO, {"who": "alana"})]
        assert await w.held(w.sam, w.sam_chat) == [(DO, {"who": "sam"})]

    scenario(db_url, body)


def test_the_pending_set_is_found_from_another_conversation_of_the_same_person(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"), conv=w.chat)
        await w.call(o, DO, {"n": 1})
        got = await w.pending(w.alana, w.other_chat)
        assert got is not None and got.conversation_id == w.chat
        assert await w.pending(w.sam, w.other_chat) is None

    scenario(db_url, body)


@pytest.mark.parametrize("which", ["shared_room", "device", "household_channel", "unknown_speaker"])
def test_where_the_reply_does_not_reach_the_person_alone_the_change_is_refused_not_held(db_url: str, which: str) -> None:
    async def body(w: World) -> None:
        shapes = {"shared_room": w.inbound(taint="watch", audience="present", shared=True),
                  "device": w.inbound(taint="watch", device_id=4),
                  "household_channel": w.inbound(taint="stranger", audience="household", shared=True),
                  "unknown_speaker": w.inbound(taint="watch", speaker=False)}
        src = Source()
        o = w.wrap(src, shapes[which])
        got = await w.call(o, DO, {"n": 1})
        assert got.is_error and src.reached() == [] and w.proposal_rows() == 0

    scenario(db_url, body)


def test_a_tool_that_takes_agreement_is_refused_in_a_tainted_turn_and_never_held(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        got = await w.call(o, CONFIRM)
        assert got.is_error and src.reached() == [] and w.proposal_rows() == 0

    scenario(db_url, body)


def test_a_tool_that_takes_agreement_is_refused_after_a_read_taints_the_turn(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, "web_read")
        got = await w.call(o, CONFIRM)
        assert got.is_error and src.reached(CONFIRM) == [] and w.proposal_rows() == 0

    scenario(db_url, body)


def test_a_tool_that_takes_agreement_runs_in_an_untainted_turn(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        got = await w.call(o, CONFIRM)
        assert not got.is_error and len(src.reached(CONFIRM)) == 1

    scenario(db_url, body)


def test_the_refusals_are_logged_with_their_reasons_and_no_arguments(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(w: World) -> None:
        at_info(caplog)
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, CONFIRM)
        await w.call(o, DO, {"text": "PLANTED-" + "y" * (MAX_CHARS * 2)})
        for n in range(MAX_CALLS + 1):
            await w.call(o, DO, {"n": n})
        shared = w.wrap(Source(), w.inbound(taint="watch", device_id=3))
        await w.call(shared, DO, {"n": 99})
        reasons = {str(e["reason"]) for e in events(caplog, "outside.refused")}
        assert reasons == {"agreeing_tainted", "too_long", "too_many", "needs_private"}
        assert "PLANTED-" not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)


def test_each_held_call_is_logged_with_the_count_so_far(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(w: World) -> None:
        at_info(caplog)
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"v": "PLANTED-held-argument"})
        await w.call(o, PROMPT, {"v": "two"})
        got = events(caplog, "outside.held")
        assert [e["tool"] for e in got] == [DO, PROMPT] and [int(str(e["calls"])) for e in got] == [1, 2]
        assert "PLANTED-held-argument" not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)


def test_a_read_never_stores_anything(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        got = await w.call(o, READ_HOME)
        assert isinstance(got, ToolResult) and not got.is_error and w.proposal_rows() == 0

    scenario(db_url, body)
