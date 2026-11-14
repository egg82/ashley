"""The signed-in person's open work as `WorkItem`s, each read from the system that owns the record: one-shot errands
(`ashley.errands.errands.Errands.held`), open-ended errands and standing errands (`ashley.senses.wakes.Wakes.reminders`, those with an
`ends_at` and those with a `method`) and open benches with their jobs (`ashley.workshop.workshop.Workshop`, `ashley.errands.bench_jobs.BenchJobs`).
A state is derived from those records' own fields, never from text."""

import asyncio
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import services
from ..errands.bench_job_model import State as JobState
from ..errands.bench_jobs import BenchJobs
from ..errands.errands import Errands
from ..errands.model import Held
from ..people.people import People
from ..senses.repeat import LOCAL_FORMAT
from ..senses.wakes import Scheduled, State as CheckState, Wakes
from ..workshop.model import Bench, Owner
from ..workshop.workshop import BenchNotFound, Workshop
from .work_models import WorkItem, WorkState

ERRANDS_LISTED = 50
_CHECK_STATE: dict[CheckState, WorkState] = {"scheduled": "running", "sending": "running", "undelivered": "waiting_on_you",
                                             "failed": "stopped"}
_RANK = {"waiting_on_you": 0, "running": 1, "open": 2, "stopped": 3, "done": 4}


def errand_item(held: Held) -> WorkItem:
    return WorkItem(kind="errand", id=held.id, title=held.ask, at=held.at,
                    state="done" if held.state == "done" else "running")


def open_errand_item(s: Scheduled, zone: ZoneInfo) -> WorkItem | None:
    r = s.reminder
    if r.ends_at is None:
        return None
    return WorkItem(kind="open_errand", id=s.id, title=r.brief, state=_CHECK_STATE[s.state], at=r.due_at,
                    until_local=r.ends_at.astimezone(zone).strftime(LOCAL_FORMAT))


def standing_errand_item(s: Scheduled) -> WorkItem | None:
    r = s.reminder
    if r.method is None:
        return None
    return WorkItem(kind="standing_errand", id=s.id, title=r.brief, state=_CHECK_STATE[s.state], at=r.due_at)


def bench_item(bench: Bench, jobs: list[JobState], approving: bool) -> WorkItem:
    """`waiting_on_you` when an install awaits approval or a job (by its state) is blocked on the person or `waiting` on their machine;
    else `running` while any job is going, else `open`."""
    if approving or any(j in ("blocked", "waiting") for j in jobs):
        state = "waiting_on_you"
    else:
        state = "running" if jobs else "open"
    return WorkItem(kind="bench", id=bench.id, title=bench.title, state=state,
                    at=bench.last_changed_at or bench.opened_at)


def order(items: list[WorkItem]) -> list[WorkItem]:
    items.sort(key=lambda i: (_RANK[i.state], -_stamp(i.at)))
    return items


def _stamp(at: datetime) -> float:
    return at.timestamp()


async def _approving(owner: Owner, bench_id: int) -> bool:
    try:
        return bool((await services.get(Workshop).read(owner, bench_id)).proposals)
    except BenchNotFound:
        return False


async def open_work(owner: Owner) -> list[WorkItem]:
    """Raises ErrandsUnavailable, WakesUnavailable, JobsUnavailable, WorkshopUnavailable and PeopleUnavailable."""
    household = await services.get(People).household(owner.household_id)
    zone = ZoneInfo("UTC" if household is None else household.timezone)
    benches = await services.get(Workshop).open_benches(owner)
    jobs = await services.get(BenchJobs).unfinished_of(owner.household_id, owner.person_id)
    held = await services.get(Errands).held(owner.person_id, ERRANDS_LISTED)
    scheduled = await services.get(Wakes).reminders(owner.household_id, owner.person_id)
    approving = await asyncio.gather(*(_approving(owner, b.id) for b in benches))
    on_bench: dict[int, list[JobState]] = defaultdict(list)
    for j in jobs:
        on_bench[j.bench_id].append(j.state)
    items = [errand_item(h) for h in held]
    items += [i for i in (open_errand_item(s, zone) for s in scheduled) if i is not None]
    items += [i for i in (standing_errand_item(s) for s in scheduled) if i is not None]
    items += [bench_item(b, on_bench[b.id], a) for b, a in zip(benches, approving)]
    return order(items)
