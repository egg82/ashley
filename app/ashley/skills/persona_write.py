"""The PersonaWriter service (`ashley.services`): a signed-in person changes or reverts their household's text for one
overridable persona section. Kept apart from `PersonaOverrides`, which channels read, so nothing that reads the
overrides can write them: only the persona route and the wiring import this module (a boundary test holds that).

The writer is built with the shipped `allowed` sections (`ashley.persona.sections.catalogue`, id to shipped body); an
id outside them is refused `locked`, whatever the route. Versioning is `ashley.skills.persona`'s. A change locks its
household's section for the transaction, so versions are numbered one after the other on any pod of either site.
Logs `persona.changed` with ids, the section, the version, the kind of change and a length, never the text."""

from abc import abstractmethod
from typing import Literal

from ..services import Service
from .persona import PersonaUnavailable

PersonaRefusal = Literal["locked", "bad_body", "bad_note", "unchanged", "stale", "no_such_version"]


class PersonaRefused(Exception):
    """The change was not made. `reason`: `locked` (not an `allowed` section of the shipped persona); `bad_body`
    (blank, over the skills' `max_body_chars`, or a NUL); `bad_note` (a `why` blank, over `max_note_chars`, or a NUL);
    `unchanged` (it would leave the section's text as it is now: the same body, or a revert to what is already in
    force); `stale` (`base_version` is not the section's newest version); `no_such_version` (a revert target that is
    not a version of the section with a body; 0, the shipped text, always exists)."""

    def __init__(self, reason: PersonaRefusal) -> None:
        super().__init__(reason)
        self.reason: PersonaRefusal = reason


class PersonaWriter(Service):
    @classmethod
    def null(cls) -> "PersonaWriter":
        return NullPersonaWriter()

    @abstractmethod
    async def edit(self, household_id: int, section: str, body: str, why: str, base_version: int,
                   person_id: int) -> int:
        """Make `body` the household's text for `section`, by the person `person_id`, as the next version, and answer
        its number. `base_version` is the newest version it was written from (0 for none). Raises PersonaRefused
        (`locked`, `bad_body`, `bad_note`, `unchanged`, `stale`); PersonaUnavailable."""

    @abstractmethod
    async def revert(self, household_id: int, section: str, to_version: int, why: str, base_version: int,
                     person_id: int) -> int:
        """Make version `to_version`'s body the next version (`restored_from` set), or with 0 go back to the shipped
        text (a version with body None), and answer its number. Raises PersonaRefused (`locked`, `bad_note`,
        `no_such_version`, `unchanged`, `stale`); PersonaUnavailable."""


class NullPersonaWriter(PersonaWriter):
    """What an unwired process sees: every call raises PersonaUnavailable."""

    async def edit(self, household_id: int, section: str, body: str, why: str, base_version: int,
                   person_id: int) -> int:
        raise PersonaUnavailable("PersonaWriter is not wired")

    async def revert(self, household_id: int, section: str, to_version: int, why: str, base_version: int,
                     person_id: int) -> int:
        raise PersonaUnavailable("PersonaWriter is not wired")
