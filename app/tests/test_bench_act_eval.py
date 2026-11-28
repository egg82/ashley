"""The bench-act eval's scripted mode (`python -m ashley.evals bench-act --scripted`): every case passes with the fixes in
place, and the cases that a setting can undo fail without it, so the grading is able to fail."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.evals import bench_act
from ashley.evals.bench_act import Options
from ashley.evals.bench_act_fakes import Clocked
from ashley.evals.bench_act_policy import Scripted
from ashley.evals.house_guard import RecordingInference
from ashley.inference.inference import Inference
from ashley.tools import bench_capture


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    yield
    services.unregister(Inference)
    bench_capture.uninstall()


def run(case: str | None = None, options: Options = Options(scripted=True)) -> list[bench_act.Result]:
    return asyncio.run(bench_act.run(1, case, options))


def test_every_case_passes_with_the_fixes_in_place() -> None:
    results = run()
    assert len(results) >= 9 and [r.case_id for r in results if not r.passed] == []


@pytest.mark.parametrize("case, options", [
    ("E4", Options(scripted=True, clock="age", windows=0)),
    ("E5", Options(scripted=True, windows=0)),
    ("E6", Options(scripted=True, now=False)),
    ("E7", Options(scripted=True, now=False, hold=6)),
    ("E8", Options(scripted=True, now=False)),
])
def test_a_case_fails_when_the_fix_it_measures_is_taken_away(case: str, options: Options) -> None:
    assert [r.passed for r in run(case, options)] == [False]


def test_an_unknown_case_is_refused() -> None:
    with pytest.raises(ValueError):
        run("E99")


def test_a_live_run_is_not_asked_for_a_window_it_may_rightly_not_need() -> None:
    e5 = next(c for c in bench_act.load() if c["id"] == "E5")
    assert "windows_taken" not in e5["expect"] and e5["expect_scripted"] == {"windows_taken": 1}
    assert run("E5", Options(scripted=True, windows=0))[0].passed is False


def test_a_held_turn_that_moved_resumes_on_the_bench_it_moved_to() -> None:
    assert [r.passed for r in run("E6")] == [True]
    clocked = services.get(Inference)
    assert isinstance(clocked, Clocked) and isinstance(clocked.inner, RecordingInference)
    scripted = clocked.inner.inner
    assert isinstance(scripted, Scripted)
    offered = [{t.name for t in p.tools} for p in scripted.seen]
    assert len(offered) == 3 and "bench_read" not in offered[0] and all("bench_read" in o for o in offered[1:])
