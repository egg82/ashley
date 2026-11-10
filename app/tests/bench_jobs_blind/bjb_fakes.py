"""The bench-jobs blind suite's stand-ins (part of `bjb_support`, whose docstring holds the suite's rules): a scripted
model that keeps every prompt, what a model was shown, and a bridge that keeps sessions and files in memory."""

import asyncio
import inspect
import json
from collections.abc import Sequence
from typing import Any

from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, OutFile, Reason, Screen, Session, SessionList, Status, Whoami
from ashley.inference.inference import Inference
from ashley.inference.model import Entry, Message, Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript

ROOT = "/work"



def out_file(name: str, size: int) -> Any:
    return OutFile(name, size)


# --- a scripted model ---------------------------------------------------------------------------------------------------

HANG: Any = object()
"""A step that never returns: the model is still thinking when a deadline passes or the person cancels."""

Step = Any


class Scripted(Inference):
    """Answers each step from `script` (a ToolCalls, a dict re-read as the step's `output`, an exception, or a function of
    the prompt). `hang` makes the next step wait forever. Every prompt is kept, with its task."""

    def __init__(self) -> None:
        self.script: list[Step] = []
        self.asked: list[tuple[Task, Prompt]] = []
        self.hang = False
        self.routed: dict[str, list[Step]] = {}

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        self.asked.append((task, prompt))
        if self.hang:
            await asyncio.Event().wait()
        script = self.script
        if self.routed:
            key = next(k for k in self.routed if k in first_user_message(prompt))
            script = self.routed[key]
        assert script, "the model was asked for a step nobody scripted"
        got = script.pop(0)
        if got is HANG:
            await asyncio.Event().wait()
        if callable(got):
            got = got(prompt)
            if inspect.isawaitable(got):
                got = await got
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got)

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        raise AssertionError("a job steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


def finished(summary: str = "all done", pieces: Sequence[int] = ()) -> dict[str, Any]:
    """The agent's last step: `JobResult` {done, summary, pieces}."""
    return {"done": True, "summary": summary, "pieces": list(pieces)}


def calls_of(*pairs: tuple[str, dict[str, object]], prefix: str = "k") -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"{prefix}{i}", n, a) for i, (n, a) in enumerate(pairs)))


def texts(prompt: Prompt) -> list[str]:
    """Every string a model is shown in one prompt: system, messages, calls (names and arguments) and results."""
    found = [s.text for s in prompt.system.values()]
    for entry in prompt.messages:
        found.extend(_entry_texts(entry))
    found.extend(spec.name + " " + spec.description for spec in prompt.tools)
    return found


def _entry_texts(entry: Entry) -> list[str]:
    if isinstance(entry, Message):
        return [entry.text]
    if isinstance(entry, ToolCalls):
        return [c.name + " " + json.dumps(c.arguments) for c in entry.calls]
    assert isinstance(entry, ToolResults)
    return [r.content for r in entry.results]


def everything_shown(model: Scripted) -> str:
    return "\n".join(t for _, p in model.asked for t in texts(p))


def first_user_message(prompt: Prompt) -> str:
    first = prompt.messages[0]
    assert isinstance(first, Message)
    return first.text


def results_seen(model: Scripted) -> list[ToolResult]:
    """Every tool result the model was shown over its runs, in order: for each job (told apart by its first message), the
    results of its longest prompt, which holds the whole exchange."""
    longest: dict[str, Prompt] = {}
    for _, p in model.asked:
        key = first_user_message(p)
        if key not in longest or len(p.messages) > len(longest[key].messages):
            longest[key] = p
    return [r for p in longest.values() for e in p.messages if isinstance(e, ToolResults) for r in e.results]


# --- a bridge that keeps files --------------------------------------------------------------------------------------


class FakeBridge(Bridge):
    """The app's port to a bridge (I7), in memory: sessions, what was uploaded, what `out/` holds, and every call as
    (name, ...). A session's seq rises on a prompt; `settle` sets a status and raises it as the bridge does."""

    def __init__(self) -> None:
        self.files = True
        self.roots: tuple[str, ...] | None = (ROOT,)
        self.sessions_: dict[str, Session] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.inbox: dict[str, dict[str, bytes]] = {}
        self.out: dict[str, dict[str, bytes]] = {}
        self.prompts: dict[str, list[str]] = {}
        self.closed: list[str] = []
        self.fail: dict[str, Reason] = {}
        self.count = 0
        self.phantom: dict[str, list[Any]] = {}

    def named(self, call_name: str) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == call_name]

    def _go(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        if name in self.fail:
            raise BridgeFailed(self.fail[name])

    def settle(self, session: str, status: Status) -> None:
        s = self.sessions_[session]
        self.sessions_[session] = Session(s.id, s.label, s.dir, status, s.seq + 1, None)

    async def whoami(self, access: Access) -> Whoami:
        self._go("whoami")
        if self.files:
            return Whoami("0.2.0", "1", str(access.person), capabilities=("files",))
        return Whoami("0.1.0", "1", str(access.person))

    async def sessions(self, access: Access) -> SessionList:
        self._go("sessions")
        return SessionList(tuple(self.sessions_.values()), None, self.roots)

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        self._go("read", session_id)
        return Screen("screen", False, 1)

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        self._go("prompt", session_id, text)
        self.prompts.setdefault(session_id, []).append(text)
        self.settle(session_id, "working")

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        self._go("start", directory, label)
        if self.roots is None or not any(directory == r or directory.startswith(r.rstrip("/") + "/") for r in self.roots):
            raise BridgeFailed("dir_not_allowed")
        self.count += 1
        made = Session(f"sess-{self.count}", label, directory, "idle", 1, None)
        self.sessions_[made.id] = made
        self.inbox[made.id], self.out[made.id] = {}, {}
        return made

    async def close(self, access: Access, session_id: str) -> None:
        self._go("close", session_id)
        self.closed.append(session_id)
        self.sessions_.pop(session_id, None)

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        self._go("upload", session_id, name, len(data))
        self.inbox.setdefault(session_id, {})[name] = data

    async def outputs(self, access: Access, session_id: str) -> tuple[Any, ...]:
        self._go("outputs", session_id)
        listed = tuple(out_file(n, len(d)) for n, d in self.out.get(session_id, {}).items())
        return (*listed, *self.phantom.get(session_id, ()))

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        self._go("download", session_id, name)
        data = self.out[session_id][name]
        if len(data) > max_bytes:
            raise BridgeFailed("bad_request")
        return data

    def refused_file_names(self) -> list[str]:
        return [n for files in self.inbox.values() for n in files]
