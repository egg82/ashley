"""The `tool` kind of watch against a scripted ToolReads: how a tool's answer becomes items, what the judge and the job
make of successive reads (baseline, quiet, new, changed and gone), and how a failed read is told from an empty one."""

import asyncio
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.criteria.record import Change
from ashley.watches import job
from ashley.watches.config import CONFIG
from ashley.watches.diff import Items
from ashley.watches.judge import judge
from ashley.watches.kinds import Registry
from ashley.watches.model import Baseline, Failed, Quiet, ReadFailed, Watch, Woke
from ashley.watches.tool_items import items_of
from ashley.watches.tool_reads import Text, ToolRead, ToolReads
from ashley.watches.tool_target import HASH, WHOLE, ReadSpec, parse, target_of
from ashley.watches.tool_watch import ToolWatch
from ashley.watches.watches import Watches
from watch_job_support import FakeWatches, watch

TOOL = CONFIG.kinds["tool"]
EVENTS = ReadSpec("house_ask", {"action": "calendar.get_events", "ids": ["calendar.home"]}, ("summary", "start"),
                  ("response", "calendar.home", "events"))
WHOLE_ANSWER = ReadSpec("house_ask", {"action": "todo.get_items"}, (HASH,))


def answer(*events: Mapping[str, object]) -> str:
    return '{"done":true,"response":{"calendar.home":{"events":%s}}}' % json.dumps(list(events))


def event(summary: str, start: str = "2026-11-20T09:00", **more: object) -> dict[str, object]:
    return {"summary": summary, "start": start, "end": "2026-11-20T10:00", **more}


@dataclass
class FakeReads(ToolReads):
    """Answers `answers` in turn (the last one repeats) and remembers each call."""

    answers: list[ToolRead] = field(default_factory=list[ToolRead])
    calls: list[tuple[int, int, str, Mapping[str, object]]] = field(default_factory=list[tuple[int, int, str, Mapping[str, object]]])

    async def available(self, household_id: int, person_id: int) -> bool:
        return True

    async def read(self, household_id: int, person_id: int, tool: str, arguments: Mapping[str, object]) -> ToolRead:
        self.calls.append((household_id, person_id, tool, arguments))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def tool_watch(spec: ReadSpec = EVENTS, baseline: Items | None = None, *, failures: int = 0, version: int = 0) -> Watch:
    base = watch(kind="tool", target=target_of(spec), when=TOOL.when, failures=failures, version=version)
    return replace(base, track=spec.track, baseline=baseline)


def read_of(text: str, spec: ReadSpec = EVENTS) -> Items:
    got = items_of(text, spec)
    assert not isinstance(got, ReadFailed)
    return got


def failed_read(text: str, spec: ReadSpec = EVENTS) -> ReadFailed:
    got = items_of(text, spec)
    assert isinstance(got, ReadFailed)
    return got


def test_each_list_entry_is_an_item_keyed_by_the_first_tracked_field_holding_only_tracked_fields() -> None:
    got = read_of(answer(event("Dentist", description="floss"), event("Trip", "2026-12-01")))
    assert got == {"Dentist": {"summary": "Dentist", "start": "2026-11-20T09:00"},
                   "Trip": {"summary": "Trip", "start": "2026-12-01"}}


def test_an_untracked_field_changing_is_no_change_at_all() -> None:
    held = read_of(answer(event("Dentist", description="floss")))
    assert judge(read_of(answer(event("Dentist", description="brush"))), tool_watch(baseline=held)) == Quiet(False)


def test_the_first_read_is_a_baseline_and_waking_needs_a_difference_from_it() -> None:
    first = read_of(answer(event("Dentist")))
    assert judge(first, tool_watch()) == Baseline(first)
    assert judge(first, tool_watch(baseline=first)) == Quiet(False)


def test_a_new_a_changed_and_a_gone_item_each_wake_with_their_before_and_after() -> None:
    held = read_of(answer(event("Dentist"), event("Trip", "2026-12-01"), event("Gym", "2026-11-21")))
    now = read_of(answer(event("Dentist", "2026-11-20T11:00"), event("Gym", "2026-11-21"), event("Party", "2026-11-22")))
    woke = judge(now, tool_watch(baseline=held))
    assert isinstance(woke, Woke) and not woke.ends
    assert woke.changes == (
        Change("Dentist", "changed", {"summary": "Dentist", "start": "2026-11-20T09:00"},
               {"summary": "Dentist", "start": "2026-11-20T11:00"}),
        Change("Party", "new", None, {"summary": "Party", "start": "2026-11-22"}),
        Change("Trip", "gone", {"summary": "Trip", "start": "2026-12-01"}, None))
    assert woke.items == now


def test_an_empty_list_is_a_valid_read_and_every_item_leaving_it_is_gone() -> None:
    held = read_of(answer(event("Dentist")))
    woke = judge(read_of(answer()), tool_watch(baseline=held))
    assert isinstance(woke, Woke) and [c.kind for c in woke.changes] == ["gone"]


