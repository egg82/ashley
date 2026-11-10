"""The bridge's JSON bodies (`bridge/herdr/README.md`, "The API"). Fields the bridge adds later are ignored; a body of
any other shape is `unexpected`."""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .model import BridgeFailed, OutFile, Screen, Session, SessionList, Status, Whoami


class WhoamiBody(BaseModel):
    bridge_version: str
    herdr_version: str | None
    person: str | None
    capabilities: list[str] = []


class SessionBody(BaseModel):
    id: str
    label: str
    dir: str
    status: Status
    seq: int
    last_typed_at: str | None


class SessionsBody(BaseModel):
    sessions: list[SessionBody]
    last_typed_at: str | None
    roots: list[str] | None = None


class ScreenBody(BaseModel):
    text: str
    truncated: bool
    revision: int


class SubmittedBody(BaseModel):
    submitted: bool


class ClosedBody(BaseModel):
    closed: bool


class UploadedBody(BaseModel):
    bytes: int


class OutFileBody(BaseModel):
    name: str
    bytes: int


class OutputsBody(BaseModel):
    files: list[OutFileBody]


B = TypeVar("B", bound=BaseModel)


def body_as(kind: type[B], raw: bytes) -> B:
    """`raw` as a `kind`. Raises BridgeFailed (`unexpected`)."""
    try:
        return kind.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as e:
        raise BridgeFailed("unexpected") from e


def session(b: SessionBody) -> Session:
    return Session(id=b.id, label=b.label, dir=b.dir, status=b.status, seq=b.seq, last_typed_at=b.last_typed_at)


def whoami(raw: bytes) -> Whoami:
    b = body_as(WhoamiBody, raw)
    return Whoami(b.bridge_version, b.herdr_version, b.person, tuple(b.capabilities))


def sessions(raw: bytes) -> SessionList:
    b = body_as(SessionsBody, raw)
    return SessionList(tuple(session(s) for s in b.sessions), b.last_typed_at,
                       None if b.roots is None else tuple(b.roots))


def screen(raw: bytes) -> Screen:
    b = body_as(ScreenBody, raw)
    return Screen(b.text, b.truncated, b.revision)


def outputs(raw: bytes) -> tuple[OutFile, ...]:
    return tuple(OutFile(f.name, f.bytes) for f in body_as(OutputsBody, raw).files)
