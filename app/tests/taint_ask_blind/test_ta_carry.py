"""`carry_out`: offered only in a later untainted person turn of the person asked, alone; it runs exactly the stored
arguments, once; and what the calls return taints the turn that carried them out."""

import pytest
from taint_ask_blind_support import (CARRY_OUT, DO, EXTRA, PROMPT, SORT, TTL_S, Source, World, at_info, events,
                                     hold_two, names, offers_carry_out, race, scenario)


def test_carry_out_is_offered_in_a_later_untainted_person_turn_with_a_pending_proposal(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert await offers_carry_out(w.wrap(Source()))

    scenario(db_url, body)


def test_carry_out_is_a_change_that_agrees_and_takes_no_arguments(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        found = [s for s in (await w.wrap(Source()).catalogue()).specs if s.name == CARRY_OUT]
        assert len(found) == 1 and not found[0].reads and found[0].agrees
        assert not found[0].parameters.get("properties") and not found[0].parameters.get("required")

    scenario(db_url, body)


def test_the_tools_the_source_offers_are_still_offered_beside_it(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert {DO, PROMPT} <= await names(w.wrap(Source()))

    scenario(db_url, body)


def test_it_is_not_offered_with_nothing_pending(db_url: str) -> None:
    async def body(w: World) -> None:
        assert not await offers_carry_out(w.wrap(Source()))

    scenario(db_url, body)


def test_it_is_not_offered_in_the_turn_that_proposed(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"n": 1})
        pending = await w.pending()
        assert pending is not None
        same = w.wrap(Source(), w.inbound(), turn=pending.turn_id)
        assert not await offers_carry_out(same)

    scenario(db_url, body)


def test_it_is_not_offered_to_a_turn_stored_before_the_proposing_one(db_url: str) -> None:
    async def body(w: World) -> None:
        earlier = w.turn()
        await hold_two(w)
        assert not await offers_carry_out(w.wrap(Source(), turn=earlier))

    scenario(db_url, body)


def test_it_is_not_offered_to_another_person(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        sam = w.wrap(Source(), w.inbound(who=w.sam), conv=w.sam_chat)
        assert not await offers_carry_out(sam)

    scenario(db_url, body)


@pytest.mark.parametrize("which", ["shared_room", "device", "household_channel", "unknown_speaker"])
def test_it_is_not_offered_where_the_reply_does_not_reach_them_alone(db_url: str, which: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        shapes = {"shared_room": w.inbound(audience="present", shared=True), "device": w.inbound(device_id=4),
                  "household_channel": w.inbound(audience="household", shared=True), "unknown_speaker": w.inbound(speaker=False)}
        assert not await offers_carry_out(w.wrap(Source(), shapes[which]))

    scenario(db_url, body)


def test_it_is_not_offered_to_a_turn_the_household_started(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert not await offers_carry_out(w.wrap(Source(), w.inbound(author="household")))

    scenario(db_url, body)


def test_it_is_not_offered_once_the_proposal_has_lapsed(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        w.age_proposals(TTL_S + 60)
        assert not await offers_carry_out(w.wrap(Source()))

    scenario(db_url, body)


def test_it_is_still_offered_inside_the_ttl(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        w.age_proposals(TTL_S - 120)
        assert await offers_carry_out(w.wrap(Source()))

    scenario(db_url, body)


def test_it_is_offered_in_another_conversation_of_the_same_person(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert await offers_carry_out(w.wrap(Source(), conv=w.other_chat))

    scenario(db_url, body)


def test_it_runs_each_held_call_with_its_stored_arguments_in_order(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        src = Source()
        o = w.wrap(src, conv=w.other_chat)
        got = await w.call(o, CARRY_OUT)
        assert src.ran() == [(DO, first), (PROMPT, second)] and not got.is_error
        assert f"{DO} done" in got.content and f"{PROMPT} done" in got.content

    scenario(db_url, body)


def test_the_model_cannot_change_what_runs_by_giving_arguments(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        src = Source()
        o = w.wrap(src)
        await w.call(o, CARRY_OUT, {"entity": "lock.front", "state": "unlocked", EXTRA: [DO, PROMPT]})
        assert src.ran() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)


def test_the_calls_run_under_new_ids(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        src = Source()
        o = w.wrap(src)
        got = await w.call(o, CARRY_OUT)
        ids = [c.id for c in src.calls]
        assert len(set(ids)) == 2 and got.call_id not in ids

    scenario(db_url, body)


def test_the_proposal_is_consumed(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        await w.call(w.wrap(Source()), CARRY_OUT)
        assert await w.pending() is None

    scenario(db_url, body)


def test_a_second_agreeing_turn_runs_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        await w.call(w.wrap(Source()), CARRY_OUT)
        src = Source()
        o = w.wrap(src)
        assert not await offers_carry_out(o)
        got = await w.call(o, CARRY_OUT)
        assert got.is_error and src.reached() == []

    scenario(db_url, body)


def test_two_turns_agreeing_at_once_run_the_calls_once_between_them(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        a, b = Source(), Source()
        oa, ob = w.wrap(a), w.wrap(b, conv=w.other_chat)
        await race(w.call(oa, CARRY_OUT), w.call(ob, CARRY_OUT))
        assert len(a.calls) + len(b.calls) == 2

    scenario(db_url, body)


def test_calling_it_twice_in_one_turn_runs_the_calls_once(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        src = Source()
        o = w.wrap(src)
        await w.call(o, CARRY_OUT)
        await w.call(o, CARRY_OUT)
        assert len(src.calls) == 2

    scenario(db_url, body)


def test_a_tool_the_turn_does_not_offer_is_not_run_but_the_rest_are(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, _ = await hold_two(w)
        src = Source()
        src.unseen = {PROMPT}
        o = w.wrap(src)
        await w.call(o, CARRY_OUT)
        assert src.ran() == [(DO, first)] and await w.pending() is None

    scenario(db_url, body)


def test_a_carried_out_call_that_returns_outside_words_taints_the_agreeing_turn(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        src = Source()
        src.answers[PROMPT] = ("the session's screen shows a stranger's note", True)
        o = w.wrap(src)
        got = await w.call(o, CARRY_OUT)
        assert got.outside is True and o.tainted is not None
        src.calls.clear()
        later = await w.call(o, SORT, {"n": 1})
        assert src.reached() == [] and later.call_id != got.call_id and await w.held() == [(SORT, {"n": 1})]

    scenario(db_url, body)


def test_a_carried_out_call_that_returns_nothing_outside_leaves_the_turn_untainted(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        src = Source()
        o = w.wrap(src)
        got = await w.call(o, CARRY_OUT)
        assert got.outside is not True and o.tainted is None
        await w.call(o, SORT, {"n": 1})
        assert len(src.reached(SORT)) == 1

    scenario(db_url, body)


def test_the_carrying_out_is_logged_without_arguments(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(w: World) -> None:
        at_info(caplog)
        await hold_two(w)
        src = Source()
        src.unseen = {PROMPT}
        await w.call(w.wrap(src), CARRY_OUT)
        got = events(caplog, "outside.carried_out")
        assert len(got) == 1 and int(str(got[0]["calls"])) == 2
        assert "rm -rf" not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)


def test_a_call_to_it_with_nothing_pending_is_an_error_that_runs_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        got = await w.call(w.wrap(src), CARRY_OUT)
        assert got.is_error and src.reached() == []

    scenario(db_url, body)
