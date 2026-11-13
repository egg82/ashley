"""What `wiring` registers for the object store: a store that follows the connection, built from the env's
`FILES_ENDPOINTS` until a row exists, with every files singleton running; and what it is built over, by how many
endpoints the env lists."""

import asyncio

from ashley import services, wiring
from ashley.files import repair, sweep
from ashley.files.connected_store import ConnectedStore
from ashley.files.mirror import MirroredStore
from ashley.files.s3 import S3Store
from ashley.files.store import ObjectStore
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from ashley.wiring_singletons import singletons


class NamedLeases(Lease):
    def __init__(self) -> None:
        self.names: list[str] = []

    async def run(self, name: str, body: Body) -> None:
        self.names.append(name)


def _wired(endpoints: str) -> tuple[ObjectStore, ObjectStore | None, list[str]]:
    settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow",
                        files_endpoints=endpoints, files_bucket="b", files_access_key="a", files_secret_key="s",
                        files_link_key="k" * 32)
    leases = NamedLeases()
    services.register(Lease, leases)
    closer = wiring.wire_files(settings)
    try:
        store = services.get(ObjectStore)
        for coroutine in singletons(settings):
            asyncio.run(coroutine)
        inner = asyncio.run(store.current()) if isinstance(store, ConnectedStore) else None
        asyncio.run(closer())
        return store, inner, leases.names
    finally:
        services.unregister(Lease)
        services.unregister(ObjectStore)


def test_two_endpoints_are_one_mirrored_store_kept_whole_and_swept() -> None:
    store, inner, names = _wired("http://a.invalid,http://b.invalid")
    assert isinstance(store, ConnectedStore) and isinstance(inner, MirroredStore)
    assert len(inner.stores) == 2
    assert repair.NAME in names
    assert sweep.NAME in names


def test_one_endpoint_is_that_store_swept_and_repair_has_nothing_to_do() -> None:
    store, inner, names = _wired("http://a.invalid")
    assert isinstance(store, ConnectedStore) and isinstance(inner, S3Store)
    assert names.count(repair.NAME) == 1 and names.count(sweep.NAME) == 1
