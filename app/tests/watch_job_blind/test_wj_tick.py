"""One tick: expire, due, one read per (kind, household, person) group, judge, record."""

from dataclasses import replace

from watch_job_blind_support import (CONF, Baseline, Counts, Failed, Quiet, Woke, ReadFailed, harness, refusing, one, run,
                                     watch_of)

S = "s"


def test_a_tick_expires_first_then_asks_what_is_due_with_the_batch() -> None:
    h = harness([], {})

    async def go() -> None:
        await h.tick()
        assert h.store.calls == [("expire", (CONF.keep_s,)), ("due", (CONF.batch,))]
    run(go())


def test_nothing_due_reads_nothing_and_records_nothing() -> None:
    h = harness([], {})

    async def go() -> None:
        await h.tick()
        assert h.kind.groups == [] and h.store.named("record") == []
    run(go())


def test_a_watch_with_no_baseline_records_a_baseline_of_what_was_read() -> None:
    read = one("a", "done", 5)
    h = harness([watch_of(1, baseline=None, target="a")], {1: read})

    async def go() -> None:
        await h.tick()
        assert h.store.named("record") == [(1, 3, Baseline(read))]
    run(go())


def test_each_outcome_is_recorded_for_its_own_watch_at_the_version_it_was_read_at() -> None:
    watches = [watch_of(1, version=4, baseline=one("a", "working", 1), target="a"),
               watch_of(2, version=9, baseline=one("b", "working", 1), target="b"),
               watch_of(3, version=2, baseline=one("c", "done", 1), target="c"),
               watch_of(4, version=6, baseline=one("d", "done", 1), target="d")]
    world = {1: one("a", "done", 2), 2: one("b", "working", 2), 3: ReadFailed("unreachable"), 4: {}}
    h = harness(watches, world)

    async def go() -> None:
        await h.tick()
        got = {i: (v, c) for i, v, c in h.store.named("record")}
        assert got[1][0] == 4 and isinstance(got[1][1], Woke) and got[1][1].ends is False
        assert got[2] == (9, Quiet(False))
        assert got[3] == (2, Failed("unreachable"))
        assert got[4] == (6, Quiet(True))
    run(go())


def test_a_session_that_finished_is_one_wake_with_its_items() -> None:
    read = one("a", "done", 44)
    h = harness([watch_of(1, baseline=one("a", "done", 42), target="a")], {1: read})

    async def go() -> None:
        await h.tick()
        [(_, _, check)] = h.store.named("record")
        assert isinstance(check, Woke) and check.items == read
    run(go())


def test_the_watches_of_one_person_and_kind_share_one_read() -> None:
    watches = [watch_of(i, baseline=one("x", "idle", 1), target="x") for i in (1, 2, 3)]
    h = harness(watches, {i: one("x", "idle", 1) for i in (1, 2, 3)})

    async def go() -> None:
        await h.tick()
        assert h.read_ids() == [[1, 2, 3]] and len(h.store.named("record")) == 3
    run(go())


def test_people_households_and_kinds_are_separate_reads() -> None:
    watches = [watch_of(1), watch_of(2, person_id=8), watch_of(3, household_id=2), watch_of(4, kind="fake"),
               watch_of(5)]
    h = harness(watches, {i: {} for i in range(1, 6)})

    async def go() -> None:
        await h.tick()
        assert sorted(h.read_ids()) == [[1, 5], [2], [3], [4]]
        for g in h.kind.groups:
            assert {(w.kind, w.household_id, w.person_id) for w in g.watches} == {(g.kind, g.household_id, g.person_id)}
    run(go())


def test_only_one_batch_of_what_is_due_is_read_and_recorded() -> None:
    watches = [watch_of(i, target=f"t{i}") for i in range(1, 7)]
    h = harness(watches, {i: {} for i in range(1, 7)}, replace(CONF, batch=2))

    async def go() -> None:
        await h.tick()
        assert sorted(h.store.checks()) == [1, 2]
    run(go())


def test_an_unknown_kind_fails_its_watches_unknown_kind_and_the_others_still_run() -> None:
    watches = [watch_of(1, kind="no-such-kind", person_id=9), watch_of(2)]
    h = harness(watches, {2: {}})

    async def go() -> None:
        await h.tick()
        assert h.store.checks()[1] == Failed("unknown_kind") and 2 in h.store.checks()
    run(go())


def test_a_paused_watch_is_still_read_and_a_good_read_is_diffed_against_its_old_baseline() -> None:
    paused = watch_of(1, state="paused", reason="unreachable", failures=3, baseline=one("a", "working", 1), target="a")
    h = harness([paused], {1: one("a", "done", 5)})

    async def go() -> None:
        await h.tick()
        assert isinstance(h.store.checks()[1], Woke)
    run(go())


def test_a_record_the_store_refuses_does_not_stop_the_other_watches() -> None:
    watches = [watch_of(1, target="a"), watch_of(2, target="b", person_id=8)]
    h = harness(watches, {1: {}, 2: {}})
    h.store.recorded = refusing(1)

    async def go() -> None:
        await h.tick()
        assert sorted(h.store.checks()) == [1, 2]
    run(go())


def test_counts_from_expire_are_not_needed_to_continue() -> None:
    h = harness([watch_of(1)], {1: {}})
    h.store.counts = Counts(5, 7)

    async def go() -> None:
        await h.tick()
        assert 1 in h.store.checks()
    run(go())
