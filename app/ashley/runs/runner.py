"""The program a sandbox pod runs (`python -I -B -c <this file's text>`), standard library only: it writes the job's
files into `/work`, runs the script there with the job's input, under its own timeout, with stdout and stderr going to
files in `/out`, and prints one line, `MARK` then JSON, saying what came out. A profile with an `artifact_bytes` budget
also carries the binary files named by `ARTIFACT_SUFFIXES`, each deflated and base64, while their sizes fit it. The job arrives in the environment:
`ASHLEY_SCRIPT`, `ASHLEY_STDIN`, `ASHLEY_FILE_<n>` (each `name NUL text`), each base64 of its UTF-8 so Kubernetes
expands nothing in it, and `ASHLEY_LIMITS`; one variable per value, since Linux caps a single one at 128 KiB. Binary
inputs arrive as `ASHLEY_BLOBNAME_<n>` (base64 of the name) and `ASHLEY_BLOB_<n>_<k>`, the chunks of the base64 of the
deflated bytes in order of `k`; they are written under `inputs/` in `/work`, read-only, and are never carried back. Everything the script printed is the script's to forge, so the line is read
as no more trustworthy than its own output."""

import base64
import json
import os
import subprocess
import sys
import zlib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

MARK = "ashley-run "
WORK = Path("/work")
OUT = Path("/out")
ARTIFACT_SUFFIXES = (".glb", ".stl", ".3mf")
INPUTS = "inputs"


def job(environ: Mapping[str, str]) -> tuple[str, str, dict[str, str]]:
    """The script, its input and its files (name -> text), decoded from the environment."""
    def text(key: str) -> str:
        return base64.b64decode(environ.get(key, "")).decode("utf-8")

    files: dict[str, str] = {}
    for key in sorted(k for k in environ if k.startswith("ASHLEY_FILE_")):
        name, _, content = text(key).partition("\0")
        files[name] = content
    return text("ASHLEY_SCRIPT"), text("ASHLEY_STDIN"), files


def blobs(environ: Mapping[str, str]) -> dict[str, bytes]:
    """The binary inputs (name -> bytes) in the environment: each `ASHLEY_BLOBNAME_<n>` with its chunks joined and
    inflated."""
    found: dict[str, bytes] = {}
    for key in sorted(k for k in environ if k.startswith("ASHLEY_BLOBNAME_")):
        n = key.removeprefix("ASHLEY_BLOBNAME_")
        chunks = "".join(environ[k] for k in sorted(k for k in environ if k.startswith(f"ASHLEY_BLOB_{n}_")))
        found[base64.b64decode(environ[key]).decode("utf-8")] = zlib.decompress(base64.b64decode(chunks))
    return found


def place_blobs(work: Path, inputs: Mapping[str, bytes]) -> None:
    """Write each input as `inputs/<name>` under `work`, read-only; a name that is not plain is skipped."""
    for name, data in inputs.items():
        target = placed(work / INPUTS, name)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o444)


def placed(work: Path, name: str) -> Path | None:
    """Where file `name` goes under `work`; None for an absolute name or one that climbs out."""
    pure = PurePosixPath(name)
    if not name or pure.is_absolute() or ".." in pure.parts:
        return None
    return work.joinpath(*pure.parts)


def head(path: Path, chars: int) -> tuple[str, bool]:
    """The first `chars` characters of a file as UTF-8 (bad bytes replaced), and whether there was more."""
    with path.open("rb") as f:
        raw = f.read(chars * 4 + 1)
    text = raw.decode("utf-8", errors="replace")
    return text[:chars], len(text) > chars or len(raw) > chars * 4


def outputs(work: Path) -> list[Path]:
    """The files under `work` a script made: not links, and none under `inputs/`."""
    return [p for p in work.rglob("*") if p.is_file() and not p.is_symlink() and p.relative_to(work).parts[0] != INPUTS]


