"""The watches table through `PostgresWatches`: arming (a live watch is updated, not duplicated), `record`'s version
condition and each check's effect, the wake a `Woke` or a pause stores, `due`, `expire`, and the Null Object."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley.criteria.condition import Condition
from ashley.criteria.items import ItemPredicate
from ashley.criteria.record import Change
from ashley.db.pool import PoolDatabase
from ashley.watches.config import CONFIG, WatchesConfig
from ashley.watches.model import Arm, Baseline, Failed, Quiet, Woke
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import NullWatches, Watches, WatchesUnavailable
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar

WHEN: Condition = ((ItemPredicate("changed", field="seq"),),)
ITEMS = {"s1": {"status": "working", "seq": 1}}


def arm_for(home: int, who: int, **over: object) -> Arm:
    base = Arm(home, who, "claude_session", "s1", "the build", None, "ashley", ("status", "seq"), WHEN, None, None, 15,
               datetime.now(UTC) + timedelta(hours=1))
    return replace(base, **over)


@asynccontextmanager
async def store(url: str, config: WatchesConfig = CONFIG) -> AsyncGenerator[Watches]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWatches(db, config)
    finally:
        await db.close()


def test_arm_twice_updates_the_live_watch_and_keeps_its_baseline(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            first = await w.arm(arm_for(home, who, baseline=ITEMS, armed_by="handoff", bench_id=7))
            assert first.new
            assert await w.record(first.id, 0, Baseline(ITEMS))
            later = datetime.now(UTC) + timedelta(hours=9)
            again = await w.arm(arm_for(home, who, tools=("a",), interval_s=30, expires_at=later, bench_id=8))
            assert (again.id, again.new) == (first.id, False)
            got = await w.get(first.id)
            assert got is not None and (got.armed_by, got.tools, got.interval_s, got.bench_id) == ("handoff", ("a",), 30, 8)
            assert (got.expires_at, got.version, got.baseline) == (later, 1, ITEMS)
    run(go())
    assert scalar(db_url, "SELECT count(*) FROM watches") == 1


@pytest.mark.parametrize("over", [
    {"when": ((ItemPredicate("changed", field="label"),),)},
    {"until": ((ItemPredicate("gone"),) * 7,)},
    {"when": ((ItemPredicate("gone"),),) * 5},
    {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
    {"target": ""}, {"label": "x" * 101}, {"interval_s": 0}, {"person_id": 0}])
def test_arm_refuses_before_writing(db_url: str, over: dict[str, object]) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            with pytest.raises(ValueError):
                await w.arm(arm_for(home, who, **({"person_id": who + 99} if "person_id" in over else over)))
    run(go())
    assert scalar(db_url, "SELECT count(*) FROM watches") == 0


def test_arm_past_max_live_is_refused_only_for_a_new_watch(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url, replace(CONFIG, max_live=1)) as w:
            await w.arm(arm_for(home, who))
            await w.arm(arm_for(home, who, interval_s=20))
            with pytest.raises(ValueError):
                await w.arm(arm_for(home, who, target="s2"))
    run(go())


def test_disarm_ends_the_live_watch_once_and_a_new_arm_is_new(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            a = await w.arm(arm_for(home, who))
            assert not await w.disarm(home, who, "claude_session", "other")
            assert await w.disarm(home, who, "claude_session", "s1")
            assert not await w.disarm(home, who, "claude_session", "s1")
            gone = await w.get(a.id)
            assert gone is not None and (gone.state, gone.reason) == ("ended", "disarmed")
            assert await w.live(home, who) == ()
            b = await w.arm(arm_for(home, who))
            assert b.new and b.id != a.id
    run(go())


def test_live_is_soonest_expiry_first_and_get_of_nothing_is_none(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            late = await w.arm(arm_for(home, who, target="a", expires_at=datetime.now(UTC) + timedelta(hours=5)))
            soon = await w.arm(arm_for(home, who, target="b"))
            assert [x.id for x in await w.live(home, who)] == [soon.id, late.id]
            assert await w.get(0) is None
    run(go())


def test_record_at_a_stale_version_changes_nothing(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            a = await w.arm(arm_for(home, who))
            assert await w.record(a.id, 0, Baseline(ITEMS))
            assert not await w.record(a.id, 0, Baseline({}))
            assert not await w.record(a.id, 0, Failed("refused"))
            got = await w.get(a.id)
            assert got is not None and (got.version, got.baseline, got.failures) == (1, ITEMS, 0)
    run(go())


def test_woke_stores_baseline_and_one_wake_and_a_repeat_stores_none(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    after = {"s1": {"status": "done", "seq": 2}}
    change = Change("s1", "changed", ITEMS["s1"], after["s1"])

    async def go() -> None:
        async with store(db_url) as w:
            a = await w.arm(arm_for(home, who, baseline=ITEMS))
            assert await w.record(a.id, 0, Woke(after, (change,), False))
            assert not await w.record(a.id, 0, Woke(after, (change,), False))
            got = await w.get(a.id)
            assert got is not None
            assert (got.version, got.series, got.baseline, got.state) == (1, 1, after, "armed")
            assert got.last_woke_at is not None
            assert await w.due(10) == ()
        assert scalar(db_url, "SELECT event_id FROM wakes") == f"watch:{a.id}:1"
        assert scalar(db_url, "SELECT count(*) FROM wakes") == 1
        wake = scalar(db_url, "SELECT changes FROM wakes")
        assert wake["series"] == 1 and wake["ended"] is None and wake["what"] == "changed"
        assert wake["items"] == [{"id": "s1", "kind": "changed", "before": ITEMS["s1"], "after": after["s1"]}]
        assert datetime.fromisoformat(wake["since"]) == scalar(db_url, "SELECT armed_at FROM watches")
    run(go())
    assert scalar(db_url, "SELECT kind || '/' || what FROM wakes") == "watch/changed"
    assert scalar(db_url, "SELECT person_id = %s AND device_id IS NULL AND watch_id IS NOT NULL FROM wakes", (who,))


def test_woke_that_ends_ends_until_and_still_tells(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            a = await w.arm(arm_for(home, who))
            assert await w.record(a.id, 0, Woke(ITEMS, (Change("s1", "new", None, ITEMS["s1"]),), True))
            got = await w.get(a.id)
            assert got is not None and (got.state, got.reason, got.series) == ("ended", "until", 1)
            assert got.ended_at is not None
    run(go())
    assert scalar(db_url, "SELECT changes->>'ended' FROM wakes") == "until"


def test_quiet_keeps_the_baseline_and_ends_when_told(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            a = await w.arm(arm_for(home, who, baseline=ITEMS))
            assert await w.record(a.id, 0, Quiet(False))
            got = await w.get(a.id)
            assert got is not None and (got.version, got.baseline, got.state) == (0, ITEMS, "armed")
            assert await w.record(a.id, 0, Quiet(True))
            ended = await w.get(a.id)
            assert ended is not None and (ended.state, ended.reason) == ("ended", "until")
            assert not await w.record(a.id, 0, Quiet(False))
    run(go())
    assert scalar(db_url, "SELECT count(*) FROM wakes") == 0


def test_failures_pause_at_fail_after_with_one_paused_wake_and_a_success_resumes(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url, replace(CONFIG, fail_after=2, retry_s=300)) as w:
            a = await w.arm(arm_for(home, who, baseline=ITEMS))
            assert await w.record(a.id, 0, Failed("unreachable"))
            first = await w.get(a.id)
            assert first is not None and (first.state, first.failures, first.reason) == ("armed", 1, None)
            assert await w.record(a.id, 0, Failed("refused"))
            paused = await w.get(a.id)
            assert paused is not None and (paused.state, paused.failures, paused.reason) == ("paused", 2, "refused")
            assert paused.next_check_at > datetime.now(UTC) + timedelta(seconds=200)
            assert await w.record(a.id, 0, Failed("bad_result"))
            again = await w.get(a.id)
            assert again is not None and (again.state, again.reason, again.failures) == ("paused", "bad_result", 3)
            assert [x.id for x in await w.live(home, who)] == [a.id]
            assert await w.record(a.id, 0, Quiet(False))
            back = await w.get(a.id)
            assert back is not None and (back.state, back.reason, back.failures) == ("armed", None, 0)
            assert back.baseline == ITEMS
    run(go())
    assert scalar(db_url, "SELECT count(*) FROM wakes") == 1
    assert scalar(db_url, "SELECT (what, changes->>'reason') FROM wakes") == ("paused", "refused")


def test_due_skips_future_expired_and_watches_with_an_unsettled_wake(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            ready = await w.arm(arm_for(home, who, target="ready"))
            waiting = await w.arm(arm_for(home, who, target="waiting"))
            await w.arm(arm_for(home, who, target="later"))
            await w.arm(arm_for(home, who, target="stale"))
            scalar(db_url, "UPDATE watches SET next_check_at = now() + interval '1 hour' WHERE target = 'later' "
                           "RETURNING 1")
            scalar(db_url, "UPDATE watches SET expires_at = now() - interval '1 second' WHERE target = 'stale' "
                           "RETURNING 1")
            assert await w.record(waiting.id, 0, Woke(ITEMS, (Change("s1", "new", None, ITEMS["s1"]),), False))
            scalar(db_url, "UPDATE watches SET next_check_at = now() - interval '1 minute' WHERE id = %s RETURNING 1",
                   (waiting.id,))
            assert [x.id for x in await w.due(10)] == [ready.id]
            scalar(db_url, "UPDATE wakes SET settled_at = now(), outcome = 'turn' RETURNING 1")
            assert {x.id for x in await w.due(10)} == {ready.id, waiting.id}
            assert len(await w.due(1)) == 1
    run(go())


def test_expire_ends_past_expiry_and_prunes_only_old_ended_watches_without_an_unsettled_wake(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as w:
            for t in ("past", "kept", "open", "live"):
                await w.arm(arm_for(home, who, target=t))
            scalar(db_url, "UPDATE watches SET expires_at = now() - interval '1 second' WHERE target = 'past' "
                           "RETURNING 1")
            assert (await w.expire(3600)).expired == 1
            ended = {t: await w.disarm(home, who, "claude_session", t) for t in ("kept", "open")}
            assert all(ended.values())
            open_id = int(scalar(db_url, "SELECT id FROM watches WHERE target = 'open'"))
            scalar(db_url, "INSERT INTO wakes (household_id, kind, event_id, event, person_id, watch_id, changes, at) "
                           "VALUES (%s, 'watch', 'watch:x:1', 'watch', %s, %s, '{}', now()) RETURNING 1",
                   (home, who, open_id))
            scalar(db_url, "UPDATE watches SET ended_at = now() - interval '2 hours' WHERE state = 'ended' "
                           "RETURNING 1")
            counts = await w.expire(3600)
            assert (counts.expired, counts.pruned) == (0, 2)
    run(go())
    assert sorted(r for r in [scalar(db_url, "SELECT string_agg(target, ',' ORDER BY target) FROM watches")]) == [
        "live,open"]


def test_the_null_object_raises_on_every_method() -> None:
    null = Watches.null()
    assert isinstance(null, NullWatches)

    async def go() -> None:
        calls = [null.arm(arm_for(1, 1)), null.disarm(1, 1, "k", "t"), null.live(1, 1), null.get(1), null.due(1),
                 null.record(1, 0, Quiet(False)), null.expire(1)]
        for c in calls:
            with pytest.raises(WatchesUnavailable):
                await c
    run(go())
