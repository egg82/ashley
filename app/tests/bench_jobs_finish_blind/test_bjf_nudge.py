"""The nudge: one prompt after `idle_nudge_s` idle without `RESULT.md`, never earlier, never twice."""

import pytest

from bench_jobs_finish_blind_support import NUDGE, begun, config
from bjb_support import World, cfg, scenario
from ashley.herdr.model import Reason

WAIT = cfg().idle_nudge_s


def test_nudge_not_sent_before_idle_nudge_s(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        for at in (1, WAIT / 2, WAIT - 1):
            assert await r.tick(at) is None
        assert r.nudges == [] and r.state == "running"

    scenario(db_url, body)


def test_nudge_sent_once_when_idle_for_idle_nudge_s(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        assert await r.tick(1 + WAIT) is None
        assert r.nudges == [NUDGE] and r.state == "running" and w.bridge.closed == []

    scenario(db_url, body)


def test_nudge_clock_starts_when_idle_is_first_seen_not_when_the_job_began(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(10 * WAIT)
        await r.tick(10 * WAIT + 1)
        assert r.nudges == []
        await r.tick(11 * WAIT)
        assert r.nudges == [NUDGE]

    scenario(db_url, body)


def test_nudge_never_sent_twice_across_ticks_each_reading_the_job_from_the_store(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        await r.tick(1 + WAIT)
        r.settle("idle")  # the nudged session stops again, still without a result
        for k in range(2, 8):
            assert await r.tick(1 + k * WAIT) is None
        assert r.nudges == [NUDGE] and r.state == "running"

    scenario(db_url, body)


def test_nudge_is_not_repeated_while_the_session_stays_idle_after_it(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        await r.tick(1 + WAIT)
        for k in range(1, 5):
            await r.tick(1 + WAIT + k * WAIT)
        assert len(r.nudges) == 1

    scenario(db_url, body)


@pytest.mark.parametrize("why", ["busy", "person_typing", "unknown_state"])
def test_nudge_a_transient_refusal_is_tried_again_on_a_later_tick(db_url: str, why: Reason) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        w.bridge.fail["prompt"] = why
        assert await r.tick(1 + WAIT) is None and r.state == "running"
        assert r.nudges == []
        del w.bridge.fail["prompt"]
        assert await r.tick(2 + WAIT) is None
        assert r.nudges == [NUDGE]
        r.settle("idle")
        await r.tick(3 + WAIT)
        await r.tick(3 + 3 * WAIT)
        assert r.nudges == [NUDGE]

    scenario(db_url, body)


def test_nudge_a_refused_nudge_is_retried_every_tick_until_it_lands(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        w.bridge.fail["prompt"] = "busy"
        for k in range(3):
            await r.tick(1 + WAIT + k)
        assert len(w.bridge.named("prompt")) == 1 + 3 and r.nudges == []

    scenario(db_url, body)


def test_nudge_idle_clock_restarts_when_the_session_works_again(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        r.settle("working")
        assert await r.tick(WAIT - 10) is None
        r.settle("idle")
        await r.tick(WAIT - 5)
        await r.tick(WAIT + 5)  # past the first idle's mark, only 10s into the second
        await r.tick(2 * WAIT - 6)
        assert r.nudges == []
        await r.tick(2 * WAIT - 5)
        assert r.nudges == [NUDGE]

    scenario(db_url, body)


def test_nudge_time_comes_from_the_configured_idle_nudge_s(db_url: str) -> None:
    async def body(w: World) -> None:
        short = config(idle_nudge_s=30.0)
        r = await begun(w)
        r.settle("idle")
        await r.tick(1, short)
        await r.tick(30, short)
        assert r.nudges == []
        await r.tick(31, short)
        assert r.nudges == [NUDGE]

    scenario(db_url, body)


def test_nudge_then_a_result_finishes_the_job_done(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        await r.tick(1 + WAIT)
        r.write({"RESULT.md": b"after the nudge"})
        r.settle("idle")
        got = await r.tick(2 + WAIT)
        assert got is not None and got.state == "done" and got.summary == "after the nudge"
        assert len(r.nudges) == 1

    scenario(db_url, body)


def test_nudge_a_session_that_works_through_the_whole_wait_is_never_nudged(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        for k in range(1, 6):
            assert await r.tick(k * WAIT) is None
        assert r.nudges == []

    scenario(db_url, body)


def test_nudge_text_names_the_result_file() -> None:
    assert "RESULT.md" in NUDGE and "./out" in NUDGE
