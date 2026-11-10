"""A bench job's folder (`<root>/ashley-jobs/j<id>`, `herdr_bridge.jobdirs`): the session is started with a settings file
that lets it read, write and edit inside that folder and nothing else; any other start is left as it was; and the oldest
folders beyond `keep_job_dirs` are removed at a start, never one a live session runs in."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from herdr_bridge import jobdirs
from herdr_bridge.cli import make_api
from herdr_bridge.config import Config, load
from herdr_bridge.errors import BridgeError
from herdr_bridge.herdr import Herdr
from herdr_bridge_blind_fake import FakeHerdr
from herdr_bridge_blind_pki import Pki, make_pki
from herdr_bridge_blind_support import Bridge, MemoryLog, build_bridge


@pytest.fixture(scope="module")
def pki() -> Pki:
    return make_pki()


@pytest.fixture
def fake() -> FakeHerdr:
    return FakeHerdr()


@pytest.fixture
def bridge(tmp_path: Path, pki: Pki, fake: FakeHerdr) -> Bridge:
    built = build_bridge(tmp_path, pki, fake)
    built.sessions.keep_job_dirs = 3
    return built


def job_dir(b: Bridge, n: int) -> Path:
    return b.root / jobdirs.PARENT / f"j{n}"


def start_job(b: Bridge, n: int) -> str:
    made = b.start(job_dir(b, n), f"job-{n}")
    assert made.status == 200, made.body
    return str(made.body["id"])


def test_a_job_session_is_started_with_a_settings_file_naming_only_its_own_folder(bridge: Bridge) -> None:
    start_job(bridge, 5)
    folder = os.path.realpath(job_dir(bridge, 5))
    (command,) = bridge.herdr.commands("agent", "start")
    settings = command[command.index("--settings") + 1]
    assert command[command.index("--") + 1] == "--settings" and settings == f"{folder}/{jobdirs.SETTINGS}"
    inside = f"//{folder.lstrip('/')}/**"
    assert json.loads(Path(settings).read_text()) == {
        "permissions": {"allow": [f"Read({inside})", f"Edit({inside})", f"Write({inside})"]}}


def test_the_settings_never_widen_to_a_bypass_mode_a_parent_or_a_bash_rule(bridge: Bridge) -> None:
    start_job(bridge, 5)
    text = (job_dir(bridge, 5) / jobdirs.SETTINGS).read_text()
    folder = os.path.realpath(job_dir(bridge, 5))
    rules = json.loads(text)["permissions"]
    assert set(rules) == {"allow"}
    assert all(r.startswith(("Read(", "Edit(", "Write(")) and r.endswith(f"{folder}/**)") for r in rules["allow"])
    assert "bypass" not in text.lower() and "defaultMode" not in text and "skip" not in text.lower()


def test_a_model_comes_after_the_settings_flag(bridge: Bridge) -> None:
    made = bridge.start(job_dir(bridge, 5), "job-5", model="opus")
    assert made.status == 200
    (command,) = bridge.herdr.commands("agent", "start")
    assert command[command.index("--") + 1:][0::2] == ("--settings", "--model")


def test_a_session_outside_a_job_folder_gets_no_settings_and_no_flag(bridge: Bridge) -> None:
    for where in (bridge.mkdir("proj"), bridge.root / "ashley-jobs" / "notes", bridge.root / "other" / "j1",
                  bridge.root / "ashley-jobs" / "j1" / "sub"):
        bridge.start(where, "x" + where.name.replace("_", "-").lower())
    assert all("--settings" not in c for c in bridge.herdr.commands("agent", "start"))
    assert not list(bridge.root.rglob(jobdirs.SETTINGS))


@pytest.mark.parametrize("bad", ["/w/with space/ashley-jobs/j7", "/w/a*b/ashley-jobs/j7", "/w/a[1]/ashley-jobs/j7",
                                 "/w/a(1)/ashley-jobs/j7", "/w/a!/ashley-jobs/j7"])
def test_a_path_a_rule_cannot_name_exactly_is_refused(bad: str) -> None:
    with pytest.raises(BridgeError):
        jobdirs.permissions(bad)


def test_the_oldest_folders_beyond_the_newest_few_are_removed_when_a_new_job_starts(bridge: Bridge) -> None:
    for n in (1, 2, 3, 4):
        job_dir(bridge, n).mkdir(parents=True)
        (job_dir(bridge, n) / "out").mkdir()
        (job_dir(bridge, n) / "out" / "r.txt").write_text("kept?")
    start_job(bridge, 5)
    left = sorted(p.name for p in (bridge.root / jobdirs.PARENT).iterdir())
    assert left == ["j3", "j4", "j5"]
    assert "call=job_dirs_pruned removed=2" in bridge.log.text()


def test_job_numbers_are_compared_as_numbers_not_text(bridge: Bridge) -> None:
    for n in (9, 10, 100):
        job_dir(bridge, n).mkdir(parents=True)
    start_job(bridge, 101)
    assert sorted(p.name for p in (bridge.root / jobdirs.PARENT).iterdir()) == ["j10", "j100", "j101"]


def test_a_folder_a_live_session_runs_in_is_never_removed(bridge: Bridge) -> None:
    for n in (1, 2, 3, 4):
        job_dir(bridge, n).mkdir(parents=True)
    bridge.add("alive", cwd=str(job_dir(bridge, 1)))
    start_job(bridge, 5)
    assert sorted(p.name for p in (bridge.root / jobdirs.PARENT).iterdir()) == ["j1", "j3", "j4", "j5"]


def test_nothing_but_job_folders_is_removed_and_a_symlink_is_not_followed(bridge: Bridge) -> None:
    parent = bridge.root / jobdirs.PARENT
    for n in (1, 2, 3):
        job_dir(bridge, n).mkdir(parents=True)
    (parent / "notes").mkdir()
    (parent / "j99").symlink_to(bridge.outside)
    (bridge.outside / "precious").write_text("x")
    (parent / "j00x").write_text("a file")
    start_job(bridge, 4)
    assert sorted(p.name for p in parent.iterdir()) == ["j00x", "j2", "j3", "j4", "j99", "notes"]
    assert (bridge.outside / "precious").read_text() == "x"


def test_a_failed_start_removes_nothing(bridge: Bridge, fake: FakeHerdr) -> None:
    for n in (1, 2, 3, 4):
        job_dir(bridge, n).mkdir(parents=True)
    fake.never_reports = True
    assert bridge.start(job_dir(bridge, 5), "job-5").status == 504
    assert sorted(p.name for p in (bridge.root / jobdirs.PARENT).iterdir()) == ["j1", "j2", "j3", "j4", "j5"]


def test_how_many_folders_are_kept_is_a_setting_with_a_default(tmp_path: Path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    config = Config("127.0.0.1", 1, ("/w",), str(tmp_path), str(ca))
    assert config.keep_job_dirs == 20
    path = tmp_path / "config.json"
    config.dump(path)
    raw = json.loads(path.read_text())
    assert raw["keep_job_dirs"] == 20
    del raw["keep_job_dirs"]
    path.write_text(json.dumps(raw))
    assert load(path).keep_job_dirs == 20
    raw["keep_job_dirs"] = 5
    path.write_text(json.dumps(raw))
    assert load(path).keep_job_dirs == 5


def test_the_served_api_keeps_the_number_of_folders_the_settings_name(bridge: Bridge, fake: FakeHerdr) -> None:
    config = replace(bridge.config, keep_job_dirs=7)
    assert make_api(config, Herdr(fake), MemoryLog()).sessions.keep_job_dirs == 7
