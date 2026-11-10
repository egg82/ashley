"""The S3 adapter against a fake S3 server (its requests are signed, listings page, an error is StoreUnavailable), the
memory store, the mirror over several stores (a write counts with one copy, a read falls through, repair copies what is
missing) and the repair singleton's pass."""

import httpx2
import pytest
from files_support import FakeS3, sync
from ashley import wiring_singletons
from ashley.files import repair
from ashley.files.memory import MemoryStore
from ashley.files.mirror import MirroredStore
from ashley.files.s3 import S3Store
from ashley.files.store import NullStore, ObjectStore, StoreUnavailable

PREFIXES = ("bench/", "other/")


def s3(fake: FakeS3, endpoint: str = "http://nas.test:30203") -> S3Store:
    return S3Store(endpoint, fake.bucket, "key", "secret", httpx2.AsyncClient(transport=fake.transport()))


@sync
async def test_s3_keeps_reads_and_lists_signed_requests() -> None:
    fake = FakeS3()
    store = s3(fake)
    assert await store.put("bench/1/" + "a" * 64, b"bytes") == 1
    assert await store.get("bench/1/" + "a" * 64) == b"bytes"
    assert await store.get("bench/1/missing") is None
    assert await store.keys("bench/1/") == frozenset({"bench/1/" + "a" * 64})
    assert fake.signed == 4 and fake.unsigned == 0


@sync
async def test_a_key_with_awkward_characters_round_trips() -> None:
    fake = FakeS3()
    store = s3(fake)
    await store.put("bench/1/a b+c=d", b"x")
    assert fake.objects == {"bench/1/a b+c=d": b"x"} and await store.get("bench/1/a b+c=d") == b"x"


@sync
async def test_a_listing_follows_its_pages() -> None:
    fake = FakeS3(page=2)
    store = s3(fake)
    for n in range(5):
        await store.put(f"bench/1/k{n}", b"x")
    await store.put("other/k", b"x")
    assert await store.keys("bench/") == frozenset(f"bench/1/k{n}" for n in range(5))


@sync
async def test_an_error_status_and_an_unreachable_server_are_unavailable() -> None:
    fake = FakeS3()
    store = s3(fake)
    fake.fail = 500
    for call in (store.put("k", b"x"), store.get("k"), store.keys("")):
        with pytest.raises(StoreUnavailable):
            await call
    def refuse(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")
    down = S3Store("http://x", "b", "k", "s", httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)))
    with pytest.raises(StoreUnavailable):
        await down.get("k")


@sync
async def test_the_null_store_raises_and_the_locator_answers_it_unwired() -> None:
    from ashley import services
    assert isinstance(services.get(ObjectStore), NullStore)
    with pytest.raises(StoreUnavailable):
        await services.get(ObjectStore).put("k", b"x")


@sync
async def test_a_write_to_a_mirror_counts_with_one_copy_and_reads_fall_through() -> None:
    near, far = MemoryStore(), MemoryStore()
    mirror = MirroredStore([near, far])
    assert await mirror.put("k", b"v") == 2
    far.down = True
    assert await mirror.put("k2", b"w") == 1
    assert near.objects == {"k": b"v", "k2": b"w"}
    near.down, far.down = True, False
    assert await mirror.get("k") == b"v"
    assert await mirror.get("k2") is None
    far.down = True
    with pytest.raises(StoreUnavailable):
        await mirror.get("k")
    with pytest.raises(StoreUnavailable):
        await mirror.put("k3", b"x")


@sync
async def test_the_nearest_copy_is_read_first() -> None:
    near, far = MemoryStore(), MemoryStore()
    near.objects["k"], far.objects["k"] = b"near", b"far"
    assert await MirroredStore([near, far]).get("k") == b"near"
    assert await MirroredStore([far, near]).get("k") == b"far"


@sync
async def test_repair_copies_what_each_site_lacks_and_only_that() -> None:
    a, b = MemoryStore(), MemoryStore()
    a.objects.update({"bench/1/x": b"x", "bench/1/both": b"both"})
    b.objects.update({"bench/1/both": b"both", "bench/2/y": b"y", "elsewhere/z": b"z"})
    mirror = MirroredStore([a, b])
    assert await repair.run_once(mirror, PREFIXES) == 2
    assert a.objects["bench/2/y"] == b"y" and b.objects["bench/1/x"] == b"x"
    assert "elsewhere/z" not in a.objects
    assert await repair.run_once(mirror, PREFIXES) == 0


@sync
async def test_repair_does_nothing_when_a_site_cannot_be_listed() -> None:
    """A store that cannot be listed would look empty, and everything would be 'missing' from it."""
    a, b = MemoryStore(), MemoryStore()
    a.objects["bench/1/x"] = b"x"
    b.down = True
    assert await repair.run_once(MirroredStore([a, b]), PREFIXES) == 0
    assert b.objects == {}


@sync
async def test_the_repair_loop_passes_then_waits_until_cancelled() -> None:
    a, b = MemoryStore(), MemoryStore()
    a.objects["bench/1/x"] = b"x"
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await repair.run(MirroredStore([a, b]), PREFIXES, 3600, sleep)
    assert waits == [3600, 3600] and b.objects["bench/1/x"] == b"x"


@sync
async def test_a_look_taken_on_one_site_is_copied_to_the_other_by_the_wired_repair() -> None:
    key = "look/1/" + "a" * 64
    a, b = MemoryStore(), MemoryStore()
    a.objects[key] = b"picture"
    assert await repair.run_once(MirroredStore([a, b]), wiring_singletons.REPAIRED_PREFIXES) == 1
    assert b.objects[key] == b"picture"
