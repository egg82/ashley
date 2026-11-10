"""The tags of the images CI builds. The test image's: the first 12 hex digits of sha256 over app/requirements.txt,
app/requirements-dev.txt and app/ci/Containerfile, concatenated in that order (the build job reproduces it with
`cat ... | sha256sum`). The browser image's and the media image's: the same over deploy/look/Containerfile and
deploy/media/Containerfile alone. The CAD image's: the same over deploy/cad/Containerfile,
deploy/cad/ashley_cad.py then deploy/cad/ashley_print.py, since the helper is baked into the image. The mail bridge image's: the same over
deploy/mail-bridge/Containerfile, `bridge.proto` and the keeper's `keeper*.py` in name order, all of which are baked in.

    python tools/ci_image_hash.py           print the test image's hash
    python tools/ci_image_hash.py --look    print the browser image's hash
    python tools/ci_image_hash.py --media   print the media image's hash
    python tools/ci_image_hash.py --cad     print the CAD image's hash
    python tools/ci_image_hash.py --bridge  print the mail bridge image's hash"""
import hashlib
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
FILES = ("requirements.txt", "requirements-dev.txt", "ci/Containerfile")
LOOK_FILE = APP.parent / "deploy" / "look" / "Containerfile"
MEDIA_FILE = APP.parent / "deploy" / "media" / "Containerfile"
CAD_FILES = tuple(APP.parent / "deploy" / "cad" / f for f in ("Containerfile", "ashley_cad.py", "ashley_print.py"))
BRIDGE_DIR = APP.parent / "deploy" / "mail-bridge"


def bridge_files(directory: Path = BRIDGE_DIR) -> tuple[Path, ...]:
    """What the mail bridge image bakes in, in the order they are hashed."""
    return (directory / "Containerfile", directory / "bridge.proto", *sorted(directory.glob("keeper*.py")))


def image_hash(app: Path = APP) -> str:
    return hashlib.sha256(b"".join((app / f).read_bytes() for f in FILES)).hexdigest()[:12]


def look_hash(containerfile: Path = LOOK_FILE) -> str:
    return hashlib.sha256(containerfile.read_bytes()).hexdigest()[:12]


def media_hash(containerfile: Path = MEDIA_FILE) -> str:
    return hashlib.sha256(containerfile.read_bytes()).hexdigest()[:12]


def cad_hash(files: tuple[Path, ...] = CAD_FILES) -> str:
    return hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:12]


def bridge_hash(directory: Path = BRIDGE_DIR) -> str:
    return hashlib.sha256(b"".join(f.read_bytes() for f in bridge_files(directory))).hexdigest()[:12]


if __name__ == "__main__":
    print(look_hash() if "--look" in sys.argv else media_hash() if "--media" in sys.argv else
          cad_hash() if "--cad" in sys.argv else bridge_hash() if "--bridge" in sys.argv else image_hash())
