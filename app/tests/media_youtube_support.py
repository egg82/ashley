"""A stand-in `yt-dlp` on PATH for the media runner's YouTube captions job: it records its argv and, as the real one does
for a video that has an English track, writes the captured json3 track to the `-o` template with `%(ext)s` as `en.json3`.
`MODE` (environment) picks `track` (default), `none` (exit 0, nothing written), `fail` (exit 1) or `hang`."""

import os
import stat
from pathlib import Path

CAPTURED = Path(__file__).parent / "youtube_captured" / "captions.en.json3"
SCRIPT = """#!/usr/bin/env python3
import json, os, shutil, sys, time
mode = os.environ.get("MODE", "track")
open(os.environ["ARGV_FILE"], "w").write(json.dumps(sys.argv[1:]))
if mode == "hang":
    time.sleep(30)
if mode == "fail":
    sys.exit(1)
if mode == "track":
    template = sys.argv[sys.argv.index("-o") + 1]
    shutil.copy(os.environ["TRACK"], template.replace("%(ext)s", "en.json3"))
"""


def install(bin_dir: Path) -> None:
    """Put the stand-in on the front of PATH's directory `bin_dir` as `yt-dlp`."""
    path = bin_dir / "yt-dlp"
    path.write_text(SCRIPT)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def track_text() -> str:
    return CAPTURED.read_text(encoding="utf-8")


def with_path(bin_dir: Path) -> str:
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
