"""Contract 6 (and R1, R2): a successful call returns before any worker step runs. Its job row is `due`, its `job` piece
exists, one `bench_job` watch is armed for the group, and nothing was sent to a worker."""

from bjb_support import (MARK_BODY, MARK_TITLE, World, job_body, job_pieces, payload, reason, row, scenario, spec, state_of,
                         watch_rows, watches_down)
from ashley import services
from ashley.watches.watches import Watches
from ashley.workshop.workshop import Workshop


def test_c06_one_job_comes_back_as_a_group_of_one_with_its_piece_and_a_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        note = await w.piece("note", MARK_TITLE, MARK_BODY)
        got = payload(await w.hand_off(spec(title="Gate", brief="Build it.", pieces=[note])))
        assert got["watched"] is True
        (job,) = got["jobs"]
        assert job["worker"] == "agent" and set(job) == {"job", "piece", "worker", "state"}
        stored = row(w.url, job["job"])
        assert stored["state"] == "due" and stored["attempts"] == 0
        assert stored["group_id"] == got["group"] and stored["piece_id"] == job["piece"]
        assert (stored["worker"], stored["title"], stored["brief"]) == ("agent", "Gate", "Build it.")
        assert stored["person_id"] == w.owner.person_id and stored["bench_id"] == w.bench

    scenario(db_url, body)


def test_c06_no_worker_step_ran_before_the_call_returned(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.hand_off(spec("agent"), spec("claude_code", title="Code"), can_code=True)
        assert w.model.asked == []
        assert [c[0] for c in w.bridge.calls if c[0] in ("start", "upload", "prompt", "outputs", "download")] == []
        assert w.bridge.sessions_ == {}

    scenario(db_url, body)


def test_c06_the_job_piece_is_a_stored_job_piece_written_by_code(db_url: str) -> None:
    async def body(w: World) -> None:
        got = payload(await w.hand_off(spec(title="Gate")))
        pieces = await w.pieces()
        (piece,) = job_pieces(pieces)
        assert piece.id == got["jobs"][0]["piece"]
        shown = job_body(piece)
        assert shown["worker"] == "agent" and shown["title"] == "Gate" and shown["state"] == "due"
        assert shown["outputs"] == []
        log = await services.get(Workshop).log(w.owner, w.bench)
        assert [r.by.author for r in log if r.seq == piece.id] == ["ashley"]
        assert w.ran.heard.events, "a change by her is announced on Live"

    scenario(db_url, body)


def test_c06_a_bench_job_watch_is_armed_on_the_group_for_this_bench_as_a_handoff(db_url: str) -> None:
    async def body(w: World) -> None:
        got = payload(await w.hand_off(spec(title="a"), spec(title="b")))
        ((_, kind, target, armed_by, bench, track, state),) = watch_rows(w.url)
        assert (kind, target, armed_by, bench, state) == ("bench_job", str(got["group"]), "handoff", w.bench, "armed")
        assert list(track) == ["settled", "blocked", "waiting"]

    scenario(db_url, body)


def test_c06_a_group_of_three_is_three_rows_three_pieces_and_one_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        got = payload(await w.hand_off(spec(title="gate"), spec(title="eye"), spec(title="tongue")))
        jobs = got["jobs"]
        assert len({j["job"] for j in jobs}) == 3 and len({j["piece"] for j in jobs}) == 3
        assert {row(w.url, j["job"])["group_id"] for j in jobs} == {got["group"]}
        assert [row(w.url, j["job"])["title"] for j in jobs] == ["gate", "eye", "tongue"]
        assert {state_of(w.url, j["job"]) for j in jobs} == {"due"}
        assert len(job_pieces(await w.pieces())) == 3
        assert len(watch_rows(w.url)) == 1

    scenario(db_url, body)


def test_c06_two_calls_are_two_groups(db_url: str) -> None:
    async def body(w: World) -> None:
        a = payload(await w.hand_off(spec(title="a")))
        b = payload(await w.hand_off(spec(title="b")))
        assert a["group"] != b["group"] and len(watch_rows(w.url)) == 2

    scenario(db_url, body)


def test_c06_the_named_pieces_are_recorded_on_the_job_in_order_with_their_run_files_flag(db_url: str) -> None:
    async def body(w: World) -> None:
        a, b = await w.piece("note", "a", "a"), await w.piece("code", "b", "print(1)")
        got = payload(await w.hand_off(spec(pieces=[a, (b, True)])))
        stored = row(w.url, got["jobs"][0]["job"])["pieces"]
        assert [(p["id"], p["run_files"]) for p in stored] == [(a, False), (b, True)]

    scenario(db_url, body)


def test_c06_an_unarmed_watch_is_said_not_hidden(db_url: str) -> None:
    async def body(w: World) -> None:
        services.register(Watches, watches_down())
        got = payload(await w.hand_off(spec()))
        assert got["watched"] is False
        assert state_of(w.url, got["jobs"][0]["job"]) == "due"

    scenario(db_url, body)


def test_c06_when_the_jobs_table_cannot_be_reached_the_call_fails_unavailable_and_adds_no_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        from bjb_support import BenchJobs
        services.register(BenchJobs, BenchJobs.null())
        assert reason(await w.hand_off(spec())) == "unavailable"
        assert job_pieces(await w.pieces()) == []

    scenario(db_url, body)
