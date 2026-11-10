"""The bench-act eval's scripted mode (`python -m ashley.evals bench-act --scripted`): every case passes with the fixes in
place, and the cases that a setting can undo fail without it, so the grading is able to fail."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services
from ashley.evals import bench_act
from ashley.evals.bench_act import Options
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
