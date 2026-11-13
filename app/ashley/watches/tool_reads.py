"""The ToolReads service (`ashley.services`): a read one of her tools makes for a watch, with no model in it (`decisions.md`,
"Watches wake her when what a read returns changes, until a condition or a time"). Only a tool whose spec says it reads
(`ToolSpec.reads`) is ever run, so a watch can never change anything; the implementation lives beside the tools, which
this package does not import."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from ..services import Service
from .model import ReadFailed


@dataclass(frozen=True)
class Text:
    """What the tool answered, as the text the model would read."""

    text: str


ToolRead = Text | ReadFailed


class ToolReads(Service):
    @classmethod
    def null(cls) -> "ToolReads":
        return NullToolReads()

    @abstractmethod
    async def available(self, household_id: int, person_id: int) -> bool:
        """Whether this person can have a tool read for a watch."""

    @abstractmethod
    async def read(self, household_id: int, person_id: int, tool: str, arguments: Mapping[str, object]) -> ToolRead:
        """Run `tool` with `arguments` as the person's own turn would, and only when the tool reads. `ReadFailed`
        `refused` for a tool the person has no read of (unknown, or one that changes things), `bad_result` for an
        answer that is an error, `unreachable` when the tools cannot be listed. Never raises for what a tool did."""


class NullToolReads(ToolReads):
    """What an unwired process sees: nothing can be read for a watch."""

    async def available(self, household_id: int, person_id: int) -> bool:
        return False

    async def read(self, household_id: int, person_id: int, tool: str, arguments: Mapping[str, object]) -> ToolRead:
        return ReadFailed("unreachable")
