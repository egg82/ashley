"""`shooter.serve_one` and `shooter.clear`: each look gets a browser of its own that is closed after, whatever the look
did, and what it left in `TMPDIR` is removed, so nothing one look held reaches the next."""

import base64
import os
import queue
from pathlib import Path

from ashley.looks import shooter
from warm_blind_browser_support import PwError, Script, playwright
from warm_blind_support import LIMITS, PAGE_URL


def take(script: Script, tmp: Path, url: str = PAGE_URL) -> str:
    jobs: queue.Queue[shooter.Job] = queue.Queue()
    reply: queue.Queue[str] = queue.Queue()
    jobs.put((url, reply))
    api, p = playwright(script, tmp)
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp))
    return reply.get_nowait()


def names(tmp: Path) -> set[str]:
    return set(os.listdir(tmp))


def test_a_look_is_answered_with_the_line_of_its_picture(tmp_path: Path) -> None:
    line = take(Script(), tmp_path)
    assert line.startswith(shooter.MARK)
    assert base64.b64decode(line[len(shooter.MARK):]).startswith(bytes.fromhex("ffd8ff"))


def test_the_page_opened_is_the_one_asked_for(tmp_path: Path) -> None:
    script = Script()
    take(script, tmp_path, PAGE_URL + "?piece=4")
    assert script.gotos == [PAGE_URL + "?piece=4"]


def test_a_look_that_cannot_draw_is_answered_with_its_reason(tmp_path: Path) -> None:
    assert take(Script(ready=False), tmp_path) == shooter.FAILED + "not_ready"
    assert take(Script(scale=100_000), tmp_path) == shooter.FAILED + "too_large"


def test_a_browser_that_will_not_start_is_still_an_answer(tmp_path: Path) -> None:
    line = take(Script(launch_error=PwError("boom")), tmp_path)
    assert line.startswith(shooter.FAILED)
    assert line[len(shooter.FAILED):] not in ("not_ready", "too_large")


def test_any_failure_of_the_look_is_still_an_answer(tmp_path: Path) -> None:
    line = take(Script(launch_error=RuntimeError("not playwright's")), tmp_path)
    assert line.startswith(shooter.FAILED) and line[len(shooter.FAILED):] not in ("not_ready", "too_large")


def test_each_look_launches_a_browser_of_its_own_and_closes_it_before_the_next(tmp_path: Path) -> None:
    script = Script()
    for _ in range(3):
        take(script, tmp_path)
    assert script.events == [("launch", 1), ("close", 1), ("launch", 2), ("close", 2), ("launch", 3), ("close", 3)]


def test_the_browser_is_closed_when_the_look_fails(tmp_path: Path) -> None:
    for script in (Script(ready=False), Script(goto_error=PwError("x")), Script(scale=100_000)):
        take(script, tmp_path)
        assert script.events == [("launch", 1), ("close", 1)]


def test_what_a_look_left_in_tmp_is_removed(tmp_path: Path) -> None:
    script = Script(leave=("pw-profile/", "note.txt"))
    take(script, tmp_path)
    assert names(tmp_path) == set()


def test_what_a_failed_look_left_in_tmp_is_removed(tmp_path: Path) -> None:
    for script in (Script(leave=("pw/", "a"), ready=False), Script(leave=("pw/", "a"), goto_error=PwError("x")),
                   Script(leave=("pw/", "a"), scale=100_000)):
        take(script, tmp_path)
        assert names(tmp_path) == set()


def test_what_was_there_before_the_look_stays(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    (tmp_path / "keepdir").mkdir()
    (tmp_path / "keepdir" / "inner").write_text("x")
    take(Script(leave=("pw/", "new")), tmp_path)
    assert names(tmp_path) == {"keep.txt", "keepdir"}
    assert (tmp_path / "keepdir" / "inner").read_text() == "x"


def test_the_directory_itself_stays(tmp_path: Path) -> None:
    take(Script(leave=("pw/",)), tmp_path)
    assert tmp_path.is_dir()


def test_clear_removes_what_appeared_since_the_listing(tmp_path: Path) -> None:
    (tmp_path / "old").write_text("o")
    before = names(tmp_path)
    (tmp_path / "file").write_text("f")
    (tmp_path / ".hidden").write_text("h")
    (tmp_path / "dir" / "deeper").mkdir(parents=True)
    (tmp_path / "dir" / "deeper" / "x").write_text("x")
    shooter.clear(str(tmp_path), before)
    assert names(tmp_path) == {"old"}


def test_clear_of_nothing_new_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / "old").write_text("o")
    shooter.clear(str(tmp_path), names(tmp_path))
    assert names(tmp_path) == {"old"}


def test_clear_removes_a_symlink_and_not_what_it_points_at(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("p")
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    before = names(tmp)
    os.symlink(outside, tmp / "link")
    os.symlink(outside / "precious", tmp / "flink")
    shooter.clear(str(tmp), before)
    assert names(tmp) == set()
    assert (outside / "precious").read_text() == "p"


def test_clear_leaves_the_old_when_the_new_includes_a_directory_with_the_same_prefix(tmp_path: Path) -> None:
    (tmp_path / "pw").mkdir()
    (tmp_path / "pw" / "inner").write_text("i")
    before = names(tmp_path)
    (tmp_path / "pw2").mkdir()
    shooter.clear(str(tmp_path), before)
    assert names(tmp_path) == {"pw"} and (tmp_path / "pw" / "inner").exists()
