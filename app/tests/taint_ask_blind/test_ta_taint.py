"""What taints a turn: its origin, the tool result it has read (the result's own `outside`, else its spec's), a name
the catalogue lacks; and that a taint is recorded before the result returns, never clears, and holds from a resume."""

import pytest
from taint_ask_blind_support import (DO, READ_DEFAULT, READ_HOME, READ_OUTSIDE, UNKNOWN, RecordingSteps, Source,
                                     World, at_info, events, scenario)

ARGS = {"entity": "light.porch"}


def test_a_read_whose_spec_is_outside_taints_and_the_next_change_is_held(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, READ_OUTSIDE, {"q": "x"})
        got = await w.call(o, DO, ARGS)
        assert src.reached(DO) == []
        assert got.content != "house_do done"
        assert await w.held() == [(DO, ARGS)]
        assert o.tainted == READ_OUTSIDE

    scenario(db_url, body)


def test_a_result_that_says_outside_false_does_not_taint_though_its_spec_is_outside(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        src.answers[READ_OUTSIDE] = ("a page of the household's own", False)
        o = w.wrap(src)
        await w.call(o, READ_OUTSIDE)
        await w.call(o, DO, ARGS)
        assert [c.name for c in src.reached(DO)] == [DO]
        assert o.tainted is None and await w.pending() is None

    scenario(db_url, body)


def test_a_result_that_says_outside_true_taints_though_its_spec_is_not(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        src.answers[READ_HOME] = ("a calendar event from a stranger", True)
        o = w.wrap(src)
        await w.call(o, READ_HOME)
        await w.call(o, DO, ARGS)
        assert src.reached(DO) == [] and await w.held() == [(DO, ARGS)]
        assert o.tainted == READ_HOME

    scenario(db_url, body)


def test_a_result_with_no_opinion_and_a_spec_that_is_not_outside_does_not_taint(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, READ_HOME)
        await w.call(o, DO, ARGS)
        assert len(src.reached(DO)) == 1 and o.tainted is None

    scenario(db_url, body)


def test_a_tool_whose_spec_says_nothing_about_outside_taints_by_default(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, READ_DEFAULT)
        await w.call(o, DO, ARGS)
        assert src.reached(DO) == [] and o.tainted == READ_DEFAULT

    scenario(db_url, body)


def test_an_unknown_name_taints_the_turn_it_is_called_in(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, UNKNOWN)
        await w.call(o, DO, ARGS)
        assert src.reached(DO) == [] and await w.held() == [(DO, ARGS)]

    scenario(db_url, body)


def test_an_unknown_name_in_a_tainted_turn_is_a_change_and_is_held(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        await w.call(o, UNKNOWN, {"a": 1})
        assert src.reached() == [] and await w.held() == [(UNKNOWN, {"a": 1})]

    scenario(db_url, body)


@pytest.mark.parametrize("origin", ["watch", "stranger"])
def test_an_origin_taint_holds_the_first_change_with_no_read_at_all(db_url: str, origin: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint=origin))
        await w.call(o, DO, ARGS)
        assert src.reached() == [] and await w.held() == [(DO, ARGS)]

    scenario(db_url, body)


def test_an_untainted_turn_runs_every_call_and_stores_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        got = await w.call(o, DO, {"op": "delete", "kind": "automation", "id": "porch"})
        assert got.content == "house_do done" and src.ran() == [(DO, {"op": "delete", "kind": "automation", "id": "porch"})]
        assert w.proposal_rows() == 0

    scenario(db_url, body)


def test_a_change_made_before_the_taint_runs_and_only_the_one_after_is_held(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, DO, {"n": 1})
        await w.call(o, READ_OUTSIDE)
        await w.call(o, DO, {"n": 2})
        assert src.ran() == [(DO, {"n": 1}), (READ_OUTSIDE, {})]
        assert await w.held() == [(DO, {"n": 2})]

    scenario(db_url, body)


def test_reads_in_a_tainted_turn_reach_the_tool_and_return_its_answer(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, w.inbound(taint="watch"))
        got = await w.call(o, READ_HOME, {"q": "porch"})
        assert src.ran() == [(READ_HOME, {"q": "porch"})] and got.content == f"{READ_HOME} done"
        assert w.proposal_rows() == 0

    scenario(db_url, body)


def test_a_taint_never_clears_a_later_clean_read_leaves_the_turn_tainted(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src)
        await w.call(o, READ_OUTSIDE)
        await w.call(o, READ_HOME)
        await w.call(o, DO, ARGS)
        assert src.reached(DO) == [] and o.tainted == READ_OUTSIDE

    scenario(db_url, body)


def test_the_taint_names_the_first_tool_that_tainted(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source())
        await w.call(o, READ_DEFAULT)
        await w.call(o, READ_OUTSIDE)
        assert o.tainted == READ_DEFAULT

    scenario(db_url, body)


def test_a_resumed_tainted_turn_holds_its_first_change(db_url: str) -> None:
    async def body(w: World) -> None:
        src = Source()
        o = w.wrap(src, tainted=READ_OUTSIDE)
        await w.call(o, DO, ARGS)
        assert src.reached() == [] and await w.held() == [(DO, ARGS)] and o.tainted == READ_OUTSIDE

    scenario(db_url, body)


def test_the_taint_is_recorded_once_with_the_tool_name_before_the_result_returns(db_url: str) -> None:
    async def body(w: World) -> None:
        steps = RecordingSteps()
        o = w.wrap(Source(), steps=steps)
        await w.call(o, READ_HOME)
        assert steps.tainted_by == []
        await w.call(o, READ_OUTSIDE)
        assert steps.tainted_by == [READ_OUTSIDE]
        await w.call(o, READ_DEFAULT)
        assert steps.tainted_by == [READ_OUTSIDE]

    scenario(db_url, body)


def test_a_runner_that_loses_the_turn_at_the_taint_raises_and_the_result_is_not_returned(db_url: str) -> None:
    async def body(w: World) -> None:
        o = w.wrap(Source(), steps=RecordingSteps(failing=True))
        with pytest.raises(RuntimeError):
            await w.call(o, READ_OUTSIDE)

    scenario(db_url, body)


def test_the_taint_is_logged_with_what_tainted_and_no_content(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(w: World) -> None:
        at_info(caplog)
        o = w.wrap(Source())
        await w.call(o, READ_OUTSIDE, {"q": "PLANTED-secret-query"})
        got = events(caplog, "outside.tainted")
        assert len(got) == 1 and got[0]["by"] == READ_OUTSIDE
        assert "PLANTED-secret-query" not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)
