"""The program a sandbox pod's init container runs (`python -I -B -c <this file's text>`), standard library only: it
fetches each input the job names, by the short-lived link the app signed for it, into `/inputs`, which the run
container mounts read-only as `inputs/` in its working directory. The task is in `ASHLEY_FETCH`, base64 of JSON:
`timeout_s` for each request and `files`, each `name`, `url`, `size` and `sha256`. A file is kept only when it is
exactly `size` bytes with that digest; any other result is a message on stderr and exit status 1, so the pod fails
before the script starts. Nothing is printed of the links."""

import base64
import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

INPUTS = Path("/inputs")


def task(environ: Mapping[str, str]) -> tuple[int, list[dict[str, object]]]:
    """The request timeout and the files to fetch, decoded from the environment."""
    raw = json.loads(base64.b64decode(environ["ASHLEY_FETCH"]))
    return int(raw["timeout_s"]), list(raw["files"])


def fetch(url: str, size: int, sha256: str, timeout_s: int) -> bytes:
    """The bytes at `url`, read no further than `size` + 1. Raises ValueError unless they are `size` bytes with digest
    `sha256`."""
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        data = response.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("size or digest does not match")
    return data


def place(directory: Path, name: str, data: bytes) -> None:
    """Write `data` as `name` under `directory`, read-only. Raises ValueError for a name that is not one plain file name."""
    pure = PurePosixPath(name)
    if not name or len(pure.parts) != 1 or pure.parts[0] in (".", ".."):
        raise ValueError("not a plain file name")
    target = directory / name
    target.write_bytes(data)
    target.chmod(0o444)


def main() -> None:
    timeout_s, files = task(os.environ)
    for i, item in enumerate(files):
        try:
            place(INPUTS, str(item["name"]),
                  fetch(str(item["url"]), int(str(item["size"])), str(item["sha256"]), timeout_s))
        except (OSError, ValueError, KeyError) as e:
            print(f"input {i}: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
