"""The Initiative service (`ashley.services`): whether what she would say unprompted goes out (`decisions.md`,
"Whether she speaks unprompted is decided in code"). The turn loop asks it of every reply on a turn nobody asked for
(`ashley.channels.model.Inbound.unprompted`, a wake from the house today), and never of a reply to a person.

The decision keys on structured fields of her reply, never on its words. The first policy, `WorthSaying`, is her
`Reply.worth_saying` alone; the scored policy of open-work's arrival greeting (time away, hour, who is home, when she
last spoke, weights as data) replaces it behind this interface."""

from abc import abstractmethod

from ..inference.reply import Reply
from ..services import Service


class Initiative(Service):
    @classmethod
    def null(cls) -> "Initiative":
        return NullInitiative()

    @abstractmethod
    def speaks(self, reply: Reply) -> bool:
        """Whether `reply`, said on her own initiative, goes out. Pure: the same reply always gets the same answer."""


class NullInitiative(Initiative):
    """What an unwired process sees: she never speaks unprompted."""

    def speaks(self, reply: Reply) -> bool:
        return False


class WorthSaying(Initiative):
    """She speaks when her reply says it is worth saying."""

    def speaks(self, reply: Reply) -> bool:
        return reply.worth_saying
