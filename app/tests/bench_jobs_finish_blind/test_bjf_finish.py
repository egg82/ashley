"""The finish rule: `done` only when the session has stopped and `out/RESULT.md` exists."""

import pytest

from bench_jobs_finish_blind_support import begun
from bjb_support import World, scenario
from ashley.herdr.model import Status


@pytest.mark.parametrize("status", ["idle", "done"])
def test_finish_a_stopped_session_with_result_md_is_done_with_the_summary_from_it(db_url: str, status: Status) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"RESULT.md": b"what I did"})
        r.settle(status)
        got = await r.tick(1)
        assert got is not None and got.state == "done" and got.reason is None and got.summary == "what I did"

    scenario(db_url, body)


def test_finish_other_files_in_out_become_outputs_and_result_md_is_not_one(db_url: str) -> None:
    async def body(w: World) -> None:
        before = set(await w.pieces())
        r = await begun(w)
        r.write({"RESULT.md": b"summary", "a.txt": b"alpha\n", "b.txt": b"beta\n"})
        r.settle("idle")
        got = await r.tick(1)
        assert got is not None and got.state == "done" and len(got.outputs) == 2
        assert set(got.outputs) == set(await w.pieces()) - before

    scenario(db_url, body)


@pytest.mark.parametrize("status", ["idle", "done"])
def test_finish_a_stopped_session_without_result_md_leaves_the_job_running_and_the_session_open(
        db_url: str, status: Status) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"a.txt": b"made\n"})
        r.settle(status)
        assert await r.tick(1) is None
        assert r.state == "running" and w.bridge.closed == [] and r.sid in w.bridge.sessions_

    scenario(db_url, body)


def test_finish_a_working_session_with_result_md_is_not_done_until_it_stops(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"RESULT.md": b"early"})
        assert await r.tick(1) is None and r.state == "running"
        r.settle("idle")
        got = await r.tick(2)
        assert got is not None and got.state == "done" and got.summary == "early"

    scenario(db_url, body)


def test_finish_result_md_written_after_the_session_stopped_finishes_the_job_on_the_next_tick(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.settle("idle")
        assert await r.tick(1) is None
        r.write({"RESULT.md": b"late"})
        got = await r.tick(2)
        assert got is not None and got.state == "done" and got.summary == "late"

    scenario(db_url, body)


def test_finish_a_stopped_session_with_result_md_is_not_nudged(db_url: str) -> None:
    async def body(w: World) -> None:
        r = await begun(w)
        r.write({"RESULT.md": b"x"})
        r.settle("idle")
        await r.tick(1)
        assert r.nudges == []

    scenario(db_url, body)


