"""What the bridge answers in, as values."""

from dataclasses import dataclass
from typing import Literal

from ..connections import address

Reason = Literal["bad_request", "bad_token", "wrong_person", "dir_not_allowed", "not_found", "busy", "blocked",
                 "unknown_state", "person_typing", "label_taken", "herdr_unavailable", "unconfirmed", "pin_mismatch",
                 "bad_path", "too_many", "too_large", "unexpected"]
"""Why a call failed. The bridge's own codes (`bridge/herdr/README.md`), and three of this side's: `herdr_unavailable`
is also the answer when nothing reached the bridge (down, unreachable, no TLS); `pin_mismatch`, what answered is not
the certificate pinned, and nothing was sent to it; `unexpected`, what answered is not the bridge's API, or an error
code it does not have. `unconfirmed` is also a change whose answer never came after it was sent."""

Status = Literal["idle", "working", "blocked", "done", "unknown"]


class BridgeFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class Access:
    """Everything a call to one bridge needs: the `https` address (`origin`, a path allowed), the lowercase hex sha256
    of the DER certificate it must present (`fingerprint`), the token, and the id of the person it is for."""

    origin: str
    fingerprint: str
    token: str
    person: int

    @classmethod
    def of(cls, base_url: str, token: str, person: int) -> "Access":
        """The access for a connection's stored address, `https://host:7843#sha256=<hex>`. Raises BridgeFailed
        (`unexpected`) for an address without a fingerprint, which is never trusted."""
        origin, _, pin = base_url.partition("#")
        match = address.PIN.fullmatch(pin)
        if match is None or not origin:
            raise BridgeFailed("unexpected")
        return cls(origin, match[1].lower(), token, person)


@dataclass(frozen=True)
class Whoami:
    bridge_version: str
    herdr_version: str | None
    person: str | None
    capabilities: tuple[str, ...] = ()
    """What the bridge can do beyond the original five calls (`files`); empty for a bridge that does not say."""


@dataclass(frozen=True)
class Session:
    """One Claude Code session. `id` is the Claude session id, stable across pane moves; `seq` counts its state
    changes; `last_typed_at` is an ISO time or None when the bridge cannot say."""

    id: str
    label: str
    dir: str
    status: Status
    seq: int
    last_typed_at: str | None


@dataclass(frozen=True)
class SessionList:
    """`roots` are the absolute folders the bridge allows a start under (a new folder beneath one is created); None
    when the bridge is too old to say."""

    sessions: tuple[Session, ...]
    last_typed_at: str | None
    roots: tuple[str, ...] | None = None


@dataclass(frozen=True)
class OutFile:
    """A regular file in a session's `out/`: its flat name and size in bytes."""

    name: str
    bytes: int


@dataclass(frozen=True)
class Screen:
    text: str
    truncated: bool
    revision: int
