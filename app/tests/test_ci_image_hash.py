"""Each image's tag is the hash of the files it bakes in (tools/ci_image_hash.py): a change to any of them moves the
tag, so CI builds the image again instead of reusing the old one."""
from pathlib import Path

from tools import ci_image_hash


def test_the_mail_bridge_hash_covers_every_keeper_module_and_not_its_image_test(tmp_path: Path) -> None:
    names = [f.name for f in ci_image_hash.bridge_files()]
    assert names[:2] == ["Containerfile", "bridge.proto"] and "keeper.py" in names and len(names) > 5
    assert "test_keeper_image.py" not in names
    containerfile = (ci_image_hash.BRIDGE_DIR / "Containerfile").read_text()
    assert all(name in containerfile for name in names[2:]), "a keeper module the image does not copy"
    for f in ci_image_hash.bridge_files():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    assert ci_image_hash.bridge_hash(tmp_path) == ci_image_hash.bridge_hash()
    (tmp_path / "keeper_relay.py").write_text("changed\n")
    assert ci_image_hash.bridge_hash(tmp_path) != ci_image_hash.bridge_hash()


def test_a_changed_helper_changes_the_cad_hash(tmp_path: Path) -> None:
    copies = tuple(tmp_path / f.name for f in ci_image_hash.CAD_FILES)
    for src, dst in zip(ci_image_hash.CAD_FILES, copies):
        dst.write_bytes(src.read_bytes())
    assert ci_image_hash.cad_hash(copies) == ci_image_hash.cad_hash()
    copies[1].write_text(copies[1].read_text() + "\n")
    assert ci_image_hash.cad_hash(copies) != ci_image_hash.cad_hash()


def test_the_media_image_pins_the_wyoming_version_the_app_does() -> None:
    pinned = [line for line in (ci_image_hash.APP / "requirements.txt").read_text().splitlines()
              if line.startswith("wyoming==")]
    assert len(pinned) == 1 and pinned[0] in ci_image_hash.MEDIA_FILE.read_text()


def test_a_changed_containerfile_changes_the_browser_hash(tmp_path: Path) -> None:
    copy = tmp_path / "Containerfile"
    copy.write_bytes(ci_image_hash.LOOK_FILE.read_bytes())
    assert ci_image_hash.look_hash(copy) == ci_image_hash.look_hash()
    copy.write_text(copy.read_text() + "RUN true\n")
    assert ci_image_hash.look_hash(copy) != ci_image_hash.look_hash()


def test_a_changed_requirement_changes_the_hash(tmp_path: Path) -> None:
    for f in ci_image_hash.FILES:
        (tmp_path / f).parent.mkdir(exist_ok=True)
        (tmp_path / f).write_bytes((ci_image_hash.APP / f).read_bytes())
    before = ci_image_hash.image_hash(tmp_path)
    assert before == ci_image_hash.image_hash()
    with (tmp_path / "requirements-dev.txt").open("a") as f:
        f.write("one-more-package==1.0\n")
    assert ci_image_hash.image_hash(tmp_path) != before
