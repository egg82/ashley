"""The TrustWriter service (`ashley.services`): a person's write of what she may just do for them. Only the person's
route (`ashley.api.trust`) and the wiring import this module; a boundary test holds that set to exactly those, so no
tool, channel or model call can make her less careful."""

from abc import abstractmethod
from collections.abc import Mapping

from ..services import Service
from .kinds import Value
from .trust import StoredTrust, TrustUnavailable

RETAIN_DAYS = 400
"""How long the change log is kept; each write deletes what is older."""


class VersionConflict(Exception):
    """The person's choices changed since the version the writer read."""


class TrustWriter(Service):
    @classmethod
    def null(cls) -> "TrustWriter":
        return NullTrustWriter()

    @abstractmethod
    async def put(self, household_id: int, person_id: int, version: int, chosen: Mapping[str, Value]) -> StoredTrust:
        """Replace the whole of the person's choices with `chosen` (a kind left out is unset), which must be what
        `version` was when read: compare-and-set, in one transaction with a log row per changed kind, the log pruned
        past `RETAIN_DAYS`. Only a kind whose value differs from what it is unset is stored (`Kinds.checked`). Logs
        `trust.changed` with kind names and a count. Raises TrustRefused, VersionConflict, TrustUnavailable."""


class NullTrustWriter(TrustWriter):
    async def put(self, household_id: int, person_id: int, version: int, chosen: Mapping[str, Value]) -> StoredTrust:
        raise TrustUnavailable("TrustWriter is not wired")
