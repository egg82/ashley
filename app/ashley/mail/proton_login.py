"""The ProtonLogin service (`ashley.services`): a Proton account's login to Bridge, relayed step by step from the room to
the keeper in the running pod (`decisions.md`, "Logging in happens once, from the room"). What a person types goes to
Bridge once; nothing here stores or logs it. A login lives in the keeper, one at a time, and is cut off by a failover: the
person starts again."""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..services import Service
from .proton_bridge import BridgeUnavailable


@dataclass(frozen=True)
class Ask:
    """Bridge wants `step` next: `two_factor` (the code) or `mailbox_password` (an account with two passwords)."""

    step: Literal["two_factor", "mailbox_password"]


@dataclass(frozen=True)
class Verify:
    """Proton wants the person to pass its human check at `url`, an https page on a proton.me host that carries a token
    (so it is never logged), in their own browser; then `verified` retries the login with the password again."""

    url: str = field(repr=False)


@dataclass(frozen=True)
class Done:
    """Bridge holds the account as `user_id`, reached at `addresses` (each its own mailbox, split address mode on), with
    `bridge_password` as its IMAP and SMTP password. `epoch` is the keeper's, and `synced` is whether Bridge had already
    finished syncing it in that epoch. The password is left out of `repr`."""

    user_id: str
    addresses: tuple[str, ...]
    bridge_password: str = field(repr=False)
    epoch: int
    synced: bool


@dataclass(frozen=True)
class Refused:
    """Bridge turned the step down; the login is over. `reason`: `credentials`, `code`, `mailbox_password`, `paid_plan`
    (Bridge needs a paid Proton plan), `connection` (Bridge could not reach Proton), `aborted` (Bridge ended the login:
    too many attempts, or it lost the session), `verification` (the human check did not pass), `security_key` (the
    account's two-factor is a hardware key only, which cannot work from the pod), or `other` (a Bridge answer the keeper
    does not know)."""

    reason: Literal["credentials", "code", "mailbox_password", "paid_plan", "connection", "aborted", "verification",
                    "security_key", "other"]


LoginStep = Ask | Verify | Done | Refused


class ProtonLogin(Service):
    @classmethod
    def null(cls) -> "ProtonLogin":
        return NullProtonLogin()

    @abstractmethod
    async def begin(self, username: str, password: str) -> LoginStep:
        """Bridge's `Login`. Raises BridgeUnavailable when no Bridge is running to ask."""

    @abstractmethod
    async def verified(self, password: str) -> LoginStep:
        """Bridge's `Login` again, after a `Verify` step, with the human check's details. Raises BridgeUnavailable."""

    @abstractmethod
    async def second_factor(self, code: str) -> LoginStep:
        """Bridge's `Login2FA`. Raises BridgeUnavailable."""

    @abstractmethod
    async def mailbox_password(self, password: str) -> LoginStep:
        """Bridge's `Login2Passwords`. Raises BridgeUnavailable."""

    @abstractmethod
    async def forget(self, user_id: str) -> None:
        """Remove a user Bridge holds, for a login whose connection could not be stored. Raises BridgeUnavailable."""


class NullProtonLogin(ProtonLogin):
    async def begin(self, username: str, password: str) -> LoginStep:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def verified(self, password: str) -> LoginStep:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def second_factor(self, code: str) -> LoginStep:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def mailbox_password(self, password: str) -> LoginStep:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def forget(self, user_id: str) -> None:
        raise BridgeUnavailable("Proton Bridge is not wired")
