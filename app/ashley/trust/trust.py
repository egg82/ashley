"""The Trust service (`ashley.services`): what a person stored about the kinds of action she may just do
(`trust.kinds`). Reading is open to whatever behaves by it; writing is `trust_write`, which only the person's route and
the wiring import (`tests/test_settings_boundary.py`), so nothing she does can loosen it."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ..services import Service
from .kinds import Value


class TrustUnavailable(Exception):
    """What a person set could not be read or written. A reader that cannot read it treats every kind as offer first."""


@dataclass(frozen=True)
class StoredTrust:
    """A person's stored choices: `version` counts their writes (0 for one never set), `values` the kinds whose value
    differs from what it is unset, `updated_at` the last write (None for none)."""

    version: int = 0
    values: Mapping[str, Value] = field(default_factory=dict[str, Value])
    updated_at: datetime | None = None


class Trust(Service):
    @classmethod
    def null(cls) -> "Trust":
        return NullTrust()

    @abstractmethod
    async def stored(self, household_id: int, person_id: int) -> StoredTrust:
        """That person's choices, version 0 and none for a person who set none. Raises TrustUnavailable."""


class NullTrust(Trust):
    """What an unwired process sees: nothing can be read, which every reader takes as offer first."""

    async def stored(self, household_id: int, person_id: int) -> StoredTrust:
        raise TrustUnavailable("Trust is not wired")
