"""The CodeHost service (`ashley.services`): a person's repositories on a forge (GitLab, GitHub) as neutral records,
reached as that person with their own token. Reads only: the interface has no call that changes anything, so no
adapter can. Callers import this module and `model`; adapters live beside it. Tokens are never logged; a call logs
`codehost.get` with the forge, the call, the project, the status, the byte count and the duration."""

from abc import abstractmethod

from ..services import Service
from .model import Access, Entry, Fetched, Page, Project, Reason


class CodeHostFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class CodeHost(Service):
    @classmethod
    def null(cls) -> "CodeHost":
        return NullCodeHost()

    @abstractmethod
    async def check(self, access: Access) -> None:
        """One cheap authenticated read: raises CodeHostFailed when the host does not answer for this token."""

    @abstractmethod
    async def projects(self, access: Access, search: str) -> Page[Project]:
        """The projects the token reads (those matching `search` when it is not empty), up to `projects_max`. Raises
        CodeHostFailed."""

    @abstractmethod
    async def tree(self, access: Access, project: str, ref: str, path: str) -> Page[Entry]:
        """The entries directly under `path` ('' is the root) at `ref` ('' is the default branch), up to `tree_max`.
        Raises CodeHostFailed."""

    @abstractmethod
    async def file(self, access: Access, project: str, ref: str, path: str, max_bytes: int) -> Fetched:
        """The file at `path` at `ref`, its first `max_bytes`. Raises CodeHostFailed."""

    @abstractmethod
    async def archive(self, access: Access, project: str, ref: str) -> bytes:
        """The whole tree at `ref` as a zip, at most `snapshot_max_bytes`. Raises CodeHostFailed (`too_large`)."""


class NullCodeHost(CodeHost):
    async def check(self, access: Access) -> None:
        raise CodeHostFailed("unreachable")

    async def projects(self, access: Access, search: str) -> Page[Project]:
        raise CodeHostFailed("unreachable")

    async def tree(self, access: Access, project: str, ref: str, path: str) -> Page[Entry]:
        raise CodeHostFailed("unreachable")

    async def file(self, access: Access, project: str, ref: str, path: str, max_bytes: int) -> Fetched:
        raise CodeHostFailed("unreachable")

    async def archive(self, access: Access, project: str, ref: str) -> bytes:
        raise CodeHostFailed("unreachable")
