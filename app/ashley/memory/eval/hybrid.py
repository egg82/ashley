"""The hybrid recall eval: how often recall brings back a fact that answers a remark, by how the remark relates to it
(`hybrid_cases.json`: `lexical` shares its words, `paraphrase` says it otherwise, `indirect` needs the fact to answer),
and how many facts it returns for remarks nothing answers. A measurement, not a gate: its cases are `authored`."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from ..memory import Memory
from ..model import Add, Asker, NewFact

AT = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Scored:
    """`hits[style]` is (cases of that style that got a relevant fact back, cases of that style); `returned` the mean
    number of facts returned for a case, `returned_for_nothing` the mean for a remark no fact answers."""

    hits: dict[str, tuple[int, int]]
    returned: float
    returned_for_nothing: float


def load() -> dict[str, Any]:
    """The cases; every case names facts that exist."""
    data: dict[str, Any] = json.loads(resources.files("ashley.memory.eval").joinpath("hybrid_cases.json").read_text("utf-8"))
    unknown = {r for c in data["cases"] for r in c["relevant"]} - set(data["facts"])
    if unknown:
        raise ValueError(f"cases name unknown facts {sorted(unknown)}")
    return data


async def seed(memory: Memory, household_id: int, conversation_id: int, data: dict[str, Any]) -> dict[int, str]:
    """Writes every fact as a shared household fact in one `apply`; returns fact id -> ref."""
    refs = list(data["facts"])
    ids = await memory.apply(household_id, conversation_id,
                             [Add(NewFact(None, None, "shared", False, "other", False, data["facts"][r])) for r in refs], AT)
    return dict(zip(ids, refs, strict=True))


async def score(memory: Memory, household_id: int, refs: dict[int, str], data: dict[str, Any]) -> Scored:
    """Recalls every case's remark and every `nothing` remark for an unknown speaker in the household."""
    asker = Asker(household_id, None, False, AT)
    hits: dict[str, list[bool]] = defaultdict(list)
    returned: list[int] = []
    for case in data["cases"]:
        found = {refs[r.fact.id] for r in await memory.recall(asker, case["ask"])}
        returned.append(len(found))
        hits[case["style"]].append(bool(found & set(case["relevant"])))
    nothing = [len(await memory.recall(asker, ask)) for ask in data["nothing"]]
    return Scored({s: (sum(h), len(h)) for s, h in hits.items()}, sum(returned) / len(returned),
                  sum(nothing) / len(nothing))
