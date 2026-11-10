"""The sweep: bytes no piece names go, but only when old enough on every site and found unreferenced by two passes in a
row; a site that fails does not stop the others; a pass that cannot judge deletes nothing; logs carry counts, not keys.
Also the store listing (`LastModified`) and delete the sweep stands on."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from files_support import FakeS3, sync
from ashley.files import config as files_config, sweep
from ashley.looks.keys import key_of as look_key
from ashley.files.memory import MemoryStore
from ashley.files.mirror import MirroredStore
from ashley.files.s3 import S3Store
from ashley.files.store import StoreUnavailable

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
GRACE = 1000
CONFIG = files_config.parse({"max_bytes": 10, "link_ttl_s": 60, "repair_interval_s": 5, "sweep_interval_s": 6,
                             "sweep_grace_s": GRACE, "text_types": ["text/plain"],
                             "types": [{"media_type": "image/png", "image": True, "magic": [[0, "89504e47"]]}]})
OLD, YOUNG = "bench/1/" + "a" * 64, "bench/1/" + "b" * 64
KEPT = "bench/1/" + "c" * 64


class Remembered:
    """The candidates, in memory."""

    def __init__(self) -> None:
        self.keys: frozenset[str] = frozenset()

    async def load(self) -> frozenset[str]:
        return self.keys

    async def save(self, keys: frozenset[str]) -> None:
        self.keys = keys


def put(store: MemoryStore, key: str, age_s: float) -> None:
    store.objects[key] = b"x"
    store.written[key] = NOW - timedelta(seconds=age_s)


def named(*keys: str) -> sweep.Referenced:
    async def read() -> frozenset[str]:
        return frozenset(keys)

    return read


async def once(sites: list[MemoryStore], referenced: sweep.Referenced, remembered: Remembered) -> sweep.Swept | None:
    return await sweep.run_once(MirroredStore(list(sites)), referenced, remembered, CONFIG, lambda: NOW)


def two_sites() -> tuple[MemoryStore, MemoryStore]:
    return MemoryStore(), MemoryStore()


@sync
async def test_an_old_unreferenced_key_goes_on_the_second_pass_from_every_site() -> None:
    a, b = two_sites()
    for site in (a, b):
        put(site, OLD, 5 * GRACE)
    remembered = Remembered()
    first = await once([a, b], named(), remembered)
    assert first == sweep.Swept(1, 1, 0) and OLD in a.objects and OLD in b.objects and remembered.keys == {OLD}
    second = await once([a, b], named(), remembered)
    assert second == sweep.Swept(1, 1, 2) and OLD not in a.objects and OLD not in b.objects and remembered.keys == set()


@sync
async def test_a_look_key_is_never_swept_however_old_and_unnamed() -> None:
    a, b = two_sites()
    look = look_key(1, "d" * 64)
    for site in (a, b):
        put(site, look, 5 * GRACE)
    remembered = Remembered()
    for _ in range(3):
        await once([a, b], named(), remembered)
    assert look in a.objects and look in b.objects and remembered.keys == set()


@sync
async def test_a_referenced_key_stays_however_many_passes() -> None:
    a, b = two_sites()
    put(a, KEPT, 5 * GRACE)
    remembered = Remembered()
    for _ in range(3):
        await once([a, b], named(KEPT), remembered)
    assert KEPT in a.objects and remembered.keys == set()


@sync
async def test_a_young_unreferenced_key_stays_and_is_not_yet_a_candidate() -> None:
    a, b = two_sites()
    put(a, YOUNG, GRACE - 1)
    remembered = Remembered()
    for _ in range(3):
        await once([a, b], named(), remembered)
    assert YOUNG in a.objects and remembered.keys == set()


@sync
async def test_a_key_unreferenced_on_one_pass_only_stays() -> None:
    a, b = two_sites()
    put(a, OLD, 5 * GRACE)
    remembered = Remembered()
    await once([a, b], named(), remembered)
    await once([a, b], named(OLD), remembered)
    assert OLD in a.objects and remembered.keys == set()
    await once([a, b], named(), remembered)
    assert OLD in a.objects and remembered.keys == {OLD}


@sync
async def test_a_key_young_on_one_site_is_young() -> None:
    a, b = two_sites()
    put(a, OLD, 5 * GRACE)
    put(b, OLD, 10)
    remembered = Remembered()
    for _ in range(3):
        await once([a, b], named(), remembered)
    assert OLD in a.objects and OLD in b.objects


@sync
async def test_a_site_that_cannot_be_listed_does_not_stop_the_others() -> None:
    a, b = two_sites()
    put(b, OLD, 5 * GRACE)
    a.down = True
    remembered = Remembered()
    await once([a, b], named(), remembered)
    swept = await once([a, b], named(), remembered)
    assert swept == sweep.Swept(1, 1, 1) and OLD not in b.objects


@sync
async def test_a_site_that_cannot_be_deleted_from_does_not_stop_the_others_and_the_key_stays_a_candidate() -> None:
    a, b = two_sites()
    for site in (a, b):
        put(site, OLD, 5 * GRACE)
    remembered = Remembered()
    await once([a, b], named(), remembered)

    class Refusing(MemoryStore):
        async def delete(self, key: str) -> None:
            raise StoreUnavailable("down")

    refusing = Refusing()
    refusing.objects, refusing.written = a.objects, a.written
    swept = await once([refusing, b], named(), remembered)
    assert swept is not None and swept.deleted == 1 and OLD in a.objects and OLD not in b.objects
    assert remembered.keys == {OLD}


@sync
async def test_nothing_is_judged_when_no_site_lists_or_the_references_cannot_be_read() -> None:
    a, b = two_sites()
    put(a, OLD, 5 * GRACE)
    remembered = Remembered()
    await once([a, b], named(), remembered)
    a.down = b.down = True
    assert await once([a, b], named(), remembered) is None and remembered.keys == {OLD}
    a.down = False

    async def broken() -> frozenset[str]:
        raise RuntimeError("database gone")

    assert await once([a, b], broken, remembered) is None
    assert OLD in a.objects and remembered.keys == {OLD}


@sync
async def test_the_pass_logs_counts_per_site_and_never_a_key(caplog: pytest.LogCaptureFixture) -> None:
    a, b = two_sites()
    put(a, OLD, 5 * GRACE)
    put(b, OLD, 5 * GRACE)
    put(b, KEPT, 5 * GRACE)
    remembered = Remembered()
    with caplog.at_level(logging.INFO):
        await once([a, b], named(KEPT), remembered)
        await once([a, b], named(KEPT), remembered)
    events = [r.getMessage() for r in caplog.records]
    assert events.count("files.sweep_started") == 2 and events.count("files.swept") == 2
    stores = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "files.sweep_store"]
    last = [s for s in stores if s["store"] == 1][-1]
    assert (last["seen"], last["unreferenced"], last["deleted"]) == (2, 1, 1)
    swept = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "files.swept"][-1]
    assert (swept["seen"], swept["unreferenced"], swept["deleted"]) == (2, 1, 2)
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text}" for r in caplog.records)
    assert "a" * 64 not in text and "c" * 64 not in text


@sync
async def test_a_failure_is_logged_with_its_frames(caplog: pytest.LogCaptureFixture) -> None:
    a, b = two_sites()

    async def broken() -> frozenset[str]:
        raise RuntimeError("secret row content")

    with caplog.at_level(logging.INFO):
        await once([a, b], broken, Remembered())
    failed = [r for r in caplog.records if r.getMessage() == "files.sweep_failed"]
    assert len(failed) == 1 and failed[0].exc_info is not None


def s3(fake: FakeS3, clock: Callable[[], datetime] = lambda: NOW) -> S3Store:
    return S3Store("http://nas.test:30203", fake.bucket, "key", "secret",
                   httpx2.AsyncClient(transport=fake.transport()), clock)


@sync
async def test_s3_lists_when_each_key_was_written_and_deletes() -> None:
    fake = FakeS3(page=1)
    store = s3(fake)
    for key in (OLD, YOUNG, KEPT):
        await store.put(key, b"x")
    fake.modified[OLD] = "2026-10-01T08:30:00.000Z"
    fake.modified[YOUNG] = "garbage"
    listed = await store.listing("bench/")
    assert listed[OLD] == datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
    assert listed[YOUNG] == NOW and listed[KEPT] == NOW and set(listed) == {OLD, YOUNG, KEPT}
    await store.delete(OLD)
    await store.delete(OLD)
    assert OLD not in fake.objects and await store.keys("bench/") == {YOUNG, KEPT}
    fake.fail = 500
    with pytest.raises(StoreUnavailable):
        await store.delete(KEPT)


@sync
async def test_the_mirror_lists_each_key_at_its_newest_write_and_deletes_from_every_store() -> None:
    a, b = two_sites()
    put(a, OLD, 100)
    put(b, OLD, 10)
    mirror = MirroredStore([a, b])
    assert (await mirror.listing("bench/"))[OLD] == NOW - timedelta(seconds=10)
    await mirror.delete(OLD)
    assert not a.objects and not b.objects
    a.down = b.down = True
    with pytest.raises(StoreUnavailable):
        await mirror.delete(OLD)
