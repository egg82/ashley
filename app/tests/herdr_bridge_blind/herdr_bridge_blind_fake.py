"""A fake `herdr` for the bridge blind suite: the only thing outside the process. It answers in the shape of the
captured real CLI output (tests/herdr_captured), keeps agents and tabs in memory, and records every argv it is given.
It refuses any command outside the set the bridge is documented to need."""

import copy
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from herdr_bridge.jsonget import items, obj
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, Outcome, Runner

CAPTURED = Path(__file__).resolve().parent.parent / "herdr_captured"
NOUNS = ("agent", "tab", "pane")
ALLOWED = {
    ("agent", "list"),
    ("agent", "get"),
    ("agent", "read"),
    ("agent", "prompt"),
    ("agent", "start"),
    ("tab", "list"),
    ("tab", "create"),
    ("tab", "close"),
    ("pane", "close"),
}
SCREEN = "line one\nSCREEN-MARKER-7\nlast line\n"


def captured(name: str) -> dict[str, object]:
    return obj(json.loads((CAPTURED / name).read_text()))


def captured_agent() -> dict[str, object]:
    return copy.deepcopy(items(obj(captured("agent_list.json")["result"])["agents"])[0])


def answer(name: str, **result: object) -> Outcome:
    """A captured answer with the named parts of its result replaced."""
    doc = captured(name)
    doc["result"] = {**obj(doc["result"]), **result}
    return Outcome(0, json.dumps(doc), "")


@dataclass
class FakeAgent:
    session_id: str
    name: str
    status: str = "idle"
    cwd: str = "/home/person/work"
    seq: int = 7
    agent: str = "claude"
    with_session: bool = True
    started_here: bool = False
    pane_id: str = field(default_factory=lambda: "w1:p" + uuid.uuid4().hex[:6])

    @property
    def tab_id(self) -> str:
        return "w1:t" + self.pane_id[4:]

    def record(self, status: str | None = None) -> dict[str, object]:
        rec = captured_agent()
        rec.update(
            agent=self.agent,
            agent_status=status or self.status,
            cwd=self.cwd,
            foreground_cwd=self.cwd,
            name=self.name,
            pane_id=self.pane_id,
            tab_id=self.tab_id,
            state_change_seq=self.seq,
            revision=11,
        )
        rec.pop("agent_session")
        if self.with_session:
            rec["agent_session"] = {"agent": self.agent, "kind": "id", "source": "x", "value": self.session_id}
        return rec


def failure(code: str) -> Outcome:
    doc = captured("agent_not_found.err")
    doc["error"] = {**obj(doc["error"]), "code": code}
    body = json.dumps(doc)
    return Outcome(1, body, body)


def verb_of(argv: Sequence[str]) -> tuple[str, str]:
    for i, a in enumerate(argv):
        if a in NOUNS and i + 1 < len(argv):
            return a, argv[i + 1]
    return ("?", "?")


def flag(argv: Sequence[str], name: str) -> str:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a[len(name) + 1 :]
    return ""


