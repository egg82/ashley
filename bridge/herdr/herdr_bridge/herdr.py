"""The `herdr` CLI as typed calls. Only the commands the bridge needs exist here; there is no way to send keys, text
or input to a pane, or to run a command in one."""

import json
from dataclasses import dataclass

from .jsonget import integer, items, obj, text
from .runner import Outcome, Runner

STATUSES = ("idle", "working", "blocked", "done", "unknown")


class HerdrError(Exception):
    """`herdr` ran and answered with an error; `code` is herdr's own (`agent_not_found`, `agent_blocked`, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Agent:
    session_id: str
    pane_id: str
    tab_id: str
    name: str | None
    status: str
    seq: int
    cwd: str
    revision: int


@dataclass(frozen=True)
class Created:
    tab_id: str
    pane_id: str


def parse_agent(d: dict[str, object]) -> Agent | None:
    """None for anything but a Claude agent whose session id herdr knows."""
    session = obj(d.get("agent_session"))
    sid, pane, tab = text(session, "value"), text(d, "pane_id"), text(d, "tab_id")
    if d.get("agent") != "claude" or sid is None or pane is None or tab is None:
        return None
    status = text(d, "agent_status")
    return Agent(
        session_id=sid,
        pane_id=pane,
        tab_id=tab,
        name=text(d, "name"),
        status=status if status in STATUSES else "unknown",
        seq=integer(d, "state_change_seq") or 0,
        cwd=text(d, "cwd") or "",
        revision=integer(d, "revision") or 0,
    )


def decode(done: Outcome) -> dict[str, object]:
    """The `result` object of a successful call; raises HerdrError for a failed one."""
    if done.code != 0:
        try:
            code = text(obj(obj(json.loads(done.err)).get("error")), "code")
        except ValueError:
            code = None
        raise HerdrError(code or "failed")
    try:
        return obj(obj(json.loads(done.out)).get("result"))
    except ValueError as e:
        raise HerdrError("bad_output") from e


class Herdr:
    def __init__(self, runner: Runner, timeout_s: float = 15.0) -> None:
        self.runner = runner
        self.timeout_s = timeout_s

    def call(self, *args: str, timeout_s: float | None = None) -> Outcome:
        return self.runner.run(args, timeout_s or self.timeout_s)

    def version(self) -> str | None:
        out = self.call("--version").out.split()
        return out[1] if len(out) == 2 and out[0] == "herdr" else None

    def agents(self) -> list[Agent]:
        listed = items(decode(self.call("agent", "list")).get("agents"))
        return [a for a in (parse_agent(d) for d in listed) if a is not None]

    def tab_labels(self) -> dict[str, str]:
        listed = items(decode(self.call("tab", "list")).get("tabs"))
        return {t: label for d in listed if (t := text(d, "tab_id")) and (label := text(d, "label"))}

    def read(self, pane_id: str, lines: int) -> str:
        """The pane's recent unwrapped history; the visible screen while the agent is working, as herdr cannot scroll then."""
        done = self.call("agent", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines))
        if done.code != 0:
            try:
                decode(done)
            except HerdrError as e:
                if e.code != "agent_not_idle":
                    raise
                done = self.call("agent", "read", pane_id, "--source", "visible", "--lines", str(lines))
                if done.code != 0:
                    decode(done)
        return done.out

    def prompt(self, pane_id: str, body: str) -> None:
        decode(self.call("agent", "prompt", pane_id, body))

    def tab_create(self, cwd: str, label: str) -> Created:
        result = decode(self.call("tab", "create", "--cwd", cwd, "--label", label, "--no-focus"))
        tab, pane = text(obj(result.get("tab")), "tab_id"), text(obj(result.get("root_pane")), "pane_id")
        if tab is None or pane is None:
            raise HerdrError("bad_output")
        return Created(tab, pane)

    def agent_start(self, name: str, pane_id: str, model: str | None, timeout_ms: int,
                    settings: str | None = None) -> Agent:
        """`settings` is a Claude Code settings file the session is started with (`claude --settings`)."""
        args = ["agent", "start", name, "--kind", "claude", "--pane", pane_id, "--timeout", str(timeout_ms)]
        extra = (["--settings", settings] if settings is not None else []) + (["--model", model] if model is not None else [])
        if extra:
            args += ["--", *extra]
        result = decode(self.call(*args, timeout_s=timeout_ms / 1000 + 10))
        agent = parse_agent(obj(result.get("agent")))
        if agent is None:
            raise HerdrError("bad_output")
        return agent

    def pane_close(self, pane_id: str) -> None:
        decode(self.call("pane", "close", pane_id))

    def tab_close(self, tab_id: str) -> None:
        decode(self.call("tab", "close", tab_id))
