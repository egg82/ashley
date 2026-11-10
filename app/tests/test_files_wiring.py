"""What `wiring` registers for the object store, and which files singletons the app runs, by how many endpoints
`FILES_ENDPOINTS` lists."""

import asyncio

from ashley import services, wiring
from ashley.files import repair, sweep
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


def _wired(endpoints: str) -> tuple[ObjectStore, list[str]]:
    settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow",
                        files_endpoints=endpoints, files_bucket="b", files_access_key="a", files_secret_key="s",
                        files_link_key="k" * 32)
    leases = NamedLeases()
    services.register(Lease, leases)
    closer = wiring._wire_files(settings)
    try:
        store = services.get(ObjectStore)
        for coroutine in singletons(settings):
            asyncio.run(coroutine)
        asyncio.run(closer())
        return store, leases.names
    finally:
        services.unregister(Lease)
        services.unregister(ObjectStore)


def test_two_endpoints_are_one_mirrored_store_kept_whole_and_swept() -> None:
    store, names = _wired("http://a.invalid,http://b.invalid")
    assert isinstance(store, MirroredStore)
    assert len(store.stores) == 2
    assert repair.NAME in names
    assert sweep.NAME in names

