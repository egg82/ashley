"""`bench_hand_off` and `bench_job_cancel` (`ashley.tools.bench_jobs`) over a real database: a call returns at once with
the jobs `due`, a `job` piece each and one group watch armed; any job that is not startable fails the whole call and
records nothing; a Claude Code job needs a connected bridge that takes files; and no log line carries a title, a brief or
a name."""

import json
from dataclasses import replace
from typing import Any

import pytest
from ashley import logs, services
from ashley.errands.bench_jobs import BenchJobs
from ashley.errands.jobs_config import CONFIG
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_jobs import BenchJobTools, specs
from ashley.watches.watches import Watches
from ashley.workshop.workshop import Workshop
from bench_jobs_support import Jobs, db_url as db_url, jobs_world, migrated_template as migrated_template
from contract.conversations_support import run

TITLE, BRIEF = "Gate variant zzq", "Build the zzq gate and run it"


def job(worker: str = "agent", pieces: list[dict[str, object]] | None = None, title: str = TITLE) -> dict[str, object]:
    return {"worker": worker, "title": title, "brief": BRIEF, "pieces": pieces or []}


def tools(w: Jobs, can_code: bool = True) -> BenchJobTools:
    return BenchJobTools(w.s.household, w.s.person, w.s.bench, (w.s.conversation, w.s.turn), can_code)


async def hand_off(w: Jobs, jobs: list[dict[str, object]], can_code: bool = True) -> ToolResult:
    return await tools(w, can_code).call(ToolCall("h", "bench_hand_off", {"jobs": jobs}))


async def stored(w: Jobs) -> int:
    return len(await services.get(BenchJobs).unfinished())


