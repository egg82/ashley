"""Contracts 2, 4, 5 and 22 (with the tool's own argument rules): a hand-off that is refused records nothing and sends
nothing, whatever the reason; any invalid job of a group records none of them."""

from dataclasses import replace

import pytest
from bjb_support import (MARK_BODY, MARK_TITLE, World, cfg, job_count, limit, payload, reason, scenario, spec, watch_rows,
                         job_pieces)
from ashley import services
from ashley.workshop.workshop import Workshop


async def nothing_recorded(w: World, others: int = 0) -> None:
    assert job_count(w.url) == 0
    assert watch_rows(w.url) == []
    assert job_pieces(await w.pieces()) == []
    sent = [c[0] for c in w.bridge.calls if c[0] in ("start", "upload", "prompt", "close")]
    assert sent == []
    assert w.model.asked == []


# --- 2: claude_code needs a connection and a bridge that has files -------------------------------------------------


def test_c02_claude_code_without_a_herdr_connection_is_not_connected(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await w.hand_off(spec("claude_code"), can_code=True)
        assert reason(got) == "not_connected"
        await nothing_recorded(w)

    scenario(db_url, body, connected=False)


def test_c02_a_bridge_without_the_files_capability_is_bridge_too_old(db_url: str) -> None:
    async def body(w: World) -> None:
        w.bridge.files = False
        got = await w.hand_off(spec("claude_code"), can_code=True)
        assert reason(got) == "bridge_too_old"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c02_a_bridge_that_refuses_the_connection_is_bridge_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        w.bridge.fail["whoami"] = "bad_token"
        got = await w.hand_off(spec("claude_code"), can_code=True)
        assert reason(got) == "bridge_refused"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c02_a_bridge_with_null_roots_is_no_roots(db_url: str) -> None:
    async def body(w: World) -> None:
        w.bridge.roots = None
        got = await w.hand_off(spec("claude_code"), can_code=True)
        assert reason(got) == "no_roots"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c02_claude_code_is_refused_when_the_turn_did_not_offer_it(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await w.hand_off(spec("claude_code"), can_code=False)
        assert got.is_error
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c02_an_agent_job_needs_no_herdr_connection(db_url: str) -> None:
    async def body(w: World) -> None:
        assert not (await w.hand_off(spec("agent"))).is_error

    scenario(db_url, body, connected=False)


# --- 4: the pieces a job names --------------------------------------------------------------------------------------


def test_c04_an_unknown_piece_id_is_no_such_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await w.hand_off(spec(pieces=[9999]))
        assert reason(got) == "no_such_piece"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c04_a_shelved_piece_is_no_such_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        shelved = await w.piece("note", MARK_TITLE, MARK_BODY)
        await w.piece("note", "kept", "kept")
        await w.shelve(shelved)
        assert reason(await w.hand_off(spec(pieces=[shelved]))) == "no_such_piece"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c04_a_piece_of_another_bench_is_no_such_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        elsewhere = await w.piece("note", "other", "other", bench=w.other_bench)
        assert reason(await w.hand_off(spec(pieces=[elsewhere]))) == "no_such_piece"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c04_a_piece_of_another_persons_bench_is_no_such_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        theirs = await services.get(Workshop).read(w.mate, w.foreign_bench)
        assert theirs.pieces == ()
        sams = await _sams_piece(w)
        assert reason(await w.hand_off(spec(pieces=[sams]))) == "no_such_piece"
        await nothing_recorded(w)

    scenario(db_url, body)


async def _sams_piece(w: World) -> int:
    from ashley.workshop.commands import Add
    from ashley.workshop.model import By, Text
    got = await services.get(Workshop).apply(w.mate, w.foreign_bench, Add(By(w.mate.person_id), "note", Text("s", "s"), "small"))
    assert got.piece_id is not None
    return got.piece_id


def test_c04_a_hand_off_on_a_bench_that_is_not_the_speakers_names_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await w.hand_off(spec(), bench=w.foreign_bench)
        assert got.is_error
        await nothing_recorded(w)

    scenario(db_url, body)


# --- 5: sizes and concurrency ---------------------------------------------------------------------------------------


def test_c05_more_named_pieces_than_max_pieces_in_is_too_large(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.piece("note", f"n{i}", "x") for i in range(limit("max_pieces_in") + 1)]
        assert reason(await w.hand_off(spec(pieces=ids))) == "too_large"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c05_exactly_max_pieces_in_pieces_is_accepted(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.piece("note", f"n{i}", "x") for i in range(limit("max_pieces_in"))]
        assert not (await w.hand_off(spec(pieces=ids))).is_error

    scenario(db_url, body)


def test_c05_named_bytes_over_max_bytes_in_is_too_large(db_url: str) -> None:
    async def body(w: World) -> None:
        half = limit("max_bytes_in") // 2 + 1
        ids = [await w.huge_piece(half, "a.zip"), await w.huge_piece(half, "b.zip")]
        assert reason(await w.hand_off(spec(pieces=ids))) == "too_large"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c05_the_bytes_of_every_job_of_the_call_are_not_summed_across_jobs(db_url: str) -> None:
    async def body(w: World) -> None:
        half = limit("max_bytes_in") // 2 + 1
        a, b = await w.huge_piece(half, "a.zip"), await w.huge_piece(half, "b.zip")
        got = await w.hand_off(spec(title="one", pieces=[a]), spec(title="two", pieces=[b]))
        assert not got.is_error, got.content

    scenario(db_url, body)


async def _hand_off_one(w: World, worker: str = "agent", title: str = "j") -> None:
    got = await w.hand_off(spec(worker, title=title), can_code=True)
    assert not got.is_error, got.content


def test_c05_the_job_past_max_running_of_one_worker_for_one_person_is_too_many(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(limit("max_running", "agent")):
            await _hand_off_one(w, title=f"j{i}")
        before = job_count(w.url)
        assert reason(await w.hand_off(spec(title="over"))) == "too_many"
        assert job_count(w.url) == before
        assert await w.jobs.running(w.owner.household_id, w.owner.person_id, "agent") == before

    scenario(db_url, body)


def test_c05_the_limit_is_per_worker(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(limit("max_running", "agent")):
            await _hand_off_one(w, title=f"j{i}")
        await _hand_off_one(w, "claude_code", "code")

    scenario(db_url, body)


def test_c05_the_limit_is_per_person(db_url: str) -> None:
    async def body(w: World) -> None:
        from bjb_support import new_job
        mates = [replace(new_job(w, title=f"m{i}"), person=w.mate.person_id, bench=w.foreign_bench)
                 for i in range(limit("max_running", "agent"))]
        await w.start(*mates)
        assert await w.jobs.running(w.owner.household_id, w.owner.person_id, "agent") == 0
        await _hand_off_one(w)

    scenario(db_url, body)


def test_c05_a_finished_job_frees_its_place(db_url: str) -> None:
    async def body(w: World) -> None:
        from bjb_support import outcome
        for i in range(limit("max_running", "agent")):
            await _hand_off_one(w, title=f"j{i}")
        job = await w.claimed()
        assert await w.jobs.finish(job.id, job.attempts, outcome("done", summary="ok"))
        await _hand_off_one(w, title="again")

    scenario(db_url, body)


def test_c05_a_group_that_would_pass_max_running_is_too_many_and_records_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(limit("max_running", "agent") - 1):
            await _hand_off_one(w, title=f"j{i}")
        before = job_count(w.url)
        got = await w.hand_off(spec(title="a"), spec(title="b"))
        assert reason(got) == "too_many"
        assert job_count(w.url) == before

    scenario(db_url, body)


# --- 22 and the tool's own arguments --------------------------------------------------------------------------------


def test_c22_one_invalid_job_of_a_group_records_none_of_them(db_url: str) -> None:
    async def body(w: World) -> None:
        good = await w.piece("note", "good", "good")
        got = await w.hand_off(spec(title="fine", pieces=[good]), spec(title="bad", pieces=[9999]))
        assert reason(got) == "no_such_piece"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c22_a_group_of_a_valid_agent_job_and_a_refused_claude_code_job_records_neither(db_url: str) -> None:
    async def body(w: World) -> None:
        w.bridge.files = False
        got = await w.hand_off(spec("agent", title="a"), spec("claude_code", title="c"), can_code=True)
        assert reason(got) == "bridge_too_old"
        await nothing_recorded(w)

    scenario(db_url, body)


@pytest.mark.parametrize("bad", [
    {"worker": "bogus"},
    {"worker": ""},
    {"title": ""},
    {"title": "   "},
    {"brief": ""},
    {"pieces": "7"},
    {"pieces": [{"id": "7", "run_files": False}]},
    {"pieces": [{"id": 1}], "extra": 1},
], ids=["worker", "worker-empty", "title-empty", "title-blank", "brief-empty", "pieces-not-list", "id-not-int", "extra"])
def test_c22_malformed_jobs_are_bad_arguments_and_record_nothing(db_url: str, bad: dict[str, object]) -> None:
    async def body(w: World) -> None:
        await w.piece("note", "n", "n")
        got = await w.hand_off({**spec(), **bad})
        assert reason(got) == "bad_arguments"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c22_a_brief_over_brief_chars_is_refused_and_exactly_brief_chars_is_not(db_url: str) -> None:
    async def body(w: World) -> None:
        n = limit("brief_chars")
        assert reason(await w.hand_off(spec(brief="b" * (n + 1)))) == "bad_arguments"
        await nothing_recorded(w)
        assert not (await w.hand_off(spec(brief="b" * n))).is_error

    scenario(db_url, body)


def test_c22_no_jobs_and_more_than_max_group_jobs_are_bad_arguments(db_url: str) -> None:
    async def body(w: World) -> None:
        assert reason(await w.hand_off()) == "bad_arguments"
        too_many = [spec(title=f"j{i}") for i in range(limit("max_group") + 1)]
        assert reason(await w.hand_off(*too_many)) == "bad_arguments"
        await nothing_recorded(w)

    scenario(db_url, body)


def test_c22_max_group_jobs_in_one_call_are_accepted_when_the_worker_has_room(db_url: str) -> None:
    async def body(w: World) -> None:
        group = [spec(title=f"j{i}") for i in range(limit("max_group"))]
        got = payload(await w.hand_off(*group))
        assert len(got["jobs"]) == limit("max_group")

    scenario(db_url, body)


def test_c22_the_shipped_limits_are_the_specified_ones() -> None:
    c = cfg()
    assert (c.max_pieces_in, c.max_bytes_in, c.max_outputs, c.brief_chars, c.result_chars) == (12, 52428800, 8, 6000, 800)
    assert (c.agent_max_tool_rounds, c.max_runs_per_turn, c.max_group, c.group_timeout_min) == (40, 2, 3, 200)
    assert dict(c.max_running) == {"agent": 3, "claude_code": 3}
    assert dict(c.deadline_min) == {"agent": 30, "claude_code": 180}
