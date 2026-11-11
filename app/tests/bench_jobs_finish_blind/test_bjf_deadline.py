"""The deadline collects what `out/` holds: `deadline` with a `RESULT.md`, `no_result` without."""

import pytest

from bench_jobs_finish_blind_support import NO_RESULT, begun
from bjb_support import World, expire, scenario
from ashley.herdr.model import Status

STATES: list[Status] = ["working", "idle", "done"]


def test_deadline_the_reason_slug_is_no_result() -> None:
    assert NO_RESULT == "no_result"


def test_deadline_with_result_md_is_timed_out_deadline_with_its_summary(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"RESULT.md": b"partial summary", "a.txt": b"made\n"})
        expire(w.url, r.job_id)
        got = await r.tick(1)
        assert got is not None and (got.state, got.reason) == ("timed_out", "deadline")
        assert got.summary == "partial summary" and len(got.outputs) == 1

    scenario(db_url, body)


@pytest.mark.parametrize("status", STATES)
def test_deadline_without_result_md_is_timed_out_no_result(db_url: str, status: Status) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"a.txt": b"made\n"})
        if status != "working":
            r.settle(status)
        expire(w.url, r.job_id)
        got = await r.tick(1)
        assert got is not None and (got.state, got.reason) == ("timed_out", NO_RESULT)
        assert len(got.outputs) == 1, "what out/ holds is still collected"

    scenario(db_url, body)


def test_deadline_with_nothing_in_out_is_timed_out_no_result_with_no_outputs(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        expire(w.url, r.job_id)
        got = await r.tick(1)
        assert got is not None and (got.state, got.reason, got.outputs) == ("timed_out", NO_RESULT, ())

    scenario(db_url, body)


def test_deadline_after_a_nudge_without_result_is_still_no_result(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        await r.tick(1)
        await r.tick(1 + 400)
        assert len(r.nudges) == 1
        expire(w.url, r.job_id)
        got = await r.tick(2 + 400)
        assert got is not None and (got.state, got.reason) == ("timed_out", NO_RESULT)

    scenario(db_url, body)


def test_deadline_not_reached_collects_nothing_early(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"a.txt": b"made\n"})
        assert await r.tick(1) is None and r.state == "running"

    scenario(db_url, body)
