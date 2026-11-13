"""Contract 19 (logs carry ids, counts and durations and never a title, brief, file name or summary) and the wiring the
design states: the runner is a singleton under the `bench_jobs` lease, the service is wired, `bench_job` is a task with its
own route. The source scans prefilter on text before they walk an AST and each proves it can fail."""

import ast
import json
from pathlib import Path

import pytest
from bjb_support import HANG, MARK_BODY, MARK_BRIEF, MARK_TITLE, World, age, call, calls_of, cfg, finished, scenario, spec
from contract.conversations_support import scalar
from later_support import Logged
from source_tree import Parsed

NAME_MARK, SUMMARY_MARK, BRIEF_B = "NAMEMARK-LOG-kk11.txt", "SUMMARY-MARK-ll22", "BRIEF-B-LOG-mm33"
JOB_KEY, WORKER_KEY, ATTEMPT_KEY, DURATION_KEY = "job", "worker", "attempt", "duration_ms"
EVENTS = ("bench_jobs.started", "bench_jobs.finished", "bench_jobs.retaken", "bench_jobs.cancelled")
FORBIDDEN = {"title", "brief", "summary", "name", "filename", "file", "path", "text", "body", "content", "prompt",
             "transcript", "message", "label"}
APP = Path(__file__).resolve().parent.parent.parent
TARGET_STEMS = {"job_scope", "bench_agent", "bench_session", "jobs_config", "bench_jobs", "bench_job"}


async def lifecycle(w: World) -> None:
    a = await w.hand_off(spec(title=MARK_TITLE, brief=MARK_BRIEF + " A"), spec(title="second", brief=BRIEF_B))
    assert not a.is_error, a.content
    w.model.routed = {MARK_BRIEF: [calls_of(("bench_add", {"kind": "note", "title": NAME_MARK, "body": MARK_BODY})),
                                   finished(SUMMARY_MARK)],
                      BRIEF_B: [HANG]}
    await w.ticks(5)
    stuck = next(j for j in (1, 2, 3, 4, 5, 6) if state_of_or_none(w, j) == "running")
    age(w.url, stuck, "claimed_at", cfg().claim_s * 10 + 60)
    old = w.runners[-1]
    if hasattr(old, "stop"):
        await old.stop()
    w.model.routed = {BRIEF_B: [finished("second done")]}
    w.runner()
    await w.ticks(5)
    third = await w.hand_off(spec(title="third", brief="third brief"))
    job = json.loads(third.content)["jobs"][0]["job"]
    await w.tools().call(call("bench_job_cancel", job=job))
    await w.ticks(2)


def state_of_or_none(w: World, job: int) -> str | None:
    found = scalar(w.url, "SELECT coalesce((SELECT state FROM bench_jobs WHERE id = %s), 'none')", (job,))
    return None if found == "none" else str(found)