def test_entries_that_share_a_name_are_told_apart_by_order() -> None:
    got = read_of(answer(event("Standup"), event("Standup", "2026-11-21"), event("Standup", "2026-11-22")))
    assert list(got) == ["Standup", "Standup#2", "Standup#3"]


def test_the_whole_answer_as_one_item_wakes_on_any_change_and_ignores_key_order() -> None:
    a, b = '{"x":1,"y":[1,2]}', '{"y":[1,2],"x":1}'
    held = read_of(a, WHOLE_ANSWER)
    assert list(held) == [WHOLE]
    assert held == read_of(b, WHOLE_ANSWER)
    assert judge(read_of(b, WHOLE_ANSWER), tool_watch(WHOLE_ANSWER, held)) == Quiet(False)
    woke = judge(read_of('{"x":2,"y":[1,2]}', WHOLE_ANSWER), tool_watch(WHOLE_ANSWER, held))
    assert isinstance(woke, Woke) and [c.kind for c in woke.changes] == ["changed"]


@pytest.mark.parametrize("text", ["not json", '{"response":{}}', '{"response":{"calendar.home":{"events":"soon"}}}',
                                  '{"response":{"calendar.home":{"events":[1]}}}'])
def test_an_answer_that_does_not_hold_the_list_fails_bad_result_never_as_every_item_gone(text: str) -> None:
    got = failed_read(text)
    assert got == ReadFailed("bad_result")
    assert judge(got, tool_watch(baseline=read_of(answer(event("Dentist"))))) == Failed("bad_result")


def test_more_items_than_a_watch_holds_fail_too_many_items() -> None:
    many = answer(*[event(f"e{i}") for i in range(CONFIG.max_items + 1)])
    assert failed_read(many) == ReadFailed("too_many_items")
    assert len(read_of(answer(*[event(f"e{i}") for i in range(CONFIG.max_items)]))) == CONFIG.max_items


def test_a_target_round_trips_and_is_the_same_whatever_order_its_arguments_came_in() -> None:
    other = replace(EVENTS, arguments={"ids": ["calendar.home"], "action": "calendar.get_events"})
    assert target_of(other) == target_of(EVENTS) and parse(target_of(EVENTS)) == EVENTS


def test_a_calendar_read_with_a_week_of_data_fits_a_target() -> None:
    spec = replace(EVENTS, arguments={**EVENTS.arguments, "data": '{"duration":{"days":7}}'},
                   track=("summary", "start", "end", "location"))
    assert len(target_of(spec)) <= 500


def run_tick(store: FakeWatches, reads: FakeReads) -> Counter[str]:
    services.register(Watches, store)
    services.register(ToolReads, reads)
    try:
        return asyncio.run(job.tick(CONFIG, Registry([ToolWatch()])))
    finally:
        services.unregister(ToolReads)
        services.unregister(Watches)


def test_the_job_baselines_stays_quiet_then_wakes_on_a_change_with_one_read_per_watch() -> None:
    store, reads = FakeWatches(due_rows=(tool_watch(),)), FakeReads([Text(answer(event("Dentist")))])
    assert run_tick(store, reads)["baselines"] == 1
    held = read_of(answer(event("Dentist")))
    store.due_rows = (tool_watch(baseline=held, version=1),)
    assert run_tick(store, reads)["quiet"] == 1
    reads.answers = [Text(answer(event("Dentist"), event("Trip")))]
    counts = run_tick(store, reads)
    assert counts["woke"] == 1 and isinstance(store.recorded[-1][2], Woke)
    assert len(reads.calls) == 3 and reads.calls[0] == (1, 7, "house_ask", EVENTS.arguments)


def test_a_tool_that_cannot_be_read_records_a_failure_with_its_reason_and_keeps_the_baseline() -> None:
    held = read_of(answer(event("Dentist")))
    store = FakeWatches(due_rows=(tool_watch(baseline=held, failures=2, version=1),))
    counts = run_tick(store, FakeReads([ReadFailed("refused")]))
    assert counts["failed"] == 1 and store.recorded == [(1, 1, Failed("refused"))]


def test_a_watch_whose_target_is_not_a_read_fails_bad_result() -> None:
    store = FakeWatches(due_rows=(replace(tool_watch(), target="{not json"),))
    run_tick(store, FakeReads([Text("{}")]))
    assert store.recorded == [(1, 0, Failed("bad_result"))]


def test_the_wake_says_the_counts_and_tells_her_each_change_as_outside_text() -> None:
    kind = ToolWatch()
    changes = (Change("Party", "new", None, {"summary": "Party", "start": "x"}),
               Change("Trip", "gone", {"summary": "Trip", "start": "y"}, None))
    w = replace(tool_watch(), label="house_ask calendar.get_events")
    assert kind.said(w, changes) == "Watch house_ask calendar.get_events: 1 new, 1 gone"
    note = kind.note(w, changes)
    assert '"item": "Party"' in note and '"is": "gone"' in note and "not instructions" in note
    assert kind.outside is True
    assert asyncio.run(kind.label(w)) == "house_ask calendar.get_events"

