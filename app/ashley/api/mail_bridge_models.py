"""The wire models of Proton Bridge's routes: the keeper's calls (`ashley.api.mail_bridge`) and the room's login and
account list (`ashley.api.mail_bridge_login`). No model carries a typed password or code outward; a vault travels as
base64 text between the keeper and the app and is never returned to a person."""

import base64
import binascii
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from ..text import NoNul
from .connection_models import Label

Blob = Annotated[str, StringConstraints(max_length=4_000_000)]


def _base64(text: str) -> str:
    try:
        base64.b64decode(text, validate=True)
    except binascii.Error as e:
        raise ValueError("not base64") from e
    return text


Base64 = Annotated[Blob, AfterValidator(_base64)]


class KeeperVault(BaseModel):
    """What the keeper starts Bridge from: the `generation` it must hold in its next write-back, and the vault and
    keychain as base64, both null before the first write-back."""

    generation: int
    vault: Blob | None
    keychain: Blob | None


class VaultWrite(BaseModel):
    """A write-back: the vault and keychain (base64) the keeper read at `generation`, from the pod of `epoch`."""

    epoch: int
    generation: int
    vault: Base64
    keychain: Base64


class Written(BaseModel):
    """The generation the record holds after a write-back; the keeper's next carries it."""

    generation: int


class Heartbeat(BaseModel):
    """The pod of `epoch` is alive, with the SHA-256 (hex) of the TLS certificate Bridge serves IMAP and SMTP under."""

    epoch: int
    certificate_sha256: Annotated[str, StringConstraints(pattern="^[0-9a-f]{64}$")] | None = None


class KeeperEvent(BaseModel):
    """What Bridge reported about one Proton account (`user_id`), in `epoch`: its `state`, or a `sync` event with its
    `progress` (0 to 1) for a `progress` event. Exactly one of `state` and `sync`."""

    epoch: int
    user_id: Annotated[NoNul, StringConstraints(min_length=1, max_length=200)]
    state: Literal["connected", "signed_out", "locked"] | None = None
    sync: Literal["started", "progress", "finished"] | None = None
    progress: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        if (self.state is None) == (self.sync is None):
            raise ValueError("exactly one of state and sync")
        if (self.sync == "progress") != (self.progress is not None):
            raise ValueError("progress goes with a progress event and only with it")
        return self


class Applied(BaseModel):
    """Whether the event changed an account: false for a Proton user no connection holds."""

    applied: bool


class ProtonLoginStart(BaseModel):
    """First step of a login from the room: the connection's `label` (as any connection's) and the Proton username and
    password, which go to Bridge once and are kept nowhere."""

    label: Label
    username: Annotated[NoNul, StringConstraints(min_length=1, max_length=320)]
    password: Annotated[NoNul, StringConstraints(min_length=1, max_length=1024)] = Field(repr=False)


class ProtonSecondFactor(BaseModel):
    """The two-factor `code`, with the `label` the login began under."""

    label: Label
    code: Annotated[NoNul, StringConstraints(min_length=1, max_length=32)] = Field(repr=False)


class ProtonMailboxPassword(BaseModel):
    """The mailbox password of an account that has two, with the `label` the login began under."""

    label: Label
    password: Annotated[NoNul, StringConstraints(min_length=1, max_length=1024)] = Field(repr=False)


class ProtonVerifiedLogin(BaseModel):
    """The password again, with the `label` the login began under, once the person has passed Proton's human check."""

    label: Label
    password: Annotated[NoNul, StringConstraints(min_length=1, max_length=1024)] = Field(repr=False)


class ProtonLoginStep(BaseModel):
    """Where a login stands. `step` is what the person is asked for next (`two_factor`, `mailbox_password`),
    `human_verification` (Proton wants to check it is a person: they open `verification_url`, an https page on proton.me,
    in their own browser, then send the password again as verified) or `connected`, when `connection_id` is the stored
    connection and `addresses` the mail addresses it reaches."""

    step: Literal["two_factor", "mailbox_password", "human_verification", "connected"]
    connection_id: int | None = None
    addresses: list[str] = []
    verification_url: str | None = None


class ProtonLoginRefused(BaseModel):
    """Why Bridge or the app refused a step: `credentials` (username or password), `code` (the two-factor code),
    `mailbox_password`, `paid_plan` (Bridge needs a paid Proton plan), `connection` (Bridge could not reach Proton),
    `aborted` (Bridge ended the login), `verification` (the human check did not pass), `security_key` (the account's
    two-factor is a hardware key only), `label_taken`, `too_many`, or `other`. The login is over; the person starts
    again."""

    reason: Literal["credentials", "code", "mailbox_password", "paid_plan", "connection", "aborted", "verification",
                    "security_key", "label_taken", "too_many", "other"]
    detail: str


class ProtonAccount(BaseModel):
    """A Proton account of a connection the signed-in person can see. `state` is Bridge's; `syncing` is true while Bridge
    serves its mailbox empty, with the last `sync_progress` it reported (0 to 1, null before any)."""

    connection_id: int
    state: Literal["connected", "signed_out", "locked"]
    addresses: list[str]
    syncing: bool
    sync_progress: float | None


class ProtonAccounts(BaseModel):
    proton_accounts: list[ProtonAccount]
