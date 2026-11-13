"""Her reach into the talking person's own Claude Code sessions (`ashley.herdr`), through the bridge they connected
(`ashley.herdr.kind.HERDR`): list the sessions, read a screen, prompt one, start one and close one. Offered per turn by
`ashley.channels.turn_tools.sources` where the reply reaches the speaker alone (as the code host tools are), and only
to a person who connected a bridge. Prompting, starting and closing act on the person's machine and are not proposed
first: the bridge refuses a session that is not ready, and `decisions.md` ("For code and the cluster she is a front for
Claude Code") bounds what she may do. Arguments, screen text and prompts are never logged; `tools.call` carries the
outcome, counts and the bridge's reason."""

import time
from collections.abc import Awaitable, Callable, Mapping

from .. import services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from ..herdr.bridge import Bridge
from ..herdr.model import Access, BridgeFailed, Reason, Session
from ..inference.model import ToolCall, ToolResult, ToolSpec
from . import bench_results, cut
from .bench_args import BadArguments, check_names
from .claude_code_config import ClaudeCodeConfig
from .claude_watching import state_of, watching
from .tools import Catalogue, Tools, ToolsUnavailable

SESSIONS, READ, PROMPT, START, CLOSE = ("claude_sessions", "claude_read", "claude_prompt", "claude_start",
                                        "claude_close")
INSTRUCTIONS = (
    "The person has connected their own Claude Code sessions, so you can drive them: claude_sessions lists the "
    "sessions (id, label, folder and status: idle, working, blocked, done or unknown) with the roots a session may be "
    "started under, claude_read shows the end of "
    "one's screen, claude_prompt sends one a prompt, claude_start starts a new session in a folder and claude_close "
    "ends one. A session is the heavy tool, not the default. It fits work your own tools cannot do: cloning and "
    "examining a repository, running or testing code at length, a multi-step investigation across many files or "
    "sites; and the person's own sessions when they ask about them. Reading a page, a link, a video's description or "
    "a file in a connected code host goes through your own tools (look_up, git_read_file, the bench tools). To hand "
    "work to a session, prompt one that is idle or done, or start one, then claude_read it later for the answer. "
    "Read a session before you prompt it and after, say which session you used, and never claim a prompt did "
    "something you have not read. A session that is working or blocked takes no prompt, and you cannot answer a "
    "dialog it is blocked on: tell the person. A session you start or prompt is watched: when it finishes or blocks "
    "you are woken to read it and tell them, unless the result says watched is false, which you tell them instead. "
    "On a bench, a session the person wants to watch as it runs goes up as a session piece (bench_add, kind session, "
    'body {"source": "herdr", "session": "<its id>"}): their screen shows its output live, and you see only the id. '
    "These act on their machine, so do what they asked and nothing more.")
_HINTS: dict[Reason, str] = {
    "bad_request": "the bridge refused the arguments; a label is a lowercase letter then up to 31 of a-z, 0-9, _ and -, "
                   "a model is a model name, lines are 1 to 400",
    "bad_token": "the bridge turned the person's token away; they can set the bridge up again and replace it in settings",
    "wrong_person": "the bridge serves another person; they can set it up again and replace it in settings",
    "dir_not_allowed": "that folder is outside the roots the bridge was set up with, or is a file; claude_sessions "
                       "lists the roots, and a folder under one may be new",
    "not_found": "no such session, it may have ended; claude_sessions lists the sessions there are",
    "busy": "that session is working; nothing was sent. claude_read it and prompt it once it is idle or done",
    "blocked": "that session is waiting on a dialog only the person can answer; nothing was sent. claude_read shows "
               "what it asks, and tell the person",
    "unknown_state": "that session reports no state; nothing was sent. claude_read it, and try again later",
    "person_typing": "the person is typing in that session; nothing was sent. Try again in a moment",
    "label_taken": "a session already has that label; pick another or claude_sessions to see",
    "herdr_unavailable": "the bridge or herdr there did not answer; nothing was done. Tell the person it is not "
                         "reachable",
    "unconfirmed": "it was sent but not answered, so it may have happened: claude_sessions or claude_read to check "
                   "before you do it again",
    "pin_mismatch": "what answered is not the person's bridge, so nothing was sent; the person can check the bridge's "
                    "address in settings",
    "unexpected": "the bridge answered with something unexpected"}


def specs(config: ClaudeCodeConfig) -> tuple[ToolSpec, ...]:
    session = {"type": "string", "description": "A session's id as claude_sessions gives it"}
    return (
        ToolSpec(SESSIONS, "List the person's Claude Code sessions, and the roots: the absolute folders a session may be "
                           "started under (null when the bridge does not say).", {"type": "object", "properties": {}}, True, outside=False),
        ToolSpec(READ, "Read the end of a session's screen as text.", {
            "type": "object", "required": ["session"], "properties": {"session": session, "lines": {
                "type": "integer", "description": f"How many lines from the end, at most {config.read_lines_max}; "
                                                  f"{config.read_lines} when left out"}}}, True, outside=True),
        ToolSpec(PROMPT, "Send a prompt to a session that is idle or done. A session that is working or blocked "
                         "refuses it.", {
            "type": "object", "required": ["session", "text"], "properties": {"session": session, "text": {
                "type": "string", "description": f"The prompt, at most {config.prompt_chars} characters"}}}, outside=False, tier="judged", label="Sent a prompt to a coding session"),
        ToolSpec(START, "Start a new Claude Code session in a folder the bridge allows, for work that needs a session: a "
                       "clone, a long run, a multi-step investigation.", {
            "type": "object", "required": ["dir", "label"], "properties": {
                "dir": {"type": "string", "description": "The folder's absolute path: a root from claude_sessions or a "
                                                         "path beneath one, which is created if it is new"},
                "label": {"type": "string", "description": "The session's name: lowercase, no spaces"},
                "model": {"type": "string", "description": "A model name; the session's default when left out"}}}, outside=False, tier="judged", label="Started a coding session"),
        ToolSpec(CLOSE, "End a session.", {"type": "object", "required": ["session"], "properties": {"session": session}}, outside=False, tier="judged", label="Ended a coding session"))