def left(work: Path, file_chars: int, max_files: int, apart: tuple[str, ...] = ()) -> tuple[dict[str, str], list[str]]:
    """The text files under `work`, by name relative to it, and the names left out: not UTF-8, longer than
    `file_chars`, or past `max_files`. Links and the inputs are not followed. A name ending in one of `apart` is neither."""
    files: dict[str, str] = {}
    skipped: list[str] = []
    for path in sorted(p for p in outputs(work) if not p.name.endswith(apart)):
        name = path.relative_to(work).as_posix()
        if len(files) >= max_files or path.stat().st_size > file_chars * 4:
            skipped.append(name)
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(name)
            continue
        if len(text) > file_chars:
            skipped.append(name)
        else:
            files[name] = text
    return files, skipped


def artifacts(work: Path, budget: int) -> tuple[dict[str, bytes], list[str]]:
    """The files under `work` whose names end in `ARTIFACT_SUFFIXES`, by name relative to it, in name order while their
    sizes add up to no more than `budget`; the names of the rest. Links and the inputs are not followed."""
    kept: dict[str, bytes] = {}
    skipped: list[str] = []
    used = 0
    for path in sorted(p for p in outputs(work) if p.name.endswith(ARTIFACT_SUFFIXES)):
        name = path.relative_to(work).as_posix()
        if used + path.stat().st_size > budget:
            skipped.append(name)
            continue
        kept[name] = path.read_bytes()
        used += len(kept[name])
    return kept, skipped


def line(exit_code: int | None, timed_out: bool, out: Path, work: Path, limits: dict[str, int]) -> str:
    """The line to print: `MARK` then JSON of `exit_code` (negative: the signal that stopped it; None when it timed
    out), `timed_out`, `stdout`, `stderr`, `cut`, `files` and `skipped` (and, when the limits give an `artifact_bytes`,
    `artifacts`: name -> base64 of the deflated bytes), under `log_bytes` with its newline, since the log is read no
    further. The streams always fit (`config.parse` sizes them); each file or artifact that would not is left out and
    named in `skipped`, while the names fit."""
    stdout, cut_out = head(out / "stdout", limits["output_chars"])
    stderr, cut_err = head(out / "stderr", limits["output_chars"])
    budget_bytes = limits.get("artifact_bytes", 0)
    found, skipped = left(work, limits["file_chars"], limits["max_files"], ARTIFACT_SUFFIXES if budget_bytes else ())
    files: dict[str, str] = {}
    named: list[str] = []
    body: dict[str, object] = {"exit_code": exit_code, "timed_out": timed_out, "stdout": stdout, "stderr": stderr,
                               "cut": cut_out or cut_err, "files": files, "skipped": named}
    budget = limits["log_bytes"] - 1
    for name, text in found.items():
        files[name] = text
        if _size(body) > budget:
            del files[name]
            skipped.append(name)
    if budget_bytes:
        skipped += _carry(work, budget_bytes, body, budget)
    for name in skipped:
        named.append(name)
        if _size(body) > budget:
            named.pop()
            break
    return MARK + json.dumps(body, ensure_ascii=False)


def _carry(work: Path, budget_bytes: int, body: dict[str, object], budget: int) -> list[str]:
    """Put each artifact of `work` in `body["artifacts"]` while the line fits `budget`; the names of those that did not."""
    kept, left_out = artifacts(work, budget_bytes)
    carried: dict[str, str] = {}
    body["artifacts"] = carried
    for name, data in kept.items():
        carried[name] = base64.b64encode(zlib.compress(data)).decode("ascii")
        if _size(body) > budget:
            del carried[name]
            left_out.append(name)
    return left_out


def _size(body: dict[str, object]) -> int:
    return len((MARK + json.dumps(body, ensure_ascii=False)).encode("utf-8"))


def main() -> None:
    limits: dict[str, int] = json.loads(os.environ["ASHLEY_LIMITS"])
    script, stdin, files = job(os.environ)
    for name, text in files.items():
        target = placed(WORK, name)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    place_blobs(WORK, blobs(os.environ))
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(WORK), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    exit_code: int | None = None
    timed_out = False
    with (OUT / "stdout").open("wb") as stdout, (OUT / "stderr").open("wb") as stderr:
        try:
            done = subprocess.run([sys.executable, "-B", "-c", script], cwd=WORK, env=env,
                                  input=stdin.encode("utf-8"), stdout=stdout,
                                  stderr=stderr, timeout=limits["timeout_s"], check=False)
            exit_code = done.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    print(line(exit_code, timed_out, OUT, WORK, limits), flush=True)


if __name__ == "__main__":
    main()