def test_a_call_returns_with_the_jobs_due_a_piece_each_and_one_watch(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            note = await w.piece("note", "N", "text")
            got = await hand_off(w, [job(pieces=[{"id": note}]), job("claude_code", title="Second")])
            assert not got.is_error
            body = json.loads(got.content)
            assert body["watched"] is True and [j["worker"] for j in body["jobs"]] == ["agent", "claude_code"]
            made = await services.get(BenchJobs).group(w.s.household, w.s.person, body["group"])
            assert [j.state for j in made] == ["due", "due"] and [j.id for j in made] == [j["job"] for j in body["jobs"]]
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            pieces = {p.id: p for p in view.pieces}
            assert all(pieces[j["piece"]].kind == "job" for j in body["jobs"])
            assert json.loads(pieces[made[0].piece_id].text.body)["job"] == made[0].id
            (watch,) = await services.get(Watches).live(w.s.household, w.s.person)
            assert (watch.kind, watch.target, watch.armed_by) == ("bench_job", str(body["group"]), "handoff")
            assert w.model.asked == []
    run(go())


def test_an_unknown_shelved_or_other_bench_piece_fails_the_call_and_records_nothing(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            good = await w.piece()
            for bad in (999, 0):
                got = await hand_off(w, [job(pieces=[{"id": good}]), job(pieces=[{"id": bad}])])
                assert got.is_error and got.content.startswith("no_such_piece")
            assert await stored(w) == 0
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            assert [p.kind for p in view.pieces] == ["note"]
    run(go())


def test_too_many_pieces_or_bytes_is_too_large_and_a_full_worker_is_too_many(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            ids = [await w.piece(title=f"p{i}") for i in range(3)]
            small = replace(CONFIG, max_pieces_in=2)
            got = await BenchJobTools(w.s.household, w.s.person, w.s.bench, (w.s.conversation, w.s.turn), False, small).call(
                ToolCall("h", "bench_hand_off", {"jobs": [job(pieces=[{"id": i} for i in ids])]}))
            assert got.is_error and got.content.startswith("too_large")
            tiny = replace(CONFIG, max_bytes_in=3)
            got = await BenchJobTools(w.s.household, w.s.person, w.s.bench, (w.s.conversation, w.s.turn), False, tiny).call(
                ToolCall("h", "bench_hand_off", {"jobs": [job(pieces=[{"id": ids[0]}])]}))
            assert got.is_error and got.content.startswith("too_large")
            assert await stored(w) == 0
            for _ in range(CONFIG.max_running["agent"]):
                assert not (await hand_off(w, [job()])).is_error
            full = await hand_off(w, [job()])
            assert full.is_error and full.content.startswith("too_many")
            assert await stored(w) == CONFIG.max_running["agent"]
            over = await hand_off(w, [job("claude_code")] * CONFIG.max_group)
            assert not over.is_error and await stored(w) == CONFIG.max_running["agent"] + CONFIG.max_group
            assert (await hand_off(w, [job("claude_code")])).content.startswith("too_many")
    run(go())


def test_one_bad_job_fails_the_group_and_arguments_are_checked(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            bad: list[dict[str, object]] = [{"jobs": []}, {"jobs": [job()] * (CONFIG.max_group + 1)}, {"jobs": "x"},
                         {"jobs": [{**job(), "extra": 1}]}, {"jobs": [{**job(), "worker": "other"}]},
                         {"jobs": [{**job(), "title": " "}]}, {"jobs": [{**job(), "pieces": [{"id": "1"}]}]},
                         {"jobs": [{**job(), "brief": "x" * (CONFIG.brief_chars + 1)}]}, {"jobs": [job()], "more": 1}]
            for args in bad:
                got = await tools(w).call(ToolCall("h", "bench_hand_off", args))
                assert got.is_error and got.content.startswith("bad_arguments"), args
            assert await stored(w) == 0
    run(go())


def test_claude_code_needs_a_bridge_that_takes_files_and_has_roots(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.bridge.capabilities = ()
            assert (await hand_off(w, [job("agent"), job("claude_code")])).content.startswith("bridge_too_old")
            w.bridge.capabilities, w.bridge.roots = ("files",), None
            assert (await hand_off(w, [job("claude_code")])).content.startswith("no_roots")
            w.bridge.roots, w.bridge.refuse = ("/work",), "bad_token"
            assert (await hand_off(w, [job("claude_code")])).content.startswith("bridge_refused")
            w.bridge.refuse = "wrong_person"
            assert (await hand_off(w, [job("claude_code")])).content.startswith("bridge_refused")
            assert await stored(w) == 0
            w.bridge.refuse = None
            assert not (await hand_off(w, [job("claude_code")])).is_error
    run(go())


def test_a_bridge_that_does_not_answer_records_the_claude_code_job_waiting_with_its_deadline(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            w.bridge.down = True
            got = await hand_off(w, [job("agent"), job("claude_code", title="Second")])
            assert not got.is_error
            body = json.loads(got.content)
            assert body["waiting"] is True and body["watched"] is True
            assert [(j["worker"], j["state"]) for j in body["jobs"]] == [("agent", "due"), ("claude_code", "waiting")]
            agent, code = await services.get(BenchJobs).group(w.s.household, w.s.person, body["group"])
            assert (agent.state, agent.deadline_at, code.state, code.attempts) == ("due", None, "waiting", 0)
            assert code.deadline_at is not None and code.created_at < code.deadline_at
            assert (code.deadline_at - code.created_at).total_seconds() / 60 > CONFIG.deadline_min["claude_code"] - 1
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            shown = next(p for p in view.pieces if p.id == code.piece_id)
            assert json.loads(shown.text.body)["state"] == "waiting"
            assert w.bridge.log == []
            w.bridge.down = False
            again = json.loads((await hand_off(w, [job("claude_code")])).content)
            assert again["waiting"] is False and again["jobs"][0]["state"] == "due"
    run(go())


def test_without_a_connection_claude_code_is_not_connected_and_the_agent_still_starts(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            from ashley.connections.connections import Connections
            from money_support import HeldConnections
            services.register(Connections, HeldConnections())
            assert (await hand_off(w, [job("claude_code")])).content.startswith("not_connected")
            assert await stored(w) == 0
            assert not (await hand_off(w, [job("agent")])).is_error
    run(go())


def workers(can_code: bool) -> object:
    loose: Any = specs(can_code)[0].parameters
    return loose["properties"]["jobs"]["items"]["properties"]["worker"]["enum"]


def test_the_worker_choice_follows_whether_claude_code_is_offered() -> None:
    assert workers(True) == ["agent", "claude_code"] and workers(False) == ["agent"]


def test_cancel_ends_the_job_shows_it_and_only_the_owner_may(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            made = json.loads((await hand_off(w, [job()])).content)["jobs"][0]
            got = await tools(w).call(ToolCall("c", "bench_job_cancel", {"job": made["job"]}))
            assert json.loads(got.content) == {"job": made["job"], "state": "cancelled"}
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            shown = next(p for p in view.pieces if p.id == made["piece"])
            assert json.loads(shown.text.body)["state"] == "cancelled"
            assert (await tools(w).call(ToolCall("c", "bench_job_cancel", {"job": 12345}))).content.startswith("no_such_job")
            assert (await tools(w).call(ToolCall("c", "bench_job_cancel", {"job": "x"}))).content.startswith("bad_arguments")
    run(go())


def test_logs_carry_ids_and_counts_never_a_title_a_brief_or_a_name(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with jobs_world(db_url) as w:
            note = await w.piece("note", "Secretpiece", "x")
            await hand_off(w, [job(pieces=[{"id": note}])])
            await hand_off(w, [job(pieces=[{"id": 777}])])
    run(go())
    out = capsys.readouterr().out
    assert "bench_jobs.started" in out and "zzq" not in out and "Secretpiece" not in out
