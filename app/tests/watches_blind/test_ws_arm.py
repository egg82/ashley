"""arm: a new watch is stored armed; the same live target again updates it and keeps what the checks earned."""

from watches_blind_support import (FAIL_AFTER, INTERVAL_S, KIND, TRACK, UNTIL_GONE, World, armed_id, armed_new,
                                   baseline, cond, count, failed, in_hours, make_arm, pred, row, scenario, woke)


def test_arm_stores_an_armed_watch_with_what_it_was_given(db_url: str) -> None:
    async def body(w: World) -> None:
        until = UNTIL_GONE
        expires = in_hours(5)
        armed = await w.store.arm(make_arm(w, "s1", until=until, tools=("lights",), expires_at=expires, bench_id=None,
                                           label="my session", armed_by="handoff"))
        assert armed_new(armed) is True
        r = row(w.url, armed_id(armed))
        assert (r["household_id"], r["person_id"], r["kind"], r["target"]) == (w.hid, w.owner, KIND, "s1")
        assert (r["label"], r["armed_by"], r["state"], r["reason"]) == ("my session", "handoff", "armed", None)
        assert list(r["track"]) == list(TRACK) and list(r["tools"]) == ["lights"]
        assert r["interval_s"] == INTERVAL_S
        assert abs((r["expires_at"] - expires).total_seconds()) < 1
        assert (r["failures"], r["version"], r["series"], r["baseline"]) == (0, 0, 0, None)
        assert len(r["when_clauses"]) == 1 and len(r["until_clauses"]) == 1 and r["until_clauses"][0][0]["kind"] == "gone"
        assert r["armed_at"] is not None and r["ended_at"] is None and r["last_woke_at"] is None

    scenario(db_url, body)


def test_arm_without_until_or_tools_stores_nulls(db_url: str) -> None:
    async def body(w: World) -> None:
        r = row(w.url, await w.arm())
        assert r["until_clauses"] is None and r["tools"] is None and r["bench_id"] is None

    scenario(db_url, body)


def test_arm_stores_the_baseline_it_is_given(db_url: str) -> None:
    async def body(w: World) -> None:
        items = {"s1": {"status": "working", "seq": 7}}
        r = row(w.url, await w.arm(items=items))
        assert r["baseline"] == items

    scenario(db_url, body)


def test_arm_the_same_target_again_updates_the_one_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        first = await w.store.arm(make_arm(w, "s1", interval_s=30, tools=None, expires_at=in_hours(2)))
        later = in_hours(9)
        second = await w.store.arm(make_arm(w, "s1", until=UNTIL_GONE, tools=("lights",), interval_s=90,
                                            expires_at=later, when=cond((pred("new"),))))
        assert armed_id(second) == armed_id(first) and armed_new(second) is False
        assert count(w.url) == 1
        r = row(w.url, armed_id(first))
        assert r["interval_s"] == 90 and list(r["tools"]) == ["lights"]
        assert abs((r["expires_at"] - later).total_seconds()) < 1
        assert r["until_clauses"][0][0]["kind"] == "gone" and r["when_clauses"][0][0]["kind"] == "new"

    scenario(db_url, body)


def test_arm_again_moves_the_bench(db_url: str) -> None:
    async def body(w: World) -> None:
        first = await w.arm(bench_id=7)
        assert row(w.url, first)["bench_id"] == 7
        await w.arm(bench_id=8)
        assert row(w.url, first)["bench_id"] == 8

    scenario(db_url, body)


def test_arm_again_keeps_baseline_version_and_series(db_url: str) -> None:
    async def body(w: World) -> None:
        wid, version = await w.armed_due(items={"s1": {"seq": 1}})
        assert await w.store.record(wid, version, woke({"s1": {"seq": 2}}))
        before = row(w.url, wid)
        assert (before["version"], before["series"], before["baseline"]) == (1, 1, {"s1": {"seq": 2}})
        again = await w.store.arm(make_arm(w, "s1", items={"s1": {"seq": 99}}, interval_s=77))
        assert armed_id(again) == wid and armed_new(again) is False
        after = row(w.url, wid)
        assert (after["version"], after["series"], after["baseline"]) == (1, 1, {"s1": {"seq": 2}})
        assert after["interval_s"] == 77 and after["last_woke_at"] == before["last_woke_at"]

    scenario(db_url, body)


def test_arm_again_after_a_baseline_check_keeps_the_version(db_url: str) -> None:
    async def body(w: World) -> None:
        wid, version = await w.armed_due()
        assert await w.store.record(wid, version, baseline({"s1": {"seq": 1}}))
        await w.arm()
        assert version_and_baseline(w.url, wid) == (1, {"s1": {"seq": 1}})

    scenario(db_url, body)


def version_and_baseline(url: str, wid: int) -> tuple[int, object]:
    r = row(url, wid)
    return int(r["version"]), r["baseline"]


def test_handoff_is_sticky_when_either_arming_was_one(db_url: str) -> None:
    async def body(w: World) -> None:
        for first, second, want in (("ashley", "ashley", "ashley"), ("ashley", "handoff", "handoff"),
                                    ("handoff", "ashley", "handoff"), ("handoff", "handoff", "handoff")):
            target = f"{first}-{second}"
            wid = await w.arm(target, armed_by=first)
            assert await w.arm(target, armed_by=second) == wid
            assert row(w.url, wid)["armed_by"] == want, (first, second)

    scenario(db_url, body)


def test_handoff_stays_after_two_more_ashley_armings(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = await w.arm(armed_by="handoff")
        await w.arm(armed_by="ashley")
        await w.arm(armed_by="ashley")
        assert row(w.url, wid)["armed_by"] == "handoff"

    scenario(db_url, body)


def test_a_different_target_kind_or_person_is_a_different_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        base = await w.arm("s1")
        others = {await w.arm("s2"), await w.arm("s1", who=w.mate), await w.arm("s1", kind="calendar")}
        assert base not in others and len(others) == 3
        assert count(w.url) == 4

    scenario(db_url, body)


def test_arm_after_the_watch_ended_makes_a_new_one(db_url: str) -> None:
    async def body(w: World) -> None:
        old = await w.arm(items={"s1": {"seq": 1}})
        assert await w.store.disarm(w.hid, w.owner, KIND, "s1")
        armed = await w.store.arm(make_arm(w, "s1"))
        assert armed_new(armed) is True and armed_id(armed) != old
        fresh = row(w.url, armed_id(armed))
        assert (fresh["state"], fresh["baseline"], fresh["version"], fresh["series"]) == ("armed", None, 0, 0)
        assert row(w.url, old)["state"] == "ended"

    scenario(db_url, body)


def test_arm_again_while_paused_updates_the_same_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        wid, version = await w.armed_due()
        for _ in range(FAIL_AFTER):
            assert await w.store.record(wid, version, failed())
        assert row(w.url, wid)["state"] == "paused"
        again = await w.store.arm(make_arm(w, "s1", expires_at=in_hours(4)))
        assert armed_id(again) == wid and armed_new(again) is False and count(w.url) == 1

    scenario(db_url, body)


def test_arm_with_when_condition_is_stored_per_alternative(db_url: str) -> None:
    async def body(w: World) -> None:
        when = cond((pred("equals", "status", value="done"), pred("changed", "seq")), (pred("gone"),))
        r = row(w.url, await w.arm(when=when))
        assert [len(a) for a in r["when_clauses"]] == [2, 1]
        assert r["when_clauses"][0][0]["kind"] == "equals" and r["when_clauses"][0][1]["kind"] == "changed"

    scenario(db_url, body)
