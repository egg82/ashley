"""File transfer for a session: `in/` and `out/` directly under the session's directory, and nothing else of it.
Every name is flat (`NAME`), so nothing a caller sends can leave the directory; each directory is opened without
following a symlink, and every file is opened relative to that directory's descriptor, so nothing is re-resolved
between the check and the use."""

import os
import re
import stat
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from .errors import BridgeError
from .sessions import Sessions

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 26_214_400
    max_files: int = 32


def checked(name: str) -> str:
    if NAME.fullmatch(name) is None:
        raise BridgeError("bad_request")
    return name


@contextmanager
def directory(session_dir: str, sub: str, create: bool) -> Generator[int | None]:
    """A descriptor for `<session_dir>/<sub>`; None when it is absent and `create` is false. A symlink or a
    non-directory in its place is `bad_path`."""
    path = os.path.join(session_dir, sub)
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError as e:
            raise BridgeError("bad_path") from e
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        yield None
        return
    except OSError as e:
        raise BridgeError("bad_path") from e
    try:
        yield fd
    finally:
        os.close(fd)


def regular_files(fd: int) -> dict[str, int]:
    """Name to size of the regular files directly in the directory, skipping anything `NAME` would refuse."""
    found: dict[str, int] = {}
    with os.scandir(fd) as entries:
        for entry in entries:
            if NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                found[entry.name] = entry.stat(follow_symlinks=False).st_size
    return found


class Files:
    def __init__(self, sessions: Sessions, limits: Limits) -> None:
        self.sessions = sessions
        self.limits = limits

    def upload(self, session_id: str, name: str, data: bytes) -> dict[str, object]:
        checked(name)
        if len(data) > self.limits.max_file_bytes:
            raise BridgeError("too_large")
        with directory(self.sessions.session_dir(session_id), "in", create=True) as fd:
            assert fd is not None
            held = regular_files(fd)
            if name not in held and len(held) >= self.limits.max_files:
                raise BridgeError("too_many")
            self.store(fd, name, data)
        return {"bytes": len(data)}

    @staticmethod
    def store(fd: int, name: str, data: bytes) -> None:
        """Write to a temporary name no caller can send (it starts with a dot), then rename over `name`."""
        temp = f".{uuid.uuid4().hex}.tmp"
        try:
            out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(out, "wb") as f:
                f.write(data)
            os.rename(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError as e:
            try:
                os.unlink(temp, dir_fd=fd)
            except OSError:
                pass
            raise BridgeError("bad_path") from e

    def outputs(self, session_id: str) -> dict[str, object]:
        with directory(self.sessions.session_dir(session_id), "out", create=False) as fd:
            held = {} if fd is None else regular_files(fd)
        if len(held) > self.limits.max_files:
            raise BridgeError("too_many")
        return {"files": [{"name": n, "bytes": b} for n, b in sorted(held.items())]}

    def download(self, session_id: str, name: str) -> bytes:
        checked(name)
        with directory(self.sessions.session_dir(session_id), "out", create=False) as fd:
            if fd is None:
                raise BridgeError("not_found")
            return self.read(fd, name)

    def read(self, fd: int, name: str) -> bytes:
        try:
            # O_NONBLOCK so that a FIFO in out/ cannot hang the open; it is refused below as not regular.
            file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError as e:
            raise BridgeError("not_found") from e
        except OSError as e:
            raise BridgeError("bad_path") from e
        if not stat.S_ISREG(os.fstat(file).st_mode):
            os.close(file)
            raise BridgeError("bad_path")
        with os.fdopen(file, "rb") as f:
            data = f.read(self.limits.max_file_bytes + 1)
        if len(data) > self.limits.max_file_bytes:
            raise BridgeError("too_large")
        return data
