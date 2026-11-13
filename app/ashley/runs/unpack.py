"""The program a sandbox pod's init container runs (`python -I -B -c <this file's text>`), standard library only: it
reads a tar stream on standard input, which the app pushes through the Kubernetes API (`inputs.tar`), and writes the files
into `/inputs`, which the run container mounts read-only as `inputs/` in its working directory. The pod has no network.
The files expected are in `ASHLEY_INPUTS`, base64 of JSON: `files`, each `name`, `size` and `sha256`. A file is kept
only when the stream holds exactly those names, each a plain file of exactly that size with that digest; any other
result is a message on stderr and exit status 1, so the pod fails before the script starts."""

import base64
import hashlib
import json
import os
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import IO

INPUTS = Path("/inputs")
CHUNK = 1 << 20


def expected(environ: Mapping[str, str]) -> dict[str, tuple[int, str]]:
    """name -> (size, sha256) of the files the stream must hold, decoded from the environment."""
    raw = json.loads(base64.b64decode(environ["ASHLEY_INPUTS"]))
    return {str(f["name"]): (int(f["size"]), str(f["sha256"])) for f in raw["files"]}


def unpack(stream: IO[bytes], want: Mapping[str, tuple[int, str]], directory: Path) -> None:
    """Write the files of the tar `stream` into `directory`, read-only. Raises ValueError unless it holds exactly the
    files in `want`, each of its size and digest."""
    seen: set[str] = set()
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for member in tar:
            name = member.name
            if not member.isfile() or name in seen or name not in want or len(PurePosixPath(name).parts) != 1:
                raise ValueError("not an input")
            size, digest = want[name]
            source = tar.extractfile(member)
            if member.size != size or source is None:
                raise ValueError("size does not match")
            hasher = hashlib.sha256()
            with (directory / name).open("wb") as target:
                while chunk := source.read(CHUNK):
                    hasher.update(chunk)
                    target.write(chunk)
            if hasher.hexdigest() != digest:
                raise ValueError("digest does not match")
            (directory / name).chmod(0o444)
            seen.add(name)
    if seen != set(want):
        raise ValueError("an input is missing")


def main() -> None:
    try:
        unpack(sys.stdin.buffer, expected(os.environ), INPUTS)
    except (OSError, ValueError, KeyError, tarfile.TarError) as e:
        print(f"inputs: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
