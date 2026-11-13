"""The Focus service (`ashley.services`): when a person last typed into a Claude Code session of theirs, the one
structured sign of their focus the app can read (`decisions.md`, "Whether she speaks unprompted is decided in code").
The first implementation asks the person's herdr bridge (`herdr_focus.HerdrFocus`). Being on a call is not read yet.

When someone typed is people's data: nothing here logs it."""

from abc import abstractmethod
from datetime import datetime

from ..services import Service


class FocusUnavailable(Exception):
    """Their source could not be read (a connection store down, a bridge unreachable). Transient."""


class Focus(Service):
    @classmethod
    def null(cls) -> "Focus":
        return NullFocus()

    @abstractmethod
    async def typed_at(self, household_id: int, person_id: int) -> datetime | None:
        """When the person last typed into one of their Claude Code sessions; None when they have connected no bridge
        or it records no typing. Raises FocusUnavailable when it cannot be read."""


class NullFocus(Focus):
    """What an unwired process sees: focus cannot be read, so nothing that waits on it goes ahead."""

    async def typed_at(self, household_id: int, person_id: int) -> datetime | None:
        raise FocusUnavailable("no focus source is wired")