@dataclass
class FakeHerdr(Runner):
    agents: list[FakeAgent] = field(default_factory=list[FakeAgent])
    tabs: dict[str, str] = field(default_factory=dict[str, str])
    tab_cwds: dict[str, str] = field(default_factory=dict[str, str])
    calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    closed: list[str] = field(default_factory=list[str])
    fail: dict[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    screen: str = (CAPTURED / "agent_read.txt").read_text() + SCREEN
    version_out: str = (CAPTURED / "version.out").read_text()
    unknown_polls: int = 0
    never_reports: bool = False
    polls: int = 0

    def add(self, agent: FakeAgent) -> FakeAgent:
        self.agents.append(agent)
        self.tabs[agent.tab_id] = agent.name
        return agent

    def commands(self, noun: str, verb: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if verb_of(c) == (noun, verb)]

    def changes(self) -> list[tuple[str, ...]]:
        mutating = {("agent", "prompt"), ("agent", "start"), ("tab", "create"), ("tab", "close"), ("pane", "close")}
        return [c for c in self.calls if verb_of(c) in mutating]

    def run(self, args: Sequence[str], timeout_s: float) -> Outcome:
        argv = tuple(args)
        self.calls.append(argv)
        if argv == ("--version",):
            return Outcome(0, self.version_out, "")
        verb = verb_of(argv)
        assert verb in ALLOWED, f"the bridge ran a herdr command outside its documented set: {argv}"
        rule = self.fail.get(verb)
        if rule == "timeout":
            raise HerdrTimeout()
        if rule == "missing":
            raise HerdrMissing()
        if rule:
            return failure(rule)
        return self.handlers()[verb](argv)

    def handlers(self) -> dict[tuple[str, str], Callable[[tuple[str, ...]], Outcome]]:
        return {
            ("agent", "list"): self.agent_list,
            ("agent", "get"): self.agent_get,
            ("agent", "read"): self.agent_read,
            ("agent", "prompt"): self.agent_prompt,
            ("agent", "start"): self.agent_start,
            ("tab", "list"): self.tab_list,
            ("tab", "create"): self.tab_create,
            ("tab", "close"): self.tab_close,
            ("pane", "close"): self.pane_close,
        }

    def target(self, argv: tuple[str, ...]) -> FakeAgent | None:
        for a in self.agents:
            if any(w in (a.pane_id, a.tab_id, a.name, a.session_id) for w in argv[2:]):
                return a
        return None

    def agent_list(self, argv: tuple[str, ...]) -> Outcome:
        self.polls += 1
        quiet = self.polls <= self.unknown_polls
        shown = [a.record("unknown" if quiet and a.started_here else None) for a in self.agents]
        return answer("agent_list.json", agents=shown)

    def agent_get(self, argv: tuple[str, ...]) -> Outcome:
        a = self.target(argv)
        return answer("agent_get.json", agent=a.record()) if a else failure("agent_not_found")

    def agent_read(self, argv: tuple[str, ...]) -> Outcome:
        return Outcome(0, self.screen, "") if self.target(argv) else failure("agent_not_found")

    def agent_prompt(self, argv: tuple[str, ...]) -> Outcome:
        a = self.target(argv)
        return answer("agent_prompt.json", agent=a.record()) if a else failure("agent_not_found")

    def tab_list(self, argv: tuple[str, ...]) -> Outcome:
        template = items(obj(captured("tab_list.json")["result"])["tabs"])[0]
        return answer("tab_list.json", tabs=[{**template, "label": lab, "tab_id": tid} for tid, lab in self.tabs.items()])

    def tab_create(self, argv: tuple[str, ...]) -> Outcome:
        n = uuid.uuid4().hex[:6]
        tab, pane = f"w1:t{n}", f"w1:p{n}"
        self.tabs[tab] = flag(argv, "--label")
        self.tab_cwds[tab] = flag(argv, "--cwd")
        base = obj(captured("tab_create.json")["result"])
        cwd = self.tab_cwds[tab]
        root = {**obj(base["root_pane"]), "pane_id": pane, "tab_id": tab, "cwd": cwd, "foreground_cwd": cwd}
        return answer("tab_create.json", root_pane=root, tab={**obj(base["tab"]), "label": self.tabs[tab], "tab_id": tab})

    def agent_start(self, argv: tuple[str, ...]) -> Outcome:
        pane = next((w for w in argv if w.startswith("w1:p")), "")
        tab = "w1:t" + pane[4:]
        if tab not in self.tabs:
            return failure("pane_not_found")
        status = "unknown" if self.never_reports else "idle"
        made = FakeAgent(str(uuid.uuid4()), self.tabs[tab], status, self.tab_cwds[tab], 1, started_here=True)
        made.pane_id = pane
        self.agents.append(made)
        return answer("agent_start.json", agent=made.record())

    def pane_close(self, argv: tuple[str, ...]) -> Outcome:
        pane = next((w for w in argv[2:] if w.startswith("w1:p")), None)
        if pane is None:
            return failure("pane_not_found")
        self.drop("w1:t" + pane[4:])
        return Outcome(0, (CAPTURED / "pane_close.json").read_text(), "")

    def tab_close(self, argv: tuple[str, ...]) -> Outcome:
        tab = next((w for w in argv[2:] if w in self.tabs), None)
        if tab is None:
            return failure("tab_not_found")
        self.drop(tab)
        return Outcome(0, (CAPTURED / "pane_close.json").read_text(), "")

    def drop(self, tab: str) -> None:
        self.closed.append(tab)
        self.tabs.pop(tab, None)
        self.agents[:] = [a for a in self.agents if a.tab_id != tab]
