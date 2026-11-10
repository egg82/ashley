"""The ProtonBridge service (`ashley.services`): the one record of Proton Mail Bridge's keeping. It holds Bridge's
vault and keychain, sealed, and the epoch that fences one Bridge pod at a time (`decisions.md`, "Bridge runs as a leased
singleton whose vault outlives its pod"), and a row per Proton account Bridge holds. The singleton
(`ashley.mail.proton_bridge_job`) reads and raises the epoch; the keeper in the pod, through
`ashley.api.mail_bridge`, fetches the vault, writes it back and reports; the room reads the accounts.

Every write from a pod names its epoch and is refused when that is not the current one: a pod nobody holds any longer
cannot change the record. Unregistered, the Null Object raises BridgeUnavailable, so no Proton kind is offered."""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..services import Service

AccountState = Literal["connected", "signed_out", "locked"]
Sync = Literal["started", "progress", "finished"]
Auth = Literal["ok", "bad_token", "stale_epoch"]


class BridgeUnavailable(Exception):
    """The record could not be read or written: no database, or a database that is read-only (a demotion) or
    unreachable. A keeper that is told this stops Bridge."""


@dataclass(frozen=True)
class Holder:
    """Who holds the record's current epoch. `site` and `pod` are None until a holder raises the epoch and makes its
    pod (a raised epoch with no pod is `pod` None); `alive_age_s` is how long ago, by the database's clock, the epoch's
    pod last showed life: its last heartbeat, or its start before the first (None when no pod has ever started).
    `certificate_sha256` is the fingerprint (hex) of the certificate Bridge serves IMAP and SMTP under, as the keeper last
    reported it; None before any report."""

    epoch: int
    site: str | None
    pod: str | None
    alive_age_s: float | None
    certificate_sha256: str | None = None


@dataclass(frozen=True)
class KeeperAccess:
    """What reaching an epoch's keeper takes, the same two things its pod's Secret carries beside the control port's key:
    the bearer `token` and the control port's `certificate` (PEM), the only one the app accepts for that pod."""

    token: str = field(repr=False)
    certificate: str = field(repr=False)


@dataclass(frozen=True)
class Vault:
    """What a keeper starts Bridge from, unsealed: both None until the first write-back."""

    generation: int
    vault: bytes | None = field(default=None, repr=False)
    keychain: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Account:
    """A Proton account Bridge holds, and the connection it is. `syncing` is true while it is connected and its sync has
    not finished in the current `epoch`: Bridge serves such a mailbox empty. `sync_progress` is the last fraction
    Bridge reported (0 to 1), None before any."""

    id: int
    connection_id: int
    proton_user_id: str
    state: AccountState
    addresses: tuple[str, ...]
    synced_epoch: int
    epoch: int
    sync_progress: float | None

    @property
    def syncing(self) -> bool:
        return self.state == "connected" and self.synced_epoch != self.epoch


