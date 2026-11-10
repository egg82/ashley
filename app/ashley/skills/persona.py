"""The PersonaOverrides service (`ashley.services`): a household's own text for the persona's overridable sections
(`ashley.persona.sections`), versioned in the skills' changelog (table `skill_versions`, family `persona`, the section
id in `kind`). This module only reads; changes go through `ashley.skills.persona_write`, which only the persona route
and the wiring import, so nothing she does on her own can change how she talks or judges.

Versions are append-only and numbered from 1 per household and section, as a skill's are. Each version is a person's
and live at once: there are no proposals. A version's `body` is the household's text for the section, or None for
"the shipped text", which follows whatever ships now rather than a copy of it. A section's override is its newest
version's body; a household with no versions, or whose newest is None, gets the shipped section. A revert is a new
version (`restored_from`), so the changelog never loses what happened.

No cache: prompt assembly reads the heads from the database for every reply, so an override stored on any pod reaches
the next reply's prompt on every pod of both sites. Bodies and notes are the household's data: stored, never logged."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ..services import Service


class PersonaUnavailable(Exception):
    """No database could be reached, or none is wired. Nothing was written. Transient."""


@dataclass(frozen=True)
class PersonaVersion:
    """One entry of a section's changelog. `body` None is "back to the shipped text". `what` says what kind of
    change it was, written by code; `why` is the person's note. `base_version` is the newest version the change was
    made against (0 for none); `restored_from` the version a revert copied (0 for the shipped text), else None.
    `person_id` is who made it: always a person."""

    version: int
    body: str | None
    what: str
    why: str
    base_version: int
    restored_from: int | None
    person_id: int
    at: datetime


def bodies(heads: Mapping[str, PersonaVersion]) -> Mapping[str, str]:
    """The overrides prompt assembly applies: each section's newest body, leaving out those back on the shipped
    text."""
    return {section: head.body for section, head in heads.items() if head.body is not None}


class PersonaOverrides(Service):
    @classmethod
    def null(cls) -> "PersonaOverrides":
        return NullPersonaOverrides()

    @abstractmethod
    async def heads(self, household_id: int) -> Mapping[str, PersonaVersion]:
        """The newest version of every section the household has ever changed, by section id, whether or not the
        shipped persona still has that section or still allows overriding it. Raises PersonaUnavailable. Reads only."""

    @abstractmethod
    async def changelog(self, household_id: int, section: str) -> tuple[PersonaVersion, ...]:
        """The newest `changelog_read` versions of `section` (`skills.json`), newest first; empty when none. Raises
        PersonaUnavailable. Reads only."""


class NullPersonaOverrides(PersonaOverrides):
    """What an unwired process sees: every call raises PersonaUnavailable."""

    async def heads(self, household_id: int) -> Mapping[str, PersonaVersion]:
        raise PersonaUnavailable("no persona overrides are wired")

    async def changelog(self, household_id: int, section: str) -> tuple[PersonaVersion, ...]:
        raise PersonaUnavailable("no persona overrides are wired")
