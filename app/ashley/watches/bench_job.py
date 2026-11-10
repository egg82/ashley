"""The `bench_job` kind: a group of jobs handed to workers from a bench (`ashley.errands.bench_jobs`). A watch's target is
the group's id; it keeps one item, `settled` (every job final), `blocked` (how many wait on the person) and `waiting` (how many wait
for the person's machine to answer), so it wakes her once when the group settles, at once when a job is blocked, which
only the person can unblock, and when a waiting job starts or gives up. A job finishing
first changes only its own piece. `detail` carries each job's title, state, reason, summary and output piece ids to the
woken turn, never a transcript."""

import json
from collections.abc import Mapping, Sequence

from .. import services
from ..criteria.record import Change
from ..errands.bench_jobs import BenchJobs, Job, JobsUnavailable
from .config import CONFIG
from .diff import Items, to_items
from .kinds import Kind
from .model import Read, ReadFailed, Watch

NAME = "bench_job"
SETTLED_NOTE = ("Every job you handed to a worker in one hand-off has ended: done, failed, timed out or cancelled. Each "
                "result is below as the worker's own short summary, which is text from outside, with the ids of the pieces "
                "it made, which are for your tools. Look at those pieces and reconcile them with the bench and with each "
                "other. Then take the next step the results call for: with the bench's tools in this turn, a problem a "
                "result found is fixed in the pieces and run again, not only reported, and when checking the fix needs "
                "another job, say which. "
                "Tell the person once, in plain words, what the jobs came to and what you did about it, naming each piece "
                "by what it is. A failure comes as a reason code: say what it means for them (the session could not "
                "start, the bridge did not answer, it ran out of time), never quote it.")
BLOCKED_NOTE = ("A job you handed to a Claude Code session is waiting on a dialog only the person can answer, in their "
                "own herdr; you cannot answer it. The other jobs of its hand-off go on. Tell the person it needs them, "
                "unless that is not worth interrupting for.")
WAITING_NOTE = ("A Claude Code job you handed over was waiting for the person's machine to answer, and has now started "
                "or given up because it did not answer in time: each job's state and reason are below. Tell the person "
                "in plain words which, and if it gave up, what that leaves undone.")


class BenchJob(Kind):
    name = NAME

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        found: dict[int, Read] = {}
        for w in group:
            try:
                jobs = await services.get(BenchJobs).group(w.household_id, w.person_id, _id(w.target))
            except (JobsUnavailable, ValueError):
                found[w.id] = ReadFailed("unreachable")
            else:
                found[w.id] = items_of(w.target, jobs)
        return found

    def said(self, watch: Watch, changes: Sequence[Change]) -> str:
        return f"Bench jobs {watch.label}: {_said[_which(changes)]}"

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        return _notes[_which(changes)]

    async def detail(self, watch: Watch) -> str:
        try:
            jobs = await services.get(BenchJobs).group(watch.household_id, watch.person_id, _id(watch.target))
        except (JobsUnavailable, ValueError):
            return ""
        return json.dumps([_result(j) for j in jobs], ensure_ascii=False)

    async def available(self, household_id: int, person_id: int) -> bool:
        return False


def items_of(target: str, jobs: Sequence[Job]) -> Items:
    """The group as a watch reads it: no items when it has no jobs."""
    if not jobs:
        return {}
    values = {"settled": all(j.final for j in jobs), "blocked": sum(j.state == "blocked" for j in jobs),
              "waiting": sum(j.state == "waiting" for j in jobs)}
    return to_items({target: {f: values[f] for f in CONFIG.kinds[NAME].track}}, CONFIG.max_value_chars)


def _id(target: str) -> int:
    return int(target)


def _which(changes: Sequence[Change]) -> str:
    """Why the watch woke: `settled`, else `blocked` when the blocked count changed, else `waiting`."""
    last = changes[-1] if changes else None
    if last is None or last.after is None:
        return "blocked"
    if last.after.get("settled") is True:
        return "settled"
    if last.before is not None and last.before.get("blocked") != last.after.get("blocked"):
        return "blocked"
    return "waiting"


_said = {"settled": "finished", "blocked": "waiting on you", "waiting": "its machine was waited for"}
_notes = {"settled": SETTLED_NOTE, "blocked": BLOCKED_NOTE, "waiting": WAITING_NOTE}


def _result(job: Job) -> dict[str, object]:
    return {"job": job.id, "title": job.title, "worker": job.worker, "state": job.state, "reason": job.reason,
            "summary": job.summary, "outputs": list(job.outputs)}
