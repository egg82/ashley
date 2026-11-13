"""Contracts 11 and 13 through `bench_session.step` over a fake bridge client that keeps files: the session's directory,
what goes up, the prompt, and what comes back into the bench when the session is done."""

from typing import Any

import pytest

from bjb_support import (ACCESS, MARK_BODY, MARK_BRIEF, MARK_TITLE, ROOT, World, bench_session, limit, named, out_file, row,
                         scenario, state_of)
from files_support import ELF, PNG
from ashley import services
from ashley.files import config as files_config
from ashley.workshop.workshop import Workshop
from bench_run_support import code as run_code
from ashley.herdr.model import Status
from ashley.inference.model import ToolCall
from ashley.tools.bench_run import BenchRunTools

UNNAMED_T, UNNAMED_B = "UNNAMED-TITLE-aa11", "UNNAMED-BODY-bb22"


async def claude_job(w: World, pieces: list[Any], brief: str = MARK_BRIEF) -> Any:
    await w.started("claude_code", pieces=pieces, brief=brief)
    return await w.claimed("claude_code")


async def fresh(w: World, job: Any) -> Any:
    return await w.jobs.get(w.owner.household_id, w.owner.person_id, job.id)


async def step(w: World, job: Any) -> Any:
    return await bench_session.step(await fresh(w, job))


def only_session(w: World) -> str:
    (sid,) = w.bridge.sessions_
    return sid


async def new_piece_authors(w: World, before: set[int]) -> list[tuple[int, str]]:
    log = await services.get(Workshop).log(w.owner, w.bench)
    return [(r.seq, r.by.author) for r in log if r.seq not in before and r.outcome == "accepted"]


# --- 11 --------------------------------------------------------------------------------------------------------------


