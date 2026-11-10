"""The `bench_job` watch kind: a group reads as one item that is `settled` once every job is final and counts the
jobs `blocked`, never from anything the jobs hold; a group with no jobs reads as gone; the woken turn's note says which
of the two happened and carries each job's result only through `detail`."""

from datetime import UTC, datetime

from ashley.errands.bench_jobs import Job, State
from ashley.watches.bench_job import BenchJob, items_of
from ashley.watches.config import CONFIG
from ashley.watches.diff import Items

NOW = datetime(2026, 11, 8, tzinfo=UTC)


def job(state: State, n: int = 1) -> Job:
    return Job(n, 1, 1, 1, 1, 1, 7, "agent", "t", "b", (), (), 1, state, 1, None, 0, None, NOW, None, None, None,
               None, (), 0)


def test_a_group_is_settled_only_when_every_job_is_final_and_counts_blocked() -> None:
    def read(states: list[State]) -> Items:
        return items_of("7", [job(s, i) for i, s in enumerate(states)])

    assert read(["done", "running"]) == {"7": {"settled": False, "blocked": 0, "waiting": 0}}
    assert read(["done", "failed", "timed_out", "cancelled"]) == {"7": {"settled": True, "blocked": 0, "waiting": 0}}
    assert read(["blocked", "blocked", "done"]) == {"7": {"settled": False, "blocked": 2, "waiting": 0}}
    assert read(["waiting", "due", "waiting"]) == {"7": {"settled": False, "blocked": 0, "waiting": 2}}
    assert items_of("7", []) == {}


def test_the_kind_is_outside_and_tracks_what_the_data_says() -> None:
    kind = BenchJob()
    assert kind.outside is True and CONFIG.kinds["bench_job"].track == ("settled", "blocked", "waiting")


def test_the_note_says_which_of_settled_blocked_or_waiting_changed() -> None:
    from ashley.criteria.record import Change
    from ashley.watches.bench_job import BLOCKED_NOTE, SETTLED_NOTE, WAITING_NOTE
    from watch_job_support import watch as make

    kind = BenchJob()
    watch = make(1, kind="bench_job", target="7")

    def change(before: dict[str, int | bool], after: dict[str, int | bool]) -> list[Change]:
        return [Change("7", "changed", before, after)]

    quiet = {"settled": False, "blocked": 0, "waiting": 0}
    assert kind.note(watch, change({**quiet, "waiting": 1}, quiet)) == WAITING_NOTE
    assert kind.note(watch, change({**quiet, "waiting": 1}, {**quiet, "settled": True})) == SETTLED_NOTE
    assert kind.note(watch, change({**quiet, "waiting": 1}, {**quiet, "blocked": 1})) == BLOCKED_NOTE
