"""What the bridge does with sessions: list, read, prompt, start and close Claude Code sessions through herdr. Each
method takes a Claude session id (herdr's `agent_session.value`) and resolves it to the live pane per call."""

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from . import jobdirs
from .errors import BridgeError
from .herdr import Agent, Herdr, HerdrError
from .logs import Log
from .runner import HerdrMissing, HerdrTimeout
from .transcripts import Transcripts, latest
T = TypeVar("T")

LABEL = re.compile(r"[a-z][a-z0-9_-]{0,31}")  # herdr's rule for an agent name
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\[\]-]{0,63}")
REFUSED = {"working": "busy", "blocked": "blocked", "unknown": "unknown_state"}


@dataclass(frozen=True)
class Session:
    id: str
    label: str
    dir: str
    status: str
    seq: int
    last_typed_at: str | None

    def wire(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "dir": self.dir,
            "status": self.status,
            "seq": self.seq,
            "last_typed_at": self.last_typed_at,
        }


def guarded(call: Callable[[], T], unsure: str = "herdr_unavailable") -> T:
    """Run one herdr call, turning its failures into the bridge's codes. `unsure` is the code for a call that
    started and did not finish, which for a change means it may have happened."""
    try:
        return call()
    except HerdrMissing as e:
        raise BridgeError("herdr_unavailable") from e
    except HerdrTimeout as e:
        raise BridgeError(unsure) from e
    except HerdrError as e:
        raise BridgeError({"agent_not_found": "not_found", "agent_blocked": "blocked"}.get(e.code, "herdr_unavailable")) from e


class Sessions:
    def __init__(self, herdr: Herdr, roots: tuple[str, ...], start_timeout_ms: int, log: Log, transcripts: Transcripts,
                 settle_s: float = 10.0, pause: Callable[[float], None] = time.sleep, keep_job_dirs: int = 20) -> None:
        self.herdr = herdr
        self.keep_job_dirs = keep_job_dirs
        self.settle_s = settle_s
        self.pause = pause
        self.log = log
        self.transcripts = transcripts
        self.roots = tuple(os.path.realpath(r) for r in roots)
        self.start_timeout_ms = start_timeout_ms
        self.changing = threading.Lock()

    def sessions(self) -> list[Session]:
        agents = guarded(self.herdr.agents)
        tabs = guarded(self.herdr.tab_labels)
        return [self.shape(a, tabs.get(a.tab_id, "")) for a in agents]

    def last_typed(self, listed: list[Session]) -> str | None:
        """The latest time any of the listed sessions was typed into."""
        return latest([s.last_typed_at for s in listed])

    def read(self, session_id: str, lines: int) -> dict[str, object]:
        agent = self.find(session_id)
        body = guarded(lambda: self.herdr.read(agent.pane_id, lines))
        return {"text": body, "truncated": len(body.splitlines()) >= lines, "revision": agent.revision}

    def prompt(self, session_id: str, body: str) -> None:
        with self.changing:
            agent = self.find(session_id)
            if agent.status in REFUSED:
                raise BridgeError(REFUSED[agent.status])
            self.transcripts.ledger.record(session_id, body)
            guarded(lambda: self.herdr.prompt(agent.pane_id, body), unsure="unconfirmed")

    def close(self, session_id: str) -> None:
        with self.changing:
            agent = self.find(session_id)
            guarded(lambda: self.herdr.pane_close(agent.pane_id), unsure="unconfirmed")

    def start(self, directory: str, label: str, model: str | None) -> Session:
        if not LABEL.fullmatch(label) or (model is not None and not MODEL.fullmatch(model)):
            raise BridgeError("bad_request")
        cwd = self.allowed(directory)
        with self.changing:
            running = guarded(self.herdr.agents)
            if any(a.name == label for a in running):
                raise BridgeError("label_taken")
            self.make(cwd)
            settings = jobdirs.write_settings(cwd) if jobdirs.is_job_dir(cwd) else None
            created = guarded(lambda: self.herdr.tab_create(cwd, label))
            try:
                agent = self.herdr.agent_start(label, created.pane_id, model, self.start_timeout_ms, settings)
                up = self.came_up(agent.session_id)
            except (HerdrError, HerdrMissing, HerdrTimeout) as e:
                self.discard(created.tab_id)
                raise BridgeError("unconfirmed") from e
            if up is None:
                self.discard(created.tab_id)
                raise BridgeError("unconfirmed")
            if settings is not None:
                self.prune_job_dirs(cwd, {os.path.realpath(a.cwd) for a in running})
            return self.shape(up, label)

    def prune_job_dirs(self, cwd: str, busy: set[str]) -> None:
        removed = jobdirs.prune(cwd, self.keep_job_dirs, busy)
        if removed:
            self.log.emit(f"call=job_dirs_pruned removed={removed}")

    def came_up(self, session_id: str) -> Agent | None:
        """The started session as herdr lists it once it reports a state, polled for at most `settle_s`."""
        waited = 0.0
        while True:
            for agent in self.herdr.agents():
                if agent.session_id == session_id and agent.status != "unknown":
                    return agent
            if waited >= self.settle_s:
                return None
            self.pause(0.5)
            waited += 0.5

    def allowed(self, directory: str) -> str:
        """The real path of `directory` when it is under a root and is, or could be made, a directory: symlinks and
        `..` are resolved, so what is checked is where the session would run. One answer for outside and
        blocked, so the refusal does not say which paths exist."""
        if "\x00" in directory:
            raise BridgeError("dir_not_allowed")
        real = os.path.realpath(directory)
        inside = any(Path(real).is_relative_to(root) for root in self.roots)
        if not os.path.isabs(directory) or not inside or (os.path.exists(real) and not os.path.isdir(real)):
            raise BridgeError("dir_not_allowed")
        return real

    @staticmethod
    def make(real: str) -> None:
        """Create a directory `allowed` approved. Its existing parents are already resolved, so nothing is followed
        out of the roots; a file in the way is the same refusal."""
        try:
            os.makedirs(real, exist_ok=True)
        except OSError as e:
            raise BridgeError("dir_not_allowed") from e

    def discard(self, tab_id: str) -> None:
        """Close the tab a failed start created, so no empty shell is left behind."""
        try:
            self.herdr.tab_close(tab_id)
        except (HerdrError, HerdrMissing, HerdrTimeout):
            self.log.emit("call=start_cleanup status=failed")

    def session_dir(self, session_id: str) -> str:
        """The real directory a listed session runs in, when it is under a root and exists as a directory."""
        real = self.allowed(self.find(session_id).cwd)
        if not os.path.isdir(real):
            raise BridgeError("dir_not_allowed")
        return real

    def find(self, session_id: str) -> Agent:
        for agent in guarded(self.herdr.agents):
            if agent.session_id == session_id:
                return agent
        raise BridgeError("not_found")

    def shape(self, agent: Agent, tab_label: str) -> Session:
        return Session(
            id=agent.session_id,
            label=agent.name or tab_label,
            dir=os.path.basename(agent.cwd.rstrip("/")),
            status=agent.status,
            seq=agent.seq,
            last_typed_at=self.transcripts.last_typed(agent.session_id),
        )
