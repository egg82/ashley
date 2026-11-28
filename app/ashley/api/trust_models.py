"""The wire models of what a person lets her just do (`ashley.api.trust`). Each kind is served with its label, so the
page draws its rows from data and holds no copy of the list."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TrustRow(BaseModel):
    """One kind of action: `value` is what she does in a turn nobody asked for, `act` (just does it) or `offer` (offers
    it first). `locked` is why the code always offers it first, whatever is set (`asks`: its tools always wait for a
    person's OK; `irreversible`: it cannot be undone), null when the person decides."""

    kind: str
    label: str
    value: Literal["act", "offer"]
    locked: Literal["asks", "irreversible"] | None


class TrustSettings(BaseModel):
    """The signed-in person's rows, in the order the page shows them. `revision` counts their writes, 0 for a person
    who set none, and is what the next write must carry; `updated_at` is their last write, null for none."""

    revision: int
    rows: list[TrustRow]
    updated_at: datetime | None


class TrustChoice(BaseModel):
    """What the person chose for one kind."""

    kind: str = Field(max_length=64)
    value: Literal["act", "offer"]


class TrustRequest(BaseModel):
    """The whole of the person's choices, replacing what is stored (a kind left out is `act`, or `offer` where it is
    locked), and the `revision` they were read at."""

    revision: int = Field(ge=0)
    picks: list[TrustChoice] = Field(max_length=32)


class TrustRefused(BaseModel):
    """Why the choices were not stored; nothing was. `reason`: `unknown_kind`, there is no such kind; `locked`, `act`
    for a kind the code always offers first. `kind` is the one it concerns."""

    kind: str
    reason: Literal["unknown_kind", "locked"]
    detail: str
