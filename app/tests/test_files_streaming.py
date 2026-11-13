"""A stored file is served from the store as a stream: a whole read and a ranged one both reach the client without
the object ever being read whole (`ObjectStore.get`), the S3 adapter asks the server for the range alone, and the
200, 206 and 416 answers a player relies on are kept."""

from collections.abc import AsyncIterator, Generator
from types import SimpleNamespace

import httpx2
import pytest
from files_support import FakeS3, sync
from ashley import services
from ashley.api import files
from ashley.files import links
from ashley.files.memory import MemoryStore
from ashley.files.mirror import MirroredStore
from ashley.files.s3 import S3Store
from ashley.files.store import CHUNK, ObjectStore, StoreUnavailable
from fastapi import FastAPI
from fastapi.testclient import TestClient

KEY = b"k" * 40
SHA = "a" * 64
OBJECT = "bench/1/" + SHA
DATA = bytes(range(256)) * 4096


class NeverWhole(MemoryStore):
    """A store that fails the test when an object is read whole, and counts the bytes streamed out."""

    def __init__(self) -> None:
        super().__init__()
        self.streamed = 0

    async def get(self, key: str) -> bytes | None:
        raise AssertionError("the object was read whole")

    async def stream(self, key: str, first: int, last: int) -> AsyncIterator[bytes] | None:
        found = await super().stream(key, first, last)
        return None if found is None else self._count(found)

    async def _count(self, source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        async for chunk in source:
            self.streamed += len(chunk)
            yield chunk


@pytest.fixture
def served() -> Generator[tuple[TestClient, NeverWhole, str]]:
    store = NeverWhole()
    store.objects[OBJECT] = DATA
    services.register(ObjectStore, store)
    app = FastAPI()
    app.state.settings = SimpleNamespace(files_link_key=KEY.decode())
    app.include_router(files.router)
    url = links.mint(KEY, links.Grant(1, SHA, "video/mp4", False, 4_000_000_000)).url
    try:
        yield TestClient(app), store, url
    finally:
        services.unregister(ObjectStore)


def test_a_whole_read_streams_every_byte_and_never_reads_the_object_whole(served: tuple[TestClient, NeverWhole, str]) -> None:
    client, store, url = served
    reply = client.get(url)
    assert (reply.status_code, reply.content) == (200, DATA)
    assert reply.headers["content-length"] == str(len(DATA)) and store.streamed == len(DATA)
    assert len(DATA) > 2 * CHUNK


def test_a_range_streams_only_that_range_with_its_content_range(served: tuple[TestClient, NeverWhole, str]) -> None:
    client, store, url = served
    reply = client.get(url, headers={"range": "bytes=1000-299999"})
    assert (reply.status_code, reply.content) == (206, DATA[1000:300000])
    assert reply.headers["content-range"] == f"bytes 1000-299999/{len(DATA)}" and reply.headers["content-length"] == "299000"
    assert store.streamed == 299000
    tail = client.get(url, headers={"range": "bytes=-5"})
    assert (tail.status_code, tail.content) == (206, DATA[-5:])
    assert tail.headers["content-range"] == f"bytes {len(DATA) - 5}-{len(DATA) - 1}/{len(DATA)}"


def test_a_range_past_the_end_is_416_and_streams_nothing(served: tuple[TestClient, NeverWhole, str]) -> None:
    client, store, url = served
    reply = client.get(url, headers={"range": f"bytes={len(DATA)}-"})
    assert reply.status_code == 416 and reply.headers["content-range"] == f"bytes */{len(DATA)}"
    assert reply.json()["code"] == "refused" and store.streamed == 0


def test_a_missing_file_is_404_and_an_unreachable_store_is_503(served: tuple[TestClient, NeverWhole, str]) -> None:
    client, store, url = served
    store.objects.clear()
    assert client.get(url).status_code == 404
    store.down = True
    assert client.get(url).status_code == 503


@sync
async def test_s3_asks_for_the_range_alone_and_sizes_with_a_head() -> None:
    fake = FakeS3()
    store = S3Store("http://nas.test", fake.bucket, "k", "s", httpx2.AsyncClient(transport=fake.transport()))
    fake.objects[OBJECT] = DATA
    assert await store.size(OBJECT) == len(DATA) and await store.size("bench/1/none") is None
    assert fake.sent == 0
    chunks = await store.stream(OBJECT, 10, 700_000)
    assert chunks is not None
    assert b"".join([c async for c in chunks]) == DATA[10:700_001]
    assert fake.sent == 700_001 - 10 and fake.signed == 3 and fake.unsigned == 0
    assert await store.stream("bench/1/none", 0, 9) is None
    fake.fail = 500
    with pytest.raises(StoreUnavailable):
        await store.stream(OBJECT, 0, 9)
    with pytest.raises(StoreUnavailable):
        await store.size(OBJECT)


@sync
async def test_a_mirror_streams_from_the_first_store_that_has_it_and_skips_one_that_is_down() -> None:
    down, site = MemoryStore(), MemoryStore()
    down.down = True
    site.objects[OBJECT] = DATA
    mirror = MirroredStore([down, site])
    assert await mirror.size(OBJECT) == len(DATA) and await mirror.size("none") is None
    chunks = await mirror.stream(OBJECT, 5, 9)
    assert chunks is not None and b"".join([c async for c in chunks]) == DATA[5:10]
    assert await mirror.stream("none", 0, 1) is None
    site.down = True
    with pytest.raises(StoreUnavailable):
        await mirror.stream(OBJECT, 0, 1)
