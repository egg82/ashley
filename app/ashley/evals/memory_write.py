"""The memory write eval against the live model: `InferenceFactWriter` graded by the model judge over
`write_cases.json`, with what its calls cost read back from the spend ledger rows it created.

The report ends with one `answered:` line per task, provider, model and outcome.
Logs `eval.memory_write` once per run: cases, runs per case, passes, calls, unpriced calls, cost_usd, duration_ms.
Never a case's text or the model's."""

import logging
import time
from dataclasses import dataclass

from .. import logs, services
from ..db.database import Database
from ..inference.model import TaskName
from ..inference.postgres import Spent, SpentBy, last_call_id, spent_after, spent_by_after
from ..memory.eval import judge, write
from ..memory.eval.people import CasePeople
from ..memory.inference_writer import InferenceFactWriter
from ..people.people import People

log = logging.getLogger("ashley.evals")

TASKS: tuple[TaskName, ...] = ("memory_write", "memory_judge")


@dataclass(frozen=True)
class Outcome:
    report: write.WriteReport
    spent: Spent
    by: list[SpentBy]


async def run(runs: int, only: str | None) -> Outcome:
    """The cases (`only` that one) `runs` times each, with `People` answering the cases' household. Needs `Database`
    and `Inference` wired and the database open. Raises ValueError, before any case runs, when the judge gets one of
    its controls wrong: a score from a judge that cannot tell facts apart would be a number about nothing."""
    data = write.load()
    if only is not None and only not in {c["id"] for c in data["cases"]}:
        raise ValueError(f"no write case {only!r}")
    services.register(People, CasePeople(data))
    database = services.get(Database)
    mark = await last_call_id(database)
    started = time.perf_counter()
    if failed := await judge.failed_controls():
        raise ValueError("the judge failed its controls, so no score:\n  " + "\n  ".join(failed))
    report = await write.run_write(InferenceFactWriter(), judge.judge, runs, only=only)
    spent = await spent_after(database, mark, TASKS)
    logs.info(log, "eval.memory_write", cases=len(report.cases), runs=runs,
              passes=sum(c.passes for c in report.cases), calls=spent.calls, unpriced=spent.unpriced,
              cost_usd=str(spent.cost_usd), duration_ms=int((time.perf_counter() - started) * 1000))
    return Outcome(report, spent, await spent_by_after(database, mark, TASKS))


def render(outcome: Outcome) -> str:
    """Per case its passes and failures, a known-failing case marked, per source its rate, then the spend."""
    lines = [f"{c.passes}/{c.runs}  {c.rate:4.0%}  {c.source:8}  {c.case_id}{'  (known failing)' if c.known_failing else ''}"
             for c in outcome.report.cases]
    for c in outcome.report.cases:
        lines += [f"  {c.case_id}: {f}" for f in c.failures]
    lines += [f"{source}: {rate:.0%}" for source, rate in sorted(outcome.report.by_source().items())]
    lines += _answered(outcome.by)
    return "\n".join(lines)


def _cost(spent: Spent) -> str:
    return f"${spent.cost_usd:.4f}" + (f", plus {spent.unpriced} with no price" if spent.unpriced else "")


def _answered(by: list[SpentBy]) -> list[str]:
    """One line per (task, provider, model, outcome), and a MIXED line for a task more than one provider answered."""
    lines = [f"answered: {b.task} {b.provider} {b.model} {b.outcome}: {b.spent.calls} calls, {_cost(b.spent)}"
             for b in by]
    for task in sorted({b.task for b in by}):
        providers = sorted({b.provider for b in by if b.task == task})
        if len(providers) > 1:
            lines.append(f"MIXED: {task} was answered by {', '.join(providers)}; the pass rate is not one model's")
    return lines
