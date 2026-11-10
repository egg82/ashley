"""`unwatch` disarms by what was watched (kind and target); `watches` lists the speaker's live watches."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from watch_tools_blind_fakes import ALANA, HOUSE, KIND, LABEL, SAM, TARGET, FakeWatch
from watch_tools_blind_support import body, local, plain, refused, use, world

from ashley.criteria.items import ItemPredicate
from ashley.watches.watches import WatchesUnavailable

SOON = datetime.now(UTC) + timedelta(hours=3)
LATER = datetime.now(UTC) + timedelta(hours=30)
DONE = ((ItemPredicate("equals", field="status", value="done"),),)


def test_unwatch_disarms_by_kind_and_target_for_the_speaker() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "unwatch", plain()))
            assert w.store.disarmed == [(HOUSE, ALANA, KIND, TARGET)]
    asyncio.run(go())


def test_unwatch_is_for_the_speaker_not_the_household() -> None:
    async def go() -> None:
        async with world() as w:
            w.connections.connect(HOUSE, "https://127.0.0.1:7843", "tok2", "herdr", SAM)
            body(await use(w.tools(speaker=SAM), "unwatch", plain()))
            assert w.store.disarmed == [(HOUSE, SAM, KIND, TARGET)]
    asyncio.run(go())


def test_unwatch_of_nothing_watched_is_not_found() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.disarm_answer = False
            refused(await use(w.tools(), "unwatch", plain()), "not_found")
    asyncio.run(go())


def test_unwatch_reads_nothing_through_the_kind() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "unwatch", plain()))
            assert w.kind.reads == 0 and w.store.armed == []
    asyncio.run(go())


def test_unwatch_takes_kind_and_target_and_nothing_else() -> None:
    async def go() -> None:
        async with world() as w:
            for args in ({"kind": KIND}, {"target": TARGET}, {"kind": KIND, "target": ""}, {"kind": KIND, "target": 7},
                         {"kind": "nope", "target": TARGET}, {"id": 3}, plain(hours=2)):
                refused(await use(w.tools(), "unwatch", args), "bad_arguments")
            assert w.store.disarmed == []
    asyncio.run(go())


def test_unwatch_with_the_store_out_of_reach_is_unavailable() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.disarm_raises = WatchesUnavailable("down")
            refused(await use(w.tools(), "unwatch", plain()), "unavailable")
    asyncio.run(go())


def test_watches_lists_the_speakers_live_watches_each_with_its_fields() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.rows = [FakeWatch(KIND, TARGET, LABEL, DONE, SOON, id=1), FakeWatch(KIND, "s2", "second", (), LATER, id=2)]
            shown = body(await use(w.tools(), "watches"))["watches"]
            assert w.store.lives == [(HOUSE, ALANA)]
            assert [r["label"] for r in shown] == [LABEL, "second"]
            assert [r["kind"] for r in shown] == [KIND, KIND]
            assert [r["expires"] for r in shown] == [local(SOON), local(LATER)]
            assert "until" in shown[0] and "until" in shown[1]
    asyncio.run(go())


def test_the_until_of_a_listed_watch_says_what_ends_it() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.rows = [FakeWatch(KIND, TARGET, LABEL, DONE, SOON)]
            (row,) = body(await use(w.tools(), "watches"))["watches"]
            text = json.dumps(row["until"])
            assert "status" in text and "done" in text
    asyncio.run(go())


def test_a_watch_with_no_until_lists_one_that_ends_by_expiry_alone() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.rows = [FakeWatch(KIND, TARGET, LABEL, (), SOON)]
            (row,) = body(await use(w.tools(), "watches"))["watches"]
            assert not row["until"]
    asyncio.run(go())


def test_a_paused_watch_says_why_and_an_armed_one_does_not() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.rows = [FakeWatch(KIND, TARGET, LABEL, (), SOON, state="paused", reason="unreachable", id=1),
                            FakeWatch(KIND, "s2", "second", (), LATER, id=2)]
            paused, armed = body(await use(w.tools(), "watches"))["watches"]
            assert paused["reason"] == "unreachable"
            assert armed.get("reason") is None and "unreachable" not in json.dumps(armed)
    asyncio.run(go())


def test_no_watches_is_an_empty_list_not_an_error() -> None:
    async def go() -> None:
        async with world() as w:
            assert body(await use(w.tools(), "watches"))["watches"] == []
    asyncio.run(go())


def test_watches_takes_no_arguments() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watches", {"kind": KIND}), "bad_arguments")
    asyncio.run(go())


def test_the_listing_is_the_stores_order() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.rows = [FakeWatch(KIND, "b", "bee", (), LATER, id=2), FakeWatch(KIND, "a", "ay", (), SOON, id=1)]
            shown = body(await use(w.tools(), "watches"))["watches"]
            assert [r["label"] for r in shown] == ["bee", "ay"]
    asyncio.run(go())
