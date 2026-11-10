"""The folders Ashley's bench jobs run in: `<root>/ashley-jobs/j<job id>`. The bridge makes one per Claude Code job, so it
is the bridge that says what the job session may touch (a settings file naming only that folder) and how many of them
are kept (the newest `keep`, never one a live session runs in)."""

import json
import os
import re
import shutil
import stat

from .errors import BridgeError

PARENT = "ashley-jobs"
FOLDER = re.compile(r"j([0-9]{1,18})")
SETTINGS = ".ashley-job-settings.json"
# A path inside a permission rule is read as a glob; anything but these would need escaping, so it is refused instead.
PLAIN = re.compile(r"/[A-Za-z0-9._/@+=,:-]+")


def is_job_dir(real: str) -> bool:
    """Whether the real path is `<something>/ashley-jobs/j<number>`."""
    parent, name = os.path.split(real)
    return os.path.basename(parent) == PARENT and FOLDER.fullmatch(name) is not None


def permissions(real: str) -> dict[str, object]:
    """Claude Code settings that let a session read, write and edit inside `real` and nothing else. `//` starts a path
    at the filesystem root; a rule for any other path is not made, so a prompt for it still stops the session."""
    if PLAIN.fullmatch(real) is None:
        raise BridgeError("dir_not_allowed")
    inside = f"//{real.lstrip('/')}/**"
    return {"permissions": {"allow": [f"Read({inside})", f"Edit({inside})", f"Write({inside})"]}}


def write_settings(real: str) -> str:
    """Write the folder's settings file, replacing any, and return its path, which the session is started with
    (`claude --settings`). A project `.claude/settings.json` would be ignored until the person has trusted the folder."""
    path = os.path.join(real, SETTINGS)
    body = json.dumps(permissions(real), indent=2) + "\n"
    try:
        with open(path, "w") as f:
            f.write(body)
    except OSError as e:
        raise BridgeError("dir_not_allowed") from e
    return path


def prune(real: str, keep: int, busy: set[str]) -> int:
    """Remove the oldest job folders beside `real` (by job number) beyond the `keep` newest. `real` itself and any folder
    in `busy` (the real paths live sessions run in) are never removed. A symlink or a file with a job folder's name is
    left alone. Returns how many were removed."""
    parent = os.path.dirname(real)
    found: list[tuple[int, str]] = []
    with os.scandir(parent) as entries:
        for entry in entries:
            match = FOLDER.fullmatch(entry.name)
            if match is not None and stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode):
                found.append((int(match[1]), entry.path))
    removed = 0
    for _, path in sorted(found, reverse=True)[keep:]:
        if path != real and os.path.realpath(path) not in busy:
            shutil.rmtree(path, ignore_errors=True)
            removed += not os.path.exists(path)
    return removed
