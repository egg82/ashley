"""The in-pod runner's pure parts, in process: where a file may go, what comes back of the working directory and the
output streams, and that its line reads back through `envelope.parse` as the output it describes."""

from pathlib import Path

from ashley.runs import config, envelope, runner
from ashley.runs.kubernetes import RUNNER
from ashley.runs.model import Output
from sandbox_support import CONFIG

LIMITS = {"timeout_s": 10, "output_chars": 5, "file_chars": 8, "max_files": 2, "log_bytes": 4096}


def test_a_file_never_lands_outside_the_working_directory(tmp_path: Path) -> None:
    assert runner.placed(tmp_path, "a/b.txt") == tmp_path / "a" / "b.txt"
    assert runner.placed(tmp_path, "/etc/passwd") is None
    assert runner.placed(tmp_path, "../x") is None
    assert runner.placed(tmp_path, "a/../../x") is None
    assert runner.placed(tmp_path, "") is None


def test_text_files_come_back_and_the_rest_are_named_skipped(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("short")
    (tmp_path / "b.bin").write_bytes(b"\xff\xfe")
    (tmp_path / "c.txt").write_text("much too long")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "e.txt").write_text("e")
    (tmp_path / "link").symlink_to(tmp_path / "a.txt")
    files, skipped = runner.left(tmp_path, file_chars=8, max_files=2)
    assert files == {"a.txt": "short", "d/e.txt": "e"}
    assert skipped == ["b.bin", "c.txt"]


def test_its_line_reads_back_as_the_output_it_describes(tmp_path: Path) -> None:
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    work.mkdir()
    (out / "stdout").write_text("1234567")
    (out / "stderr").write_text("")
    (work / "r.txt").write_text("result")
    line = runner.line(0, False, out, work, LIMITS)
    assert envelope.parse("noise\n" + line, CONFIG) == Output("ran", 0, "12345", "", True, {"r.txt": "result"}, ())


def test_the_runner_shipped_to_the_pod_is_this_module_and_compiles() -> None:
    assert RUNNER == Path(runner.__file__).read_text()
    compile(RUNNER, "runner", "exec")


def test_its_line_fits_the_log_with_stdout_intact_however_large_the_files(tmp_path: Path) -> None:
    shipped = config.load()
    log_bytes = shipped.languages["python"].log_bytes
    limits = {"timeout_s": 10, "output_chars": shipped.output_chars, "file_chars": shipped.file_chars,
              "max_files": shipped.max_files, "log_bytes": log_bytes}
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    work.mkdir()
    stdout = "\x01é\u2028" * (shipped.output_chars // 3)
    (out / "stdout").write_text(stdout)
    (out / "stderr").write_text("\x02" * shipped.output_chars)
    for i in range(shipped.max_files):
        fill = ("a", "é", "\x03", "\u2028")[i % 4]
        (work / f"f{i:02}.txt").write_text(fill * shipped.file_chars)
    line = runner.line(0, False, out, work, limits)
    assert len(line.encode("utf-8")) + 1 <= log_bytes
    got = envelope.parse(line, shipped)
    assert got is not None and got.outcome == "ran" and got.stdout == stdout
    assert got.files and set(got.files) | set(got.skipped) == {f"f{i:02}.txt" for i in range(shipped.max_files)}
