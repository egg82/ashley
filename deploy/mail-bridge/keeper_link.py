"""What the keeper needs of Bridge, as plain values and one interface (`BridgeLink`), so the keeper's rules are tested
against a fake and only `keeper_grpc.GrpcBridge` knows Bridge's wire."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

UserState = Literal["connected", "signed_out", "locked"]
LoginKind = Literal["tfa", "two_passwords", "human_verification", "error", "finished"]
Reason = Literal["credentials", "code", "mailbox_password", "paid_plan", "connection", "aborted", "verification",
                 "security_key", "other"]


@dataclass(frozen=True)
class LoginEvent:
    """What Bridge answered a login call with: it wants a two-factor code (`tfa`) or the second password
    (`two_passwords`), it wants the person to pass Proton's human check at `url` (`human_verification`; the URL carries a
    token), it refused for `reason` (`error`), or the user `user_id` is logged in (`finished`)."""

    kind: LoginKind
    user_id: str = ""
    reason: Reason = "other"
    url: str = field(repr=False, default="")


@dataclass(frozen=True)
class UserInfo:
    """A Proton user Bridge holds. `password` is the one it issued for IMAP and SMTP; `addresses` are the account's own
    addresses, each its own mailbox once `split` (split address mode) is on."""

    id: str
    state: UserState
    split: bool
    addresses: tuple[str, ...]
    password: str = field(repr=False, default="")


@dataclass(frozen=True)
class UserEvent:
    """Something Bridge reported about one user: its `state` changed (`state` set), or a sync `started`, made
    `progress` (0 to 1) or `finished`."""

    user_id: str
    state: UserState | None = None
    sync: Literal["started", "progress", "finished"] | None = None
    progress: float | None = None


class BridgeLink(Protocol):
    """A connection to a running Bridge. Every call blocks; a failure is an exception (`BridgeError`)."""

    def watch(self, on_event: Callable[[UserEvent], None]) -> None:
        """Start relaying user events to `on_event`, from another thread, until `close`."""

    def login(self, username: str, password: str, verified: bool = False) -> LoginEvent:
        """Bridge's `Login`; `verified` retries it with the human-check details Bridge kept from its last
        `human_verification` answer."""
        ...

    def second_factor(self, username: str, code: str) -> LoginEvent: ...

    def mailbox_password(self, username: str, password: str) -> LoginEvent: ...

    def abort(self, username: str) -> None: ...

    def users(self) -> list[UserInfo]: ...

    def user(self, user_id: str) -> UserInfo: ...

    def set_split(self, user_id: str, active: bool) -> None: ...

    def remove(self, user_id: str) -> None: ...

    def export_certificate(self, directory: str) -> None:
        """Write Bridge's TLS certificate (`cert.pem`) into `directory`."""

    def close(self) -> None: ...


class BridgeError(Exception):
    """Bridge could not be asked, or refused the call."""


class Stopped(Exception):
    """The keeper has ended Bridge; whatever was in progress is abandoned."""