class ClaudeCodeTools(Tools):
    def __init__(self, household_id: int, person_id: int, config: ClaudeCodeConfig, result_chars: int,
                 bench_id: int | None = None) -> None:
        self._household = household_id
        self._person = person_id
        self._bench = bench_id   # the bench whose talk this turn is, so a session's finishing wakes that bench
        self._config = config
        self._result_chars = result_chars   # the screen's end is fitted under this, so the loop never cuts it
        self._specs = specs(config)

    async def catalogue(self) -> Catalogue:
        """Empty when the person has connected no bridge. Raises ToolsUnavailable when connections cannot be read."""
        if await self._opened() is None:
            return Catalogue((), None)
        return Catalogue(self._specs, INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no connection, or the bridge failing are each an error result."""
        started = time.monotonic()
        spec = next((s for s in self._specs if s.name == call.name), None)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            opened = await self._opened()
        except ToolsUnavailable:
            return bench_results.failed(call, started, "unavailable", "the person's connections cannot be read")
        if opened is None:
            return bench_results.failed(call, started, "not_connected", "the person has not connected their Claude "
                                        "Code sessions")
        try:
            access = Access.of(opened.connection.base_url, opened.secret, self._person)
            check_names(call.arguments, spec)
            return await self._runner(call.name)(call, started, access)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except BridgeFailed as e:
            return bench_results.failed(call, started, e.reason, _HINTS[e.reason])

    async def _opened(self) -> Opened | None:
        """The person's bridge connection, or None. Raises ToolsUnavailable."""
        try:
            return await ports.opened(services.get(Connections), "herdr", self._household, self._person)
        except ConnectionsUnavailable as e:
            raise ToolsUnavailable("connections unavailable") from e

    async def _sessions(self, call: ToolCall, started: float, access: Access) -> ToolResult:
        found = await services.get(Bridge).sessions(access)
        return bench_results.ok(call, started, {"sessions": [_row(s) for s in found.sessions],
                                                       "roots": None if found.roots is None else list(found.roots)},
                                rows=len(found.sessions))

    async def _read(self, call: ToolCall, started: float, access: Access) -> ToolResult:
        lines = _lines(call.arguments, self._config)
        screen = await services.get(Bridge).read(access, _session(call.arguments), lines)
        text = screen.text

        def end(n: int) -> dict[str, object]:
            return {"text": text[len(text) - n:], "truncated": screen.truncated or n < len(text)}

        return bench_results.ok(call, started, end(cut.fit(len(text), end, self._result_chars)),
                                lines=lines, bytes=len(text.encode()))

    async def _prompt(self, call: ToolCall, started: float, access: Access) -> ToolResult:
        text = _string(call.arguments, "text", self._config.prompt_chars)
        session = _session(call.arguments)
        before = await state_of(access, session)
        await services.get(Bridge).prompt(access, session, text)
        watched = before is not None and await watching(self._household, self._person, self._bench, before)
        return bench_results.ok(call, started, {"sent": True, "watched": watched}, chars=len(text))

    async def _start(self, call: ToolCall, started: float, access: Access) -> ToolResult:
        args = call.arguments
        model = _string(args, "model", 100, required=False)
        made = await services.get(Bridge).start(access, _string(args, "dir", 500), _string(args, "label", 64),
                                                model or None)
        watched = await watching(self._household, self._person, self._bench, made)
        return bench_results.ok(call, started, {**_row(made), "watched": watched}, status=made.status)

    async def _close(self, call: ToolCall, started: float, access: Access) -> ToolResult:
        await services.get(Bridge).close(access, _session(call.arguments))
        return bench_results.ok(call, started, {"closed": True})

    def _runner(self, name: str) -> Callable[[ToolCall, float, Access], Awaitable[ToolResult]]:
        return {SESSIONS: self._sessions, READ: self._read, PROMPT: self._prompt, START: self._start,
                CLOSE: self._close}[name]


def _row(s: Session) -> dict[str, object]:
    return {"id": s.id, "label": s.label, "dir": s.dir, "status": s.status, "last_typed_at": s.last_typed_at}


def _string(args: Mapping[str, object], name: str, longest: int, required: bool = True) -> str:
    value = args.get(name, "")
    if not isinstance(value, str) or "\x00" in value or len(value) > longest or (required and not value.strip()):
        raise BadArguments(f"{name} is a{'' if required else 'n optional'} string of at most {longest} characters")
    return value.strip()


def _session(args: Mapping[str, object]) -> str:
    return _string(args, "session", 100)


def _lines(args: Mapping[str, object], config: ClaudeCodeConfig) -> int:
    value = args.get("lines", config.read_lines)
    if type(value) is not int or not 1 <= value <= config.read_lines_max:
        raise BadArguments(f"lines is a whole number from 1 to {config.read_lines_max}")
    return value
