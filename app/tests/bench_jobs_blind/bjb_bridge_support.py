"""The bridge half of the blind suite (`bridge/herdr`, spec section 3 and contract item 12): the Api over real Auth,
Sessions and Herdr with the herdr blind suite's fake `herdr`, driven through `Api.handle` as `herdr_bridge_blind` does.
No `ashley` name appears here, so these tests need nothing of the app side. Guesses are marked GUESS in the notes
(`~/scratch/ashley/handoff/blind/blind-notes.txt`)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

from herdr_bridge.api import Api, Response
from herdr_bridge.auth import Auth
from herdr_bridge.files import Limits
from herdr_bridge.herdr import Herdr
from herdr_bridge.sessions import Sessions
from herdr_bridge_blind_pki import Pki, make_pki as make_pki
from herdr_bridge_blind_support import Bridge, MemoryLog, build_bridge, no_pause, transcripts_beside

__all__ = ["Bridge", "Pki", "make_pki", "build_bridge", "files_bridge", "put", "listing", "fetch", "data_of", "tree",
           "session_dir"]

GOOD = "result.txt"


def files_bridge(b: Bridge, **limits: int) -> Bridge:
    """The same bridge with its files limits set (`Config.max_file_bytes`, `Config.max_files`): the Api is rebuilt over the
    same state and the same herdr, as a restart is. GUESS: the Api takes the Config as `config=`."""
    herdr = Herdr(b.herdr, 5.0)
    config = replace(b.config, **limits)
    sessions = Sessions(herdr, config.roots, config.start_timeout_ms, b.log, transcripts_beside(b.state_dir), settle_s=0.05, pause=no_pause)
    b.api = Api(Auth(b.state_dir), sessions, herdr, b.log, Limits(config.max_file_bytes, config.max_files))
    return b


def session_dir(b: Bridge, *parts: str, name: str = "job") -> tuple[str, Path]:
    """A session whose directory is `<root>/<parts>`, and that directory."""
    b.get("/v1/whoami")  # the first authenticated call pins the person in state/; a test's before-tree is taken after it
    where = b.mkdir(*(parts or (name,)))
    made = b.add("alpha", cwd=str(where))
    return made.session_id, where


def put(b: Bridge, sid: str, name: str, data: bytes, length: int | None = None, **kw: Any) -> Response:
    return b.call("PUT", f"/v1/sessions/{sid}/in/{name}", raw=data,
                  headers={"Content-Length": str(len(data) if length is None else length), **kw.pop("headers", {})}, **kw)


def listing(b: Bridge, sid: str) -> Response:
    return b.get(f"/v1/sessions/{sid}/out")


def fetch(b: Bridge, sid: str, name: str) -> Response:
    return b.get(f"/v1/sessions/{sid}/out/{name}")


def data_of(response: Response) -> bytes:
    """The bytes a download answered. `Response.raw` holds them."""
    got = response.raw
    assert isinstance(got, bytes), f"a download answers bytes, got {response}"
    return got


def tree(root: Path) -> list[str]:
    """Every path under `root`, as relative strings: what a call must not have changed."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def log_text(b: Bridge) -> str:
    log: MemoryLog = b.log
    return log.text()