def test_c11_the_first_step_starts_a_session_under_a_root_uploads_and_prompts_then_still_runs(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        assert await step(w, job) is None
        ((_, directory, label),) = w.bridge.named("start")
        assert directory == f"{ROOT}/ashley-jobs/j{job.id}" and str(job.id) in label
        sid = only_session(w)
        stored = row(w.url, job.id)
        assert stored["session_id"] == sid and stored["prompted_at"] is not None
        assert len(w.bridge.prompts[sid]) == 1

    scenario(db_url, body)


def test_c11_stored_pieces_go_up_as_p_id_in_their_natural_file(db_url: str) -> None:
    async def body(w: World) -> None:
        kinds = {"code": "py", "model": "py", "facts": "json", "document": "md", "note": "md"}
        bodies = {"facts": '{"items":[{"name":"w","value":3,"unit":"mm","source":"measured"}]}'}
        ids = {k: await w.piece(k, f"t-{k}", bodies.get(k, f"body of {k}")) for k in kinds}
        job = await claude_job(w, [named(i) for i in ids.values()])
        await step(w, job)
        sent = w.bridge.inbox[only_session(w)]
        assert set(sent) == {f"p{ids[k]}.{ext}" for k, ext in kinds.items()}
        for kind, pid in ids.items():
            assert sent[f"p{pid}.{kinds[kind]}"].decode() == bodies.get(kind, f"body of {kind}")

    scenario(db_url, body)


def test_c11_a_large_piece_goes_up_as_its_bytes_named_by_its_media_type(db_url: str) -> None:
    async def body(w: World) -> None:
        pic = await w.file_piece(PNG, "whatever-title.png")
        job = await claude_job(w, [named(pic)])
        await step(w, job)
        assert w.bridge.inbox[only_session(w)] == {f"p{pic}.png": PNG}

    scenario(db_url, body)


def test_c11_run_files_send_the_latest_runs_kept_file_as_p_id_run(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await services.get(Workshop).apply(w.owner, w.bench, run_code(w.owner))
        piece = got.piece_id
        assert piece is not None
        ran = await BenchRunTools(w.owner.household_id, w.owner.person_id, w.bench, w.conversation, w.turn).call(
            ToolCall("r", "bench_run", {"piece_id": piece, "base_version": 1, "language": "python"}))
        assert not ran.is_error, ran.content
        job = await claude_job(w, [named(piece, True)])
        await step(w, job)
        sent = w.bridge.inbox[only_session(w)]
        assert set(sent) == {f"p{piece}.py", f"p{piece}-run.txt"} and sent[f"p{piece}-run.txt"] == b"1"

    scenario(db_url, body)


def test_c11_without_run_files_no_run_file_goes(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await services.get(Workshop).apply(w.owner, w.bench, run_code(w.owner))
        assert got.piece_id is not None
        await BenchRunTools(w.owner.household_id, w.owner.person_id, w.bench, w.conversation, w.turn).call(
            ToolCall("r", "bench_run", {"piece_id": got.piece_id, "base_version": 1, "language": "python"}))
        job = await claude_job(w, [named(got.piece_id, False)])
        await step(w, job)
        assert set(w.bridge.inbox[only_session(w)]) == {f"p{got.piece_id}.py"}

    scenario(db_url, body)


def test_c03_an_unnamed_piece_and_every_title_stay_out_of_names_bytes_prompt_and_label(db_url: str) -> None:
    async def body(w: World) -> None:
        mine = await w.piece("note", MARK_TITLE, MARK_BODY)
        await w.piece("note", UNNAMED_T, UNNAMED_B)
        await w.file_piece(PNG + b"\x07", "UNNAMED-PIC-ee55.png")
        job = await claude_job(w, [named(mine)])
        await step(w, job)
        sid = only_session(w)
        sent = w.bridge.inbox[sid]
        assert list(sent.values()) == [MARK_BODY.encode()]
        seen = "\n".join([*sent, *w.bridge.prompts[sid], *(c[2] for c in w.bridge.named("start"))])
        for mark in (MARK_TITLE, UNNAMED_T, UNNAMED_B, "UNNAMED-PIC"):
            assert mark not in seen, mark
        assert all(mark.encode() not in b for b in sent.values() for mark in (UNNAMED_B, MARK_TITLE))

    scenario(db_url, body)


def test_c11_the_prompt_is_the_brief_then_a_footer_written_by_code(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        await step(w, job)
        (prompt,) = w.bridge.prompts[only_session(w)]
        assert prompt.startswith(MARK_BRIEF) and len(prompt) > len(MARK_BRIEF) + 40
        footer = prompt[len(MARK_BRIEF):]
        for token in ("./in", "./out", "RESULT.md", str(limit("max_outputs")), str(limit("result_chars"))):
            assert token in footer, token

    scenario(db_url, body)


def test_c11_the_footer_is_the_same_for_every_brief(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await claude_job(w, [], brief="first brief")
        await step(w, a)
        b = await claude_job(w, [], brief="second, longer brief")
        await step(w, b)
        first, second = (v[0] for v in w.bridge.prompts.values())
        assert first[len("first brief"):] == second[len("second, longer brief"):]

    scenario(db_url, body)


def test_c11_uploads_come_before_the_prompt(db_url: str) -> None:
    async def body(w: World) -> None:
        note = await w.piece("note", "t", "b")
        await step(w, await claude_job(w, [named(note)]))
        order = [c[0] for c in w.bridge.calls if c[0] in ("start", "upload", "prompt")]
        assert order == ["start", "upload", "prompt"]

    scenario(db_url, body)


def test_c11_a_directory_the_bridge_refuses_ends_the_job_failed_with_that_reason(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        w.bridge.fail["start"] = "dir_not_allowed"  # the app starts under the listed root, so the bridge itself must refuse
        got = await step(w, job)
        assert got is not None and got.state == "failed" and got.reason

    scenario(db_url, body)


def test_c11_a_bridge_with_null_roots_ends_the_job_failed_no_roots(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        w.bridge.roots = None
        got = await step(w, job)
        assert got is not None and (got.state, got.reason) == ("failed", "no_roots")
        assert w.bridge.named("start") == [] or w.bridge.sessions_ == {}

    scenario(db_url, body)


def test_c11_a_working_session_is_left_alone_between_ticks(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        await step(w, job)
        before = len(w.bridge.calls)
        assert await step(w, job) is None
        assert await step(w, job) is None
        assert [c[0] for c in w.bridge.calls[before:] if c[0] in ("start", "upload", "prompt", "close")] == []
        assert len(w.bridge.prompts[only_session(w)]) == 1

    scenario(db_url, body)


def test_c11_a_retake_with_a_session_but_no_prompt_uploads_again_and_prompts_once(db_url: str) -> None:
    async def body(w: World) -> None:
        note = await w.piece("note", "t", "b")
        job = await claude_job(w, [named(note)])
        made = await w.bridge.start(ACCESS, f"{ROOT}/ashley-jobs/j{job.id}", f"job{job.id}", None)
        w.bridge.calls.clear()
        await w.jobs.started(job.id, job.attempts, made.id)
        assert await step(w, job) is None
        assert [c[0] for c in w.bridge.calls if c[0] in ("start", "upload", "prompt")] == ["upload", "prompt"]
        assert row(w.url, job.id)["prompted_at"] is not None

    scenario(db_url, body)


def test_c11_a_retake_whose_session_already_moved_records_prompted_without_prompting_again(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        made = await w.bridge.start(ACCESS, f"{ROOT}/ashley-jobs/j{job.id}", f"job{job.id}", None)
        await w.jobs.started(job.id, job.attempts, made.id)
        w.bridge.settle(made.id, "working")
        w.bridge.calls.clear()
        assert await step(w, job) is None
        assert [c[0] for c in w.bridge.calls if c[0] == "prompt"] == []
        assert row(w.url, job.id)["prompted_at"] is not None

    scenario(db_url, body)


# --- blocked ---------------------------------------------------------------------------------------------------------


def test_c16_a_blocked_session_makes_the_job_blocked_and_it_works_again_with_the_session(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        await step(w, job)
        sid = only_session(w)
        w.bridge.settle(sid, "blocked")
        assert await step(w, job) is None and state_of(w.url, job.id) == "blocked"
        w.bridge.settle(sid, "working")
        assert await step(w, job) is None and state_of(w.url, job.id) == "running"
        assert w.bridge.closed == [] and len(w.bridge.prompts[sid]) == 1, "she never answers a dialog"

    scenario(db_url, body)


# --- 13 --------------------------------------------------------------------------------------------------------------


async def finished_session(w: World, files: dict[str, bytes], status: Status = "done") -> tuple[Any, Any]:
    job = await claude_job(w, [])
    await step(w, job)
    sid = only_session(w)
    w.bridge.out[sid] = files
    w.bridge.settle(sid, status)
    return job, await step(w, job)


def test_c13_on_done_each_accepted_file_becomes_a_file_piece_by_her_refused_ones_are_counted(db_url: str) -> None:
    async def body(w: World) -> None:
        before = set((await w.pieces()))
        log_before = {r.seq for r in await services.get(Workshop).log(w.owner, w.bench)}
        _, got = await finished_session(w, {"RESULT.md": b"the summary", "good.png": PNG, "note.txt": b"hello\n",
                                              "bad.exe": ELF})
        assert got is not None and got.state == "done" and got.summary == "the summary"
        assert len(got.outputs) == 2 and got.refused == 1
        pieces = await w.pieces()
        assert set(got.outputs) == set(pieces) - before
        assert {pieces[i].kind for i in got.outputs} <= {"image", "file", "clip", "audio"}
        authors = await new_piece_authors(w, log_before)
        assert {a for s, a in authors if s in got.outputs} == {"ashley"}

    scenario(db_url, body)


def test_c13_result_md_is_the_summary_cut_to_result_chars_and_is_not_a_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        before = set(await w.pieces())
        _, got = await finished_session(w, {"RESULT.md": b"s" * (limit("result_chars") * 4)})
        assert got.state == "done" and 0 < len(got.summary) <= limit("result_chars")
        assert got.outputs == () and set(await w.pieces()) == before and got.refused == 0

    scenario(db_url, body)


def test_c13_at_most_max_outputs_files_become_pieces(db_url: str) -> None:
    async def body(w: World) -> None:
        many = {f"f{i}.txt": f"file {i}\n".encode() for i in range(limit("max_outputs") + 4)}
        many["RESULT.md"] = b"r"
        _, got = await finished_session(w, many)
        assert got.state == "done" and 1 <= len(got.outputs) <= limit("max_outputs")

    scenario(db_url, body)


def test_c13_only_names_the_bridge_listed_are_downloaded(db_url: str) -> None:
    async def body(w: World) -> None:
        await finished_session(w, {"a.txt": b"a\n", "RESULT.md": b"r"})
        assert {c[2] for c in w.bridge.named("download")} <= {"a.txt", "RESULT.md"}
        assert w.bridge.named("outputs"), "out/ is listed first"

    scenario(db_url, body)


def test_c13_an_idle_session_after_working_is_a_finished_job(db_url: str) -> None:
    async def body(w: World) -> None:
        _, got = await finished_session(w, {"RESULT.md": b"ok"}, status="idle")
        assert got is not None and got.state == "done"

    scenario(db_url, body)


def test_c13_the_session_is_left_open_on_finish(db_url: str) -> None:
    async def body(w: World) -> None:
        await finished_session(w, {"RESULT.md": b"ok"})
        assert w.bridge.closed == [] and len(w.bridge.sessions_) == 1

    scenario(db_url, body)


@pytest.mark.parametrize("status", ["done", "idle"])
def test_c13_a_stopped_session_without_a_result_md_is_not_a_finished_job(db_url: str, status: Status) -> None:
    async def body(w: World) -> None:
        job, got = await finished_session(w, {"a.txt": b"made\n"}, status=status)
        assert got is None and state_of(w.url, job.id) == "running"
        assert w.bridge.closed == [] and len(w.bridge.sessions_) == 1

    scenario(db_url, body)


def test_c13_a_file_over_the_ceiling_is_refused_not_downloaded_into_a_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        job = await claude_job(w, [])
        await step(w, job)
        sid = only_session(w)
        w.bridge.out[sid] = {"ok.txt": b"fine\n", "RESULT.md": b"r"}
        w.bridge.settle(sid, "done")
        w.bridge.phantom[sid] = [out_file("huge.bin", files_config.load().max_bytes + 1)]
        got = await step(w, job)
        assert got.state == "done" and got.refused >= 1 and len(got.outputs) == 1
        assert "huge.bin" not in {c[2] for c in w.bridge.named("download")}

    scenario(db_url, body)