class ProtonBridge(Service):
    @classmethod
    def null(cls) -> "ProtonBridge":
        return NullProtonBridge()

    @abstractmethod
    async def holder(self) -> Holder:
        """The current epoch's holder. Raises BridgeUnavailable."""

    @abstractmethod
    async def raise_epoch(self, expected: int, site: str, token_sha256: bytes,
                          access: KeeperAccess | None = None) -> int | None:
        """Make `expected + 1` the epoch, for `site` with the keeper token whose SHA-256 is given, with no pod yet; the
        last heartbeat is kept, so the wait for the older pod's fence can be measured from it. `access` is stored, sealed,
        for `keeper_access`, so the other site reaches the keeper too (none stored when None). None, nothing written,
        when the epoch is no longer `expected`. Any older pod's next heartbeat is refused. Raises BridgeUnavailable."""

    @abstractmethod
    async def keeper_access(self, epoch: int) -> KeeperAccess | None:
        """The token and control-port certificate of `epoch`'s keeper, from the record both sites share; None when the
        epoch is not current or none was stored. Raises BridgeUnavailable."""

    @abstractmethod
    async def pod_started(self, epoch: int, pod: str) -> bool:
        """Record that `epoch`'s pod is `pod`, made now. False when the epoch is no longer current. Raises
        BridgeUnavailable."""

    @abstractmethod
    async def authorize(self, epoch: int, token: str) -> Auth:
        """Whether `token` is the keeper token of `epoch` (`bad_token` when not, whatever the epoch) and `epoch` is the
        current one (`stale_epoch`). Raises BridgeUnavailable."""

    @abstractmethod
    async def heartbeat(self, epoch: int, certificate_sha256: str | None) -> bool:
        """`epoch`'s pod is alive now, with this TLS certificate (kept as it was when None). False, nothing written,
        when the epoch is not current. Raises BridgeUnavailable."""

    @abstractmethod
    async def vault(self, epoch: int) -> Vault | None:
        """The vault and keychain for `epoch`'s pod; None when the epoch is not current. Raises BridgeUnavailable."""

    @abstractmethod
    async def write_back(self, epoch: int, generation: int, vault: bytes, keychain: bytes) -> int | None:
        """Store a vault and keychain the keeper read at `generation`, only where the epoch is current and the row is
        still at that generation; the new generation, or None, nothing written. Raises BridgeUnavailable."""

    @abstractmethod
    async def accounts(self) -> tuple[Account, ...]:
        """Every Proton account Bridge holds. Raises BridgeUnavailable."""

    @abstractmethod
    async def add_account(self, connection_id: int, proton_user_id: str, addresses: tuple[str, ...],
                          synced_epoch: int = 0) -> Account:
        """The account `connection_id` is, connected, its sync finished in `synced_epoch` (0: in none yet); one already
        stored for that Proton user is moved to this connection and clears its connection's login need. Raises
        BridgeUnavailable."""

    @abstractmethod
    async def set_state(self, epoch: int, proton_user_id: str, state: AccountState) -> int | None:
        """The account's state as Bridge reports it, in `epoch`; a signed-out account's connection gets `needs` login
        and a connected one's login need is cleared. The account's row id; None, nothing written, when the epoch is not
        current or no account is that user's. Raises BridgeUnavailable."""

    @abstractmethod
    async def sync(self, epoch: int, proton_user_id: str, event: Sync, progress: float | None = None) -> int | None:
        """A sync event for the account in `epoch`: `finished` sets `synced_epoch` to the epoch, `started` resets it and
        the progress, `progress` stores the progress. The account's row id; None, nothing written, when the epoch is not
        current or no account is that user's. Raises BridgeUnavailable."""


class NullProtonBridge(ProtonBridge):
    async def holder(self) -> Holder:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def raise_epoch(self, expected: int, site: str, token_sha256: bytes,
                          access: KeeperAccess | None = None) -> int | None:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def keeper_access(self, epoch: int) -> KeeperAccess | None:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def pod_started(self, epoch: int, pod: str) -> bool:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def authorize(self, epoch: int, token: str) -> Auth:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def heartbeat(self, epoch: int, certificate_sha256: str | None) -> bool:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def vault(self, epoch: int) -> Vault | None:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def write_back(self, epoch: int, generation: int, vault: bytes, keychain: bytes) -> int | None:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def accounts(self) -> tuple[Account, ...]:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def add_account(self, connection_id: int, proton_user_id: str, addresses: tuple[str, ...],
                          synced_epoch: int = 0) -> Account:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def set_state(self, epoch: int, proton_user_id: str, state: AccountState) -> int | None:
        raise BridgeUnavailable("Proton Bridge is not wired")

    async def sync(self, epoch: int, proton_user_id: str, event: Sync, progress: float | None = None) -> int | None:
        raise BridgeUnavailable("Proton Bridge is not wired")
