"""Runs `write_cases.json` against a `FactWriter`. Grading is structural (op, target, about, owner, kind, standing,
visibility); what a fact `states`, and what it `omits` (something said beside it that is no part of the fact, such
as a one-off ask), is judged by a callable, never by matching words."""

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...conversations.model import Conversation, Turn
from ..memory import FactWriter
from ..model import Add, Fact, Forget, Invalidate, Noop, Op, Update

CASES = Path(__file__).parent / "write_cases.json"
NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
HOUSEHOLD = 1
FIRST_KNOWN_ID = 100

Judge = Callable[[str, str], Awaitable[bool]]
"""`(expected, actual)`: whether the written fact states what the case expects. Supplied by the runner."""

_OPS = {"add": Add, "update": Update, "invalidate": Invalidate, "forget": Forget}


@dataclass(frozen=True)
class WriteCaseResult:
    """`failures` holds one structural description per failed run (no conversation content). `known_failing` marks a
    case the current writer is known to fail, kept in every rate so the eval shows the gap rather than hides it."""

    case_id: str
    source: str
    runs: int
    passes: int
    failures: tuple[str, ...]
    known_failing: bool = False

    @property
    def rate(self) -> float:
        return self.passes / self.runs


@dataclass(frozen=True)
class WriteReport:
    cases: tuple[WriteCaseResult, ...]

    def by_source(self) -> dict[str, float]:
        """Pass rate over all runs of the cases of each `source`."""
        out: dict[str, float] = {}
        for source in {c.source for c in self.cases}:
            of = [c for c in self.cases if c.source == source]
            out[source] = sum(c.passes for c in of) / sum(c.runs for c in of)
        return out


def load(path: Path = CASES) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for case in data["cases"]:
        refs = {k["ref"] for k in case["known"]}
        unknown = {e["target"] for e in case["expect"] if "target" in e} - refs
        if unknown:
            raise ValueError(f"case {case['id']} expects unknown targets {sorted(unknown)}")
    return data


def _person(people: dict[str, int], name: str | None) -> int | None:
    return None if name is None else people[name]


def build(data: dict[str, Any], case: dict[str, Any]) -> tuple[Conversation, tuple[Fact, ...], dict[str, int]]:
    """The conversation, the known facts and the ref -> id map for one case."""
    people = data["people"]
    turns = tuple(
        Turn(
            id=i + 1,
            author=t["author"],
            speaker_id=_person(people, t.get("speaker")),
            text=t["text"],
            at=NOW - timedelta(minutes=len(case["turns"]) - i),
        )
        for i, t in enumerate(case["turns"])
    )
    known = tuple(
        Fact(
            id=FIRST_KNOWN_ID + i,
            household_id=HOUSEHOLD,
            about_id=_person(people, k["about"]),
            owner_id=_person(people, k["owner"]),
            visibility=k["visibility"],
            kind=k["kind"],
            standing=k.get("standing", False),
            text=k["text"],
            source_conversation_id=0,
            valid_from=NOW - timedelta(days=30),
            valid_to=None,
            superseded_by=None,
        )
        for i, k in enumerate(case["known"])
    )
    conversation = Conversation(
        id=1,
        household_id=HOUSEHOLD,
        kind="chat",
        participants=frozenset(t.speaker_id for t in turns if t.speaker_id is not None),
        started_at=turns[0].at,
        last_activity_at=turns[-1].at,
        state="idle",
        turns=turns,
    )
    return conversation, known, {k["ref"]: f.id for k, f in zip(case["known"], known)}


def _structural(op: Op, expected: dict[str, Any], people: dict[str, int], ids: dict[str, int]) -> bool:
    if not isinstance(op, _OPS[expected["op"]]):
        return False
    if "target" in expected and getattr(op, "target", None) != ids[expected["target"]]:
        return False
    fact = getattr(op, "fact", None)
    if fact is None:
        return True
    if "about" in expected and fact.about_id != _person(people, expected["about"]):
        return False
    if "owner" in expected and fact.owner_id != _person(people, expected["owner"]):
        return False
    graded = ("kind", "visibility", "visibility_stated", "standing")
    return all(getattr(fact, k) == expected[k] for k in graded if k in expected)


async def _matches(op: Op, expected: dict[str, Any], people: dict[str, int], ids: dict[str, int],
                   judge: Judge) -> bool:
    if not _structural(op, expected, people, ids):
        return False
    fact = getattr(op, "fact", None)
    if fact is None:
        return True
    if "states" in expected and not await judge(expected["states"], fact.text):
        return False
    return "omits" not in expected or not await judge(expected["omits"], fact.text)


def _assign(compatible: list[set[int]], taken: frozenset[int] = frozenset()) -> bool:
    """Whether every expectation can take its own op, one to one."""
    if not compatible:
        return True
    return any(_assign(compatible[1:], taken | {i}) for i in compatible[0] - taken)


async def grade(ops: Sequence[Op], expect: list[dict[str, Any]], people: dict[str, int], ids: dict[str, int],
          judge: Judge) -> str | None:
    """None when the non-`Noop` ops match `expect` one to one; else what differs."""
    written = [op for op in ops if not isinstance(op, Noop)]
    if len(written) != len(expect):
        return f"wrote {len(written)} ops, expected {len(expect)}"
    compatible = [{i for i, op in enumerate(written) if await _matches(op, e, people, ids, judge)} for e in expect]
    if _assign(compatible):
        return None
    return "no one-to-one match; unmatched expectations: " + ", ".join(
        f"{e['op']}#{i}" for i, (e, c) in enumerate(zip(expect, compatible)) if not c
    )


async def run_write(writer: FactWriter, judge: Judge, runs: int = 1, path: Path = CASES,
                    only: str | None = None) -> WriteReport:
    """Each case `runs` times against `writer`, graded structurally with `judge` for `states`; only the case whose id
    is `only` when given (ValueError when no case has it)."""
    data = load(path)
    cases = [c for c in data["cases"] if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no write case {only!r}")
    results: list[WriteCaseResult] = []
    for case in cases:
        conversation, known, ids = build(data, case)
        failures: list[str] = []
        for _ in range(runs):
            ops = await writer.decide(conversation, known, NOW)
            problem = await grade(ops, case["expect"], data["people"], ids, judge)
            if problem:
                failures.append(problem)
        results.append(WriteCaseResult(case["id"], case["source"], runs, runs - len(failures), tuple(failures),
                                       case.get("known_failing", False)))
    return WriteReport(tuple(results))
