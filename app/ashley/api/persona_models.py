"""The wire models of the persona page (`ashley.api.persona`): the household's own text for the persona's overridable
sections, with each section's changelog. The household is always the session's; any person of it may read and change
it. Every answer is `PersonaDetail` as it stands after the call:

- `GET /api/persona`: 200; 401 `unauthorized`; 503 `unavailable`.
- `PUT /api/persona/{section}` with `PersonaEditRequest`: 200; 401; 403 `forbidden` (another site); 409
  `PersonaRefusalBody`; 422 FastAPI's validation error for a request outside the schema (a body, or a `section`
  that is not a slug of at most 40 characters); 503.
- `POST /api/persona/{section}/revert` with `PersonaRevertRequest`: as `PUT`.

A `section` that is not an overridable one (a locked section, or none at all) is 409 `locked`. A change reaches her
from her next reply."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..skills.persona import PersonaRefusal
from ..text import NoNul


class PersonaChange(BaseModel):
    """One entry of a section's changelog. `body` is the household's text it made, null for "back to the shipped
    text". `what` names the kind of change; `why` is the person's note; `restored_from` is the version a revert copied
    (0: the shipped text), else null; `person_id` who made it."""

    persona_version: int
    body: str | None
    what: str
    why: str
    base_version: int
    restored_from: int | None
    person_id: int
    at: datetime


class PersonaSection(BaseModel):
    """One section of her persona a household may override. `shipped` is the text that ships now. `override` is the
    household's text in force, null when she uses `shipped`. `persona_version` is the section's newest version (0:
    never changed), the `base_version` a change is made against. `history` is the latest entries of its changelog,
    newest first. `section` is the id a change names."""

    section: str
    label: str
    shipped: str
    override: str | None
    persona_version: int
    history: list[PersonaChange]


class PersonaDetail(BaseModel):
    """Every overridable section in the shipped persona's order. The sections not listed (her reply's fields and
    their rules, and the rules that hold whatever anyone asks) are locked and no route changes them. `orphaned` names
    sections the household changed that this release no longer lets it override (renamed, removed or locked): their
    text is kept but not used. `body_limit` and `note_limit` are the longest `body` and `why`."""

    sections: list[PersonaSection]
    orphaned: list[str]
    body_limit: int
    note_limit: int


class PersonaEditRequest(BaseModel):
    """The household's whole new text for the section, made from `base_version`, with a line of why."""

    model_config = ConfigDict(extra="forbid")

    body: NoNul = Field(min_length=1)
    why: NoNul = Field(min_length=1)
    base_version: int = Field(ge=0)


class PersonaRevertRequest(BaseModel):
    """Bring back the text of version `to_version` as a new version; 0 goes back to the shipped text."""

    model_config = ConfigDict(extra="forbid")

    to_version: int = Field(ge=0)
    why: NoNul = Field(min_length=1)
    base_version: int = Field(ge=0)


class PersonaRefusalBody(BaseModel):
    """A change was refused and nothing changed. `reason` is a stable word a client branches on: `stale` (the section
    moved on: read it again), `unchanged`, `no_such_version`, `bad_body`, `bad_note`, `locked` (not a section a
    household may override)."""

    code: Literal["refused"]
    reason: PersonaRefusal
    detail: str
