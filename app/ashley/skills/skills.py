"""The Skills service (`ashley.services`): the method documents she works from, per household and kind of work, and
the changelog of how they changed. Callers import only this module and `config`; the Postgres implementation lives
beside it.

A skill's text is the household's latest live version, or the seed that ships for the kind (`seeds`) until the
household first edits it. Versions are append-only and numbered from 1 per household and kind: a rollback is a new
version carrying an older body (`restored_from`), so the changelog never loses what happened. A kind a person pinned
takes her edits as proposals (`status` `proposed`) that load only once a person approves them. Bodies and notes are
the household's data: stored, never logged."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..services import Service

Status = Literal["live", "proposed", "declined"]
Refusal = Literal["unknown_kind", "bad_kind", "bad_body", "bad_note", "unchanged", "stale", "no_such_version", "not_proposed"]


class SkillsError(Exception):
    """Base of what the service raises on purpose."""


class SkillsUnavailable(SkillsError):
    """No writable database could be reached, or none is wired. Nothing was written. Transient."""


class SkillRefused(SkillsError):
    """The change was not made. `reason`: `unknown_kind` (not a kind of this household's: `add_kind` starts one);
    `bad_kind` (a name that is not a slug of the config's shape, or a label that is blank, too long or holds a NUL); `bad_body` (empty, over the limit, or a
    NUL); `bad_note` (a `what` or `why` empty, over the limit, or a NUL); `unchanged` (the body is the current
    one); `stale` (the version it was based on is not the current one); `no_such_version` (a rollback target that
    was never live); `not_proposed` (a decision on a version that is not waiting)."""

    def __init__(self, reason: Refusal) -> None:
        super().__init__(reason)
        self.reason: Refusal = reason


@dataclass(frozen=True)
class Kind:
    """A kind of work: its `kind` slug, which a bench's `work` holds, and the `label` a screen shows."""

    kind: str
    label: str


@dataclass(frozen=True)
class Version:
    """One entry of the changelog, with the `body` it made. `person_id` is None for her. `bench_id` is the bench she or the person was on, None
    for a change outside any. `base_version` is the live version the change was made against; `restored_from` is the
    version whose body a rollback copied."""

    version: int
    status: Status
    body: str
    what: str
    why: str
    base_version: int
    restored_from: int | None
    bench_id: int | None
    person_id: int | None
    at: datetime


@dataclass(frozen=True)
class Skill:
    """A kind's skill as it loads now. `version` is the live version, 0 for the seed; `edits` is how many live versions
    the household has made (a rollback counts); `seeded_from` names the seed's source while `version` is 0 and is None
    after. `proposal` is the newest waiting proposal."""

    kind: str
    version: int
    body: str
    edits: int
    pinned: bool
    seeded_from: str | None
    changed_at: datetime | None
    proposal: Version | None


@dataclass(frozen=True)
class Edited:
    """What `edit` or `rollback` made: the new `version` and whether it is `live` or waits as `proposed`."""

    version: int
    status: Status


class Skills(Service):
    @classmethod
    def null(cls) -> "Skills":
        return NullSkills()

    @abstractmethod
    async def kinds(self, household_id: int) -> tuple[Kind, ...]:
        """The household's kinds of work: those it started, and those a seed names, by slug; a household's own label
        wins over a seed's. Raises SkillsUnavailable. Reads only."""

    @abstractmethod
    async def add_kind(self, household_id: int, kind: str, label: str) -> Kind:
        """Start the household's kind `kind` named `label`, or return it as it is when it exists (a label is never
        changed here). Raises SkillRefused (`bad_kind`); SkillsUnavailable. Logs `skills.kind_added` when it starts."""

    @abstractmethod
    async def current(self, household_id: int, kind: str) -> Skill | None:
        """The household's skill for `kind`: its latest live version, else the seed, else (a kind with only her waiting
        proposal so far) version 0 with an empty body and the proposal, else None. Raises
        SkillRefused (`unknown_kind`); SkillsUnavailable. Reads only."""

    @abstractmethod
    async def edit(self, household_id: int, kind: str, body: str, what: str, why: str, base_version: int,
                   bench_id: int | None, person_id: int | None) -> Edited:
        """Make `body` the skill of `kind`, changed by the person `person_id` (None: her), on bench `bench_id`, as
        the next version. `base_version` is the live version it was written from (0 for the seed or no skill); another
        than the current one is refused `stale`. It is live at once, unless the kind is pinned and the change is hers:
        then it waits as `proposed`. Raises SkillRefused (`unknown_kind`, `bad_body`, `bad_note`, `unchanged`,
        `stale`); SkillsUnavailable. Logs `skills.edited` with ids, the kind, the version, status and lengths."""

    @abstractmethod
    async def rollback(self, household_id: int, kind: str, to_version: int, why: str, bench_id: int | None,
                       person_id: int | None) -> Edited:
        """Make the body of live version `to_version` (0: the seed) the next version, with `edit`'s liveness rule and
        `what` "Rolled back to version N" ("Rolled back to the seed" for 0). Raises SkillRefused (`unknown_kind`, `bad_note`, `no_such_version`,
        `unchanged`); SkillsUnavailable. Logs `skills.edited`."""

    @abstractmethod
    async def changelog(self, household_id: int, kind: str) -> tuple[Version, ...]:
        """The newest `changelog_read` versions of `kind`, newest first, proposed and declined ones included. Raises
        SkillRefused (`unknown_kind`); SkillsUnavailable. Reads only."""

    @abstractmethod
    async def pin(self, household_id: int, kind: str, pinned: bool) -> None:
        """Pin `kind` so her edits of it wait for approval, or unpin it. Changes nothing waiting. Raises SkillRefused
        (`unknown_kind`); SkillsUnavailable. Logs `skills.pinned`."""

    @abstractmethod
    async def decide(self, household_id: int, kind: str, version: int, approve: bool) -> Edited:
        """Approve (the version becomes live) or decline a proposed `version`. An approval is refused `stale` when the
        live version has moved past the one it was proposed against; her next proposal starts from the new one. Raises
        SkillRefused (`unknown_kind`, `not_proposed`, `stale`); SkillsUnavailable. Logs `skills.decided`."""


class NullSkills(Skills):
    """What an unwired process sees: every call raises SkillsUnavailable."""

    async def kinds(self, household_id: int) -> tuple[Kind, ...]:
        raise SkillsUnavailable("no skills are wired")

    async def add_kind(self, household_id: int, kind: str, label: str) -> Kind:
        raise SkillsUnavailable("no skills are wired")

    async def current(self, household_id: int, kind: str) -> Skill | None:
        raise SkillsUnavailable("no skills are wired")

    async def edit(self, household_id: int, kind: str, body: str, what: str, why: str, base_version: int,
                   bench_id: int | None, person_id: int | None) -> Edited:
        raise SkillsUnavailable("no skills are wired")

    async def rollback(self, household_id: int, kind: str, to_version: int, why: str, bench_id: int | None,
                       person_id: int | None) -> Edited:
        raise SkillsUnavailable("no skills are wired")

    async def changelog(self, household_id: int, kind: str) -> tuple[Version, ...]:
        raise SkillsUnavailable("no skills are wired")

    async def pin(self, household_id: int, kind: str, pinned: bool) -> None:
        raise SkillsUnavailable("no skills are wired")

    async def decide(self, household_id: int, kind: str, version: int, approve: bool) -> Edited:
        raise SkillsUnavailable("no skills are wired")
