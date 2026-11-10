"""The Memory eval's cases can fail: a correct implementation passes every case, every planted wrong one fails at
least one, and every case is failed by at least one planted wrong one (`memory_eval_support`, `write_eval_support`)."""

import asyncio
from collections.abc import Callable
from functools import cache

import pytest
from ashley.memory.eval import recall, write
from ashley.memory.memory import FactWriter, Memory
from memory_eval_support import RECALL_MUTANTS, RuleMemory
from write_eval_support import WRITE_MUTANTS, ExpectedWriter, same_text


@cache
def recall_failures(name: str | None) -> frozenset[str]:
    factory: Callable[[], Memory] = RECALL_MUTANTS[name] if name else RuleMemory
    return frozenset(r.case_id for r in asyncio.run(recall.run_recall(factory)) if not r.passed)


@cache
def write_failures(name: str | None) -> frozenset[str]:
    factory: Callable[[], FactWriter] = WRITE_MUTANTS[name] if name else ExpectedWriter
    report = asyncio.run(write.run_write(factory(), same_text))
    return frozenset(c.case_id for c in report.cases if c.passes < c.runs)


def test_the_recall_control_passes_every_case() -> None:
    assert len(recall.load()["cases"]) > 0 and recall_failures(None) == frozenset()


@pytest.mark.parametrize("name", RECALL_MUTANTS)
def test_each_recall_mutant_fails_a_case(name: str) -> None:
    assert recall_failures(name), f"no recall case notices: {name}"


def test_every_recall_case_is_failed_by_a_mutant() -> None:
    killed = {c for n in RECALL_MUTANTS for c in recall_failures(n)}
    unkilled = {c["id"] for c in recall.load()["cases"]} - killed
    assert not unkilled, f"no mutant fails these recall cases: {sorted(unkilled)}"


def test_the_write_control_passes_every_case() -> None:
    assert len(write.load()["cases"]) > 0 and write_failures(None) == frozenset()


@pytest.mark.parametrize("name", WRITE_MUTANTS)
def test_each_write_mutant_fails_a_case(name: str) -> None:
    assert write_failures(name), f"no write case notices: {name}"


def test_every_write_case_is_failed_by_a_mutant() -> None:
    killed = {c for n in WRITE_MUTANTS for c in write_failures(n)}
    unkilled = {c["id"] for c in write.load()["cases"]} - killed
    assert not unkilled, f"no mutant fails these write cases: {sorted(unkilled)}"
