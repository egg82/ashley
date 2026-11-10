"""Runs `recall_cases.json` against a `Memory`: leaks, validity and volunteering, all deterministic."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..memory import Memory
from ..model import Add, Asker, Forget, Invalidate, NewFact, Update

CASES = Path(__file__).parent / "recall_cases.json"
SEEDED_AT = datetime(2026, 1, 1, tzinfo=UTC)
ASKED_AT = datetime(2026, 6, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RecallResult:
    """`missing` are `include` refs not recalled, `leaked` are `exclude` refs recalled, `volunteered` are recalled
    `not_volunteer` refs whose `may_volunteer` is True."""

    case_id: str
    missing: tuple[str, ...]
    leaked: tuple[str, ...]
    volunteered: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not (self.missing or self.leaked or self.volunteered)


def load(path: Path = CASES) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = {f["ref"] for f in data["facts"]}
    for case in data["cases"]:
        for key in ("include", "exclude", "not_volunteer"):
            unknown = set(case.get(key, [])) - refs
            if unknown:
                raise ValueError(f"case {case['id']} names unknown refs {sorted(unknown)} in {key}")
    return data


def _new_fact(data: dict[str, Any], fact: dict[str, Any]) -> NewFact:
    people = data["people"]
    about, owner = fact["about"], fact["owner"]
    return NewFact(
        about_id=None if about is None else people[about],
        owner_id=None if owner is None else people[owner],
        visibility=fact["visibility"],
        visibility_stated=True,
        kind=fact["kind"],
        standing=fact.get("standing", False),
        text=fact["text"],
    )


async def _seed(memory: Memory, data: dict[str, Any]) -> dict[str, int]:
    """Writes every fact through `Memory.apply`, one conversation each; returns ref -> id. A fact another names in
    `superseded_by` is inserted by the `Update` on its predecessor. Forgotten facts have no row afterwards."""
    facts = {f["ref"]: f for f in data["facts"]}
    successors = {f["superseded_by"] for f in facts.values() if "superseded_by" in f}
    ids: dict[str, int] = {}
    households = data["households"]
    conversation = 0

    async def apply(ref: str, op: Add | Update | Invalidate | Forget) -> tuple[int, ...]:
        nonlocal conversation
        conversation += 1
        return await memory.apply(households[facts[ref]["household"]], conversation, [op], SEEDED_AT)

    for ref, fact in facts.items():
        if ref not in successors:
            (ids[ref],) = await apply(ref, Add(_new_fact(data, fact)))
    for ref, fact in facts.items():
        if "superseded_by" in fact:
            successor = fact["superseded_by"]
            (ids[successor],) = await apply(ref, Update(ids[ref], _new_fact(data, facts[successor])))
    for ref, fact in facts.items():
        if fact.get("invalidated"):
            await apply(ref, Invalidate(ids[ref]))
        if fact.get("forgotten"):
            await apply(ref, Forget(ids[ref]))
    return ids


async def _run_case(memory: Memory, data: dict[str, Any], ids: dict[str, int], case: dict[str, Any]) -> RecallResult:
    asker = case["asker"]
    speaker = asker["speaker"]
    recalled = await memory.recall(
        Asker(
            household_id=data["households"][asker["household"]],
            speaker_id=None if speaker is None else data["people"][speaker],
            owner_only=asker["owner_only"],
            at=ASKED_AT,
        ),
        case["query"],
    )
    may_volunteer = {r.fact.id: r.may_volunteer for r in recalled}
    return RecallResult(
        case_id=case["id"],
        missing=tuple(r for r in case["include"] if ids[r] not in may_volunteer),
        leaked=tuple(r for r in case["exclude"] if ids[r] in may_volunteer),
        volunteered=tuple(r for r in case.get("not_volunteer", []) if may_volunteer.get(ids[r], False)),
    )


async def run_recall(factory: Callable[[], Memory], path: Path = CASES) -> tuple[RecallResult, ...]:
    """Seeds one fresh `Memory` from the file's facts and runs every case against it."""
    data = load(path)
    memory = factory()
    ids = await _seed(memory, data)
    return tuple([await _run_case(memory, data, ids, case) for case in data["cases"]])
