"""The Initiative service (`ashley.services`): whether what she would say unprompted goes out (`decisions.md`,
"Whether she speaks unprompted is decided in code"). The turn loop asks it of every reply on a turn nobody asked for
(`ashley.channels.model.Inbound.unprompted`), and never of a reply to a person.

The decision keys on measured facts and structured fields of her reply, never on its words. A turn a wake from the
house starts carries the facts of its moment (`moment.Moment`), gathered before the turn, and is planned from them
before she is asked (`planned`): the plan's outcome reaches her as that call's instruction. Every other unprompted turn
carries none, and goes out on her `Reply.says` alone."""

from abc import abstractmethod

from ..inference.reply import Reply
from ..services import Service
from .moment import Moment, Plan
from .score import planned
from .weights import Weights


class Initiative(Service):
    @classmethod
    def null(cls) -> "Initiative":
        return NullInitiative()

    @abstractmethod
    def planned(self, moment: Moment) -> Plan:
        """What `moment` comes to before her turn runs. Pure: the same moment always gets the same plan."""

    @abstractmethod
    def speaks(self, reply: Reply, moment: Moment | None) -> bool:
        """Whether `reply`, said on her own initiative at `moment` (None for a turn that carries no facts), goes out.
        Pure: the same reply and moment always get the same answer."""


class NullInitiative(Initiative):
    """What an unwired process sees: she never speaks unprompted."""

    def planned(self, moment: Moment) -> Plan:
        return Plan(0.0, None, "silent")

    def speaks(self, reply: Reply, moment: Moment | None) -> bool:
        return False


class Scored(Initiative):
    """The moment's score and seeded roll (`score.planned`) under `weights`: a reply goes out when she says it is worth
    saying and, at a moment, the plan is not silent."""

    def __init__(self, weights: Weights) -> None:
        self._weights = weights

    def planned(self, moment: Moment) -> Plan:
        return planned(moment, self._weights)

    def speaks(self, reply: Reply, moment: Moment | None) -> bool:
        return reply.says != "none" and (moment is None or self.planned(moment).outcome != "silent")
