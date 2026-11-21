"""The BrowserSessions service (`ashley.services`): drive one page in a headless browser for a session of minutes, one pod
per session, for the services that have no API. `kubernetes_session.KubernetesSessions` runs `driver.py` in a pod with
public HTTPS egress and nothing private; the Null Object drives nothing. A session belongs to one conversation of one
household (`Who`), starts with the first `navigate`, and ends at its time or action cap (`looks.json`), when `end` is
called, or when its pod is gone, and its pod is deleted however it ends. Nothing of a session outlives it: no profile,
no cookies.

What it holds is the page as the browser has it: its text is outside words, never logged. A field for a password, a
one-time code or a card refuses `type` (`secret_field`): her tools do not enter them. Logs carry ids, counts and
durations, never an address or what the page held."""

from abc import abstractmethod
from dataclasses import dataclass

from ..services import Service

ACTIONS = ("navigate", "click", "type", "select")
REASONS = frozenset({
    "not_wired", "busy", "unavailable", "no_session", "ended_time", "ended_actions", "bad_request", "stale_ref",
    "no_such_ref", "secret_field", "page_timeout", "page_error", "failed"})


class SessionUnavailable(Exception):
    """The session could not do what was asked. `args[0]` is a short reason from `REASONS`: no browser is wired
    (`not_wired`), `max_sessions` are running (`busy`), the pod or the API could not be reached (`unavailable`), there is no
    session to snapshot or act in (`no_session`), it ended (`ended_time`, `ended_actions`), or the page refused the
    step."""


@dataclass(frozen=True)
class Who:
    """Whose session: a conversation of a household."""

    household_id: int
    conversation_id: int


@dataclass(frozen=True)
class Act:
    """One step. `navigate` takes `url`, `click` a `ref`, `type` a `ref` and `text` (and `submit`, to press Enter after),
    `select` a `ref` and the `value` of an option as the snapshot names it."""

    action: str
    ref: str | None = None
    text: str | None = None
    value: str | None = None
    url: str | None = None
    submit: bool = False


@dataclass(frozen=True)
class Node:
    """One element of a snapshot: its `ref`, `role` and `name`, and what the page says of it (`secret` for a field she
    does not type into, `options` of a choice)."""

    ref: str
    role: str
    name: str
    secret: bool = False
    disabled: bool = False
    checked: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    """The page's accessibility tree: `nodes` in page order, `cut` when the page held more than the snapshot's limit,
    and what is left of the session."""

    url: str
    title: str
    nodes: tuple[Node, ...]
    cut: bool
    seconds_left: int
    actions_left: int


@dataclass(frozen=True)
class Acted:
    """What is left of the session after a step."""

    seconds_left: int
    actions_left: int


class BrowserSessions(Service):
    @classmethod
    def null(cls) -> "BrowserSessions":
        return NullBrowserSessions()

    @abstractmethod
    def drives(self) -> bool:
        """Whether it can drive a page at all."""

    @abstractmethod
    async def snapshot(self, who: Who) -> Snapshot:
        """The page of `who`'s session, as it is now. Raises SessionUnavailable."""

    @abstractmethod
    async def act(self, who: Who, act: Act) -> Acted:
        """Do `act` in `who`'s session; a `navigate` with none running starts one (a pod of its own, and for `busy` no
        pod). The reference of any other step is checked against a fresh snapshot first. Raises SessionUnavailable."""

    @abstractmethod
    async def end(self, who: Who) -> bool:
        """End `who`'s session now; whether there was one."""


class NullBrowserSessions(BrowserSessions):
    def drives(self) -> bool:
        return False

    async def snapshot(self, who: Who) -> Snapshot:
        raise SessionUnavailable("not_wired")

    async def act(self, who: Who, act: Act) -> Acted:
        raise SessionUnavailable("not_wired")

    async def end(self, who: Who) -> bool:
        return False