def test_c19_every_event_carries_the_job_its_worker_and_its_attempt_and_the_finish_its_duration(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    scenario(db_url, lifecycle)
    for event in EVENTS:
        lines = log.events(event)
        assert lines, f"no {event} line"
        for line in lines:
            assert JOB_KEY in line and WORKER_KEY in line, (event, line)
    for event in ("bench_jobs.started", "bench_jobs.finished", "bench_jobs.retaken"):
        assert all(ATTEMPT_KEY in line for line in log.events(event)), event
    assert all(DURATION_KEY in line for line in log.events("bench_jobs.finished"))


def test_c19_no_log_line_carries_a_title_a_brief_a_file_name_or_a_summary(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    scenario(db_url, lifecycle)
    text = log.read()
    assert "bench_jobs." in text, "the run logged nothing of its own, so the scan below would prove nothing"
    for mark in (MARK_TITLE, MARK_BRIEF, BRIEF_B, NAME_MARK, SUMMARY_MARK, MARK_BODY, "second done"):
        assert mark not in text, mark


def test_c19_a_claude_code_run_logs_no_file_name_summary_or_prompt(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)

    async def body(w: World) -> None:
        got = await w.hand_off(spec("claude_code", title=MARK_TITLE, brief=MARK_BRIEF), can_code=True)
        assert not got.is_error, got.content
        await w.ticks(3)
        sid = next(iter(w.bridge.sessions_))
        w.bridge.out[sid] = {"RESULT.md": SUMMARY_MARK.encode(), NAME_MARK: b"x\n"}
        w.bridge.settle(sid, "done")
        await w.ticks(4)

    scenario(db_url, body)
    text = log.read()
    assert "bench_jobs." in text
    for mark in (MARK_TITLE, MARK_BRIEF, NAME_MARK, SUMMARY_MARK):
        assert mark not in text, mark


# --- source scans -------------------------------------------------------------------------------------------------------------


def forbidden_fields(source: str) -> list[str]:
    """The keyword names a `logs.<level>(...)` call passes that would carry a person's words or a file's name."""
    if "logs." not in source:
        return []
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logs" and node.func.attr in ("debug", "info", "warning", "error", "exception")):
            found += [k.arg for k in node.keywords if k.arg in FORBIDDEN]
    return found


def log_calls(source: str) -> int:
    if "logs." not in source:
        return 0
    return sum(1 for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "logs")


def targets(tree: dict[Path, Parsed]) -> dict[Path, Parsed]:
    return {p: v for p, v in tree.items() if p.is_relative_to(APP / "ashley") and p.stem in TARGET_STEMS}


def test_c19_the_scan_can_fail() -> None:
    assert forbidden_fields("logs.info(log, 'bench_jobs.started', job=1, title=t)") == ["title"]
    assert forbidden_fields("logs.info(log, 'bench_jobs.started', job=1, worker='agent')") == []
    assert log_calls("logs.info(log, 'x', job=1)") == 1


def test_c19_no_bench_job_module_passes_words_or_names_to_a_log_call(package_tree: dict[Path, Parsed]) -> None:
    mine = targets(package_tree)
    if not mine:
        pytest.skip("the bench-jobs modules are not built yet")
    assert sum(log_calls(v.source) for v in mine.values()) >= 1, "the scan found no log call in the bench-jobs modules"
    bad = {p.name: forbidden_fields(v.source) for p, v in mine.items() if forbidden_fields(v.source)}
    assert bad == {}


def has_name(tree: dict[Path, Parsed], file: str, name: str) -> bool:
    for p, v in tree.items():
        if p.name == file and p.is_relative_to(APP / "ashley") and name in v.source:
            return any(isinstance(n, ast.Name) and n.id == name or isinstance(n, ast.Attribute) and n.attr == name
                       for n in ast.walk(v.tree))
    return False


def test_c14_the_runner_is_a_singleton_under_the_bench_jobs_lease(package_tree: dict[Path, Parsed]) -> None:
    assert has_name(package_tree, "wiring_singletons.py", "BenchJobRunner")
    source = next(v.source for p, v in package_tree.items() if p.name == "wiring_singletons.py" and p.is_relative_to(APP / "ashley"))
    strings = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    names = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
    assert "bench_jobs" in strings or "NAME" in names or any("bench_job" in n for n in names)


def test_c19_the_jobs_service_is_wired_by_the_app(package_tree: dict[Path, Parsed]) -> None:
    # AMBIGUITY: this repo wires a package's stores in its own register.py, which wiring.py calls.
    wired = [p for p, v in package_tree.items() if p.is_relative_to(APP / "ashley") and "PostgresBenchJobs" in v.source
             and (p.name.startswith("wiring") or p.name == "register.py")]
    assert wired, "no wiring module registers PostgresBenchJobs, so every entry point would run on the Null Object"
    entry = next(v.source for p, v in package_tree.items() if p == APP / "ashley" / "wiring.py")
    assert any(f"{p.parent.name}.register import" in entry or p.name.startswith("wiring") for p in wired)


def test_c14_bench_job_is_a_task_with_its_own_route_and_room_for_a_build123d_script() -> None:
    from typing import get_args
    from ashley.inference.model import Task
    assert "bench_job" in get_args(Task)
    routes = json.loads((APP / "ashley" / "inference" / "routes.json").read_text())["tasks"]["bench_job"]
    assert routes
    for r in routes:
        tokens = r["params"].get("max_tokens") or r["params"].get("max_completion_tokens")
        assert tokens is not None and tokens >= 32000, r
