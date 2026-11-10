"""The port to a person's herdr bridge (`ashley.services`): their Claude Code sessions, listed, read, prompted, started
and closed, and the files moved through a session's `in/` and `out/`. Each call names the bridge by an `Access`, and raises `BridgeFailed` with the bridge's own reason."""

from abc import abstractmethod

from ..services import Service
from .model import Access, BridgeFailed, OutFile, Screen, Session, SessionList, Whoami


class Bridge(Service):
    @classmethod
    def null(cls) -> "Bridge":
        return NullBridge()

    @abstractmethod
    async def whoami(self, access: Access) -> Whoami:
        """The bridge's versions and the person it serves: the one authenticated read that checks a connection."""

    @abstractmethod
    async def sessions(self, access: Access) -> SessionList:
        """The person's Claude Code sessions."""

    @abstractmethod
    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        """The last `lines` (1 to 400) of a session's screen as unwrapped text."""

    @abstractmethod
    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        """Send `text` (1 to 8000 characters) to a session that is idle or done. `busy`, `blocked`, `unknown_state`
        or `person_typing` mean nothing was sent; `unconfirmed` means it may have been."""

    @abstractmethod
    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        """Start a session in `directory`, under a root the bridge was set up with (`SessionList.roots`), named
        `label`. A directory that does not exist yet is created."""

    @abstractmethod
    async def close(self, access: Access, session_id: str) -> None:
        """End a session's pane. `unconfirmed` means it may have ended."""

    @abstractmethod
    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        """Write `data` to `in/<name>` under the session's directory, replacing a file of that name. `name` is flat:
        a letter or digit, then up to 99 of letters, digits, `.`, `_`, `-`; anything else is `bad_request`.
        `too_large` (over the bridge's file limit), `too_many` (its file count), `bad_path` (`in/` is not a plain
        directory) and `dir_not_allowed` mean nothing was written; `unconfirmed` means it may have been. Needs the
        `files` capability (`Whoami.capabilities`)."""

    @abstractmethod
    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        """The regular files directly in the session's `out/`, by name; empty when there is no `out/`."""

    @abstractmethod
    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        """The bytes of `out/<name>`. `too_large` when the file, or what the bridge would send, is over `max_bytes`;
        `not_found` for no such file; `bad_path` for one that is not a regular file."""


class NullBridge(Bridge):
    async def whoami(self, access: Access) -> Whoami:
        raise BridgeFailed("herdr_unavailable")

    async def sessions(self, access: Access) -> SessionList:
        raise BridgeFailed("herdr_unavailable")

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        raise BridgeFailed("herdr_unavailable")

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        raise BridgeFailed("herdr_unavailable")

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        raise BridgeFailed("herdr_unavailable")

    async def close(self, access: Access, session_id: str) -> None:
        raise BridgeFailed("herdr_unavailable")

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        raise BridgeFailed("herdr_unavailable")

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        raise BridgeFailed("herdr_unavailable")

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        raise BridgeFailed("herdr_unavailable")
