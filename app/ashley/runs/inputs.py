"""A job's binary inputs, from the object store to wherever the sandbox puts them: `read` gives one file's bytes, checked
against the reference, and `tar` streams a job's inputs as one tar archive, a file in memory at a time, for the pod's
init container to read on its standard input (`unpack`). Keys and bytes are people's data and are never logged."""

import hashlib
import tarfile
from collections.abc import AsyncIterator, Mapping

from .. import services
from ..files.intake import key_of
from ..files.store import ObjectStore, StoreUnavailable
from .model import InputFile

CHUNK = 32 * 1024
BLOCK = tarfile.BLOCKSIZE


class InputUnavailable(Exception):
    """An input's bytes could not be had: the store is unreachable, holds none, or holds others than the reference names."""


async def read(file: InputFile) -> bytes:
    """The bytes of `file`. Raises InputUnavailable unless the store gives exactly `file.size` bytes with its digest."""
    try:
        data = await services.get(ObjectStore).get(key_of(file.household_id, file.sha256))
    except StoreUnavailable as e:
        raise InputUnavailable("the store could not be reached") from e
    if data is None or len(data) != file.size or hashlib.sha256(data).hexdigest() != file.sha256:
        raise InputUnavailable("the store does not hold the input")
    return data


async def tar(inputs: Mapping[str, InputFile]) -> AsyncIterator[bytes]:
    """The inputs, by name in name order, as a tar stream in chunks of at most `CHUNK` bytes. Raises InputUnavailable
    from `read`, and ValueError for a name a tar header cannot hold."""
    for name, file in sorted(inputs.items()):
        data = await read(file)
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o444
        yield info.tobuf(tarfile.USTAR_FORMAT, "utf-8", "strict")
        for at in range(0, len(data), CHUNK):
            yield data[at:at + CHUNK]
        yield b"\0" * (-len(data) % BLOCK)
    yield b"\0" * (2 * BLOCK)
