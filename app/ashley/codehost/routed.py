"""The CodeHost wired: each call goes to the adapter of the access's forge, and a call the host answered moves the
`checked_at` of the connection its access came from."""

from collections.abc import Mapping

from ..connections import answered
from .host import CodeHost
from .model import Access, Entry, Fetched, Forge, Page, Project


class RoutedCodeHost(CodeHost):
    def __init__(self, hosts: Mapping[Forge, CodeHost]) -> None:
        self._hosts = dict(hosts)

    async def check(self, access: Access) -> None:
        await self._hosts[access.forge].check(access)

    async def projects(self, access: Access, search: str) -> Page[Project]:
        got = await self._hosts[access.forge].projects(access, search)
        await _answered(access)
        return got

    async def tree(self, access: Access, project: str, ref: str, path: str) -> Page[Entry]:
        got = await self._hosts[access.forge].tree(access, project, ref, path)
        await _answered(access)
        return got

    async def file(self, access: Access, project: str, ref: str, path: str, max_bytes: int) -> Fetched:
        got = await self._hosts[access.forge].file(access, project, ref, path, max_bytes)
        await _answered(access)
        return got

    async def archive(self, access: Access, project: str, ref: str) -> bytes:
        got = await self._hosts[access.forge].archive(access, project, ref)
        await _answered(access)
        return got


async def _answered(access: Access) -> None:
    if access.connection is not None:
        await answered.record(access.connection)
