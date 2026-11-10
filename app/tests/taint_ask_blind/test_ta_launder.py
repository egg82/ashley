"""Agreement cannot be laundered: `carry_out` is refused in any tainted turn, by origin, by a read or by a resume; it
runs only what was stored and shown; it never agrees to a set a tainted turn has just made."""

import pytest
from taint_ask_blind_support import (CARRY_OUT, DO, PROMPT, READ_OUTSIDE, SORT, Source, World, at_info, events,
                                     hold_two, offers_carry_out, scenario)


@pytest.mark.parametrize("origin", ["watch", "stranger"])
def test_it_is_not_offered_to_a_turn_tainted_by_its_origin(db_url: str, origin: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert not await offers_carry_out(w.wrap(Source(), w.inbound(taint=origin)))

    scenario(db_url, body)


@pytest.mark.parametrize("origin", ["watch", "stranger"])
def test_calling_it_in_an_origin_tainted_turn_runs_nothing_and_keeps_the_proposal(db_url: str, origin: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        src = Source()
        got = await w.call(w.wrap(src, w.inbound(taint=origin)), CARRY_OUT)
        assert got.is_error and src.reached() == []
        assert await w.held() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)


def test_a_read_that_taints_withdraws_the_offer(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        o = w.wrap(Source())
        assert await offers_carry_out(o)
        await w.call(o, READ_OUTSIDE)
        assert not await offers_carry_out(o)

    scenario(db_url, body)


def test_calling_it_after_a_taint_runs_nothing_and_keeps_the_proposal(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        src = Source()
        o = w.wrap(src)
        await w.call(o, READ_OUTSIDE)
        src.calls.clear()
        got = await w.call(o, CARRY_OUT)
        assert got.is_error and src.reached() == []
        assert await w.held() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)


def test_a_resumed_tainted_turn_is_not_offered_it(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        assert not await offers_carry_out(w.wrap(Source(), tainted=READ_OUTSIDE))

    scenario(db_url, body)


def test_the_proposal_a_tainted_turn_refused_can_still_be_carried_out_by_a_clean_one(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        await w.call(w.wrap(Source(), w.inbound(taint="watch")), CARRY_OUT)
        src = Source()
        await w.call(w.wrap(src), CARRY_OUT)
        assert src.ran() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)


def test_the_refusal_is_logged_as_agreeing_while_tainted(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(w: World) -> None:
        at_info(caplog)
        await hold_two(w)
        await w.call(w.wrap(Source(), w.inbound(taint="stranger")), CARRY_OUT)
        assert [e["reason"] for e in events(caplog, "outside.refused")] == ["agreeing_tainted"]

    scenario(db_url, body)


def test_a_tainted_turn_cannot_hold_carry_out_as_one_of_its_calls(db_url: str) -> None:
    async def body(w: World) -> None:
        _, first, second = await hold_two(w)
        await w.call(w.wrap(Source(), w.inbound(taint="watch")), CARRY_OUT)
        assert [t for t, _ in await w.held()] == [DO, PROMPT] and await w.held() == [(DO, first), (PROMPT, second)]

    scenario(db_url, body)


def test_a_new_tainted_turn_replaces_the_set_so_agreeing_runs_only_what_was_last_shown(db_url: str) -> None:
    async def body(w: World) -> None:
        await hold_two(w)
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, SORT, {"label": "newest"})
        src = Source()
        await w.call(w.wrap(src), CARRY_OUT)
        assert src.ran() == [(SORT, {"label": "newest"})]

    scenario(db_url, body)


def test_a_clean_turn_cannot_agree_to_a_set_made_in_its_own_turn(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), w.inbound(taint="watch"))
        await w.call(o, DO, {"n": 1})
        pending = await w.pending()
        assert pending is not None
        src = Source()
        same = w.wrap(src, turn=pending.turn_id)
        got = await w.call(same, CARRY_OUT)
        assert got.is_error and src.reached() == [] and await w.pending() is not None

    scenario(db_url, body)
