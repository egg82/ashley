"""Wire models for a bench's kind of work and the household's skills (`api.skills`)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..skills.skills import Refusal, Skill, Status, Version
from ..text import NoNul


class WorkKind(BaseModel):
    """A kind of work a bench can have, from the skills config: its `name` (what `BenchSummary.work` holds) and the
    `label` a screen shows."""

    name: str
    label: str


class WorkRequest(BaseModel):
    """A bench's kind of work: the `work` slug of one of `WorkshopKinds.work_kinds`, or null for none. A slug the
    household has no kind for starts one, and then needs `label` (what to call it); a slug is lowercase letters, digits
    and hyphens."""

    model_config = ConfigDict(extra="forbid")

    work: NoNul | None = Field(max_length=40)
    label: NoNul | None = Field(default=None, max_length=60)


class SkillVersion(BaseModel):
    """One entry of a skill's changelog. `status` `live`: it loaded when it was current; `proposed`: her edit of a
    pinned skill, waiting for approval; `declined`: a person declined it. `author` is who made it; `restored_from`
    is the version a rollback copied (0 is the seed); `base_version` is the live version it was made against."""

    skill_version: int
    status: Status
    what: str
    why: str
    author: Literal["person", "ashley"]
    restored_from: int | None
    base_version: int
    at: datetime


class SkillDetail(BaseModel):
    """A kind's skill as it loads now: `skill_version` is the live version (0: the seed, with `seeded_from` naming the
    skill it was adapted from), `edits` how many live versions the household made, `pinned` whether her edits wait
    for a person's approval. `waiting` is her newest waiting edit, with its full `waiting_body`. `changelog` is the
    latest entries, newest first."""

    kind: str
    label: str
    skill_version: int
    body: str
    edits: int
    pinned: bool
    seeded_from: str | None
    waiting: SkillVersion | None
    waiting_body: str | None
    changelog: list[SkillVersion]


class SkillRefusal(BaseModel):
    """A change to a skill was refused and nothing changed. `reason` is a stable word a client branches on: `stale`
    (the skill moved on: read it again), `unchanged`, `no_such_version`, `not_proposed`, `bad_note`, `bad_body`,
    `unknown_kind`."""

    code: Literal["refused"]
    reason: Refusal
    detail: str


class PinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pinned: bool


class RollbackRequest(BaseModel):
    """Roll the skill back to the text of live version `to_version` (0: the seed), as a new version."""

    model_config = ConfigDict(extra="forbid")

    to_version: int = Field(ge=0)


def version_of(v: Version) -> SkillVersion:
    return SkillVersion(skill_version=v.version, status=v.status, what=v.what, why=v.why,
                        author="ashley" if v.person_id is None else "person", restored_from=v.restored_from,
                        base_version=v.base_version, at=v.at)


def detail_of(skill: Skill, label: str, changelog: tuple[Version, ...]) -> SkillDetail:
    return SkillDetail(kind=skill.kind, label=label, skill_version=skill.version, body=skill.body, edits=skill.edits,
                       pinned=skill.pinned, seeded_from=skill.seeded_from,
                       waiting=None if skill.proposal is None else version_of(skill.proposal),
                       waiting_body=None if skill.proposal is None else skill.proposal.body,
                       changelog=[version_of(v) for v in changelog])
