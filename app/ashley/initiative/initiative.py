"""The Initiative service (`ashley.services`): whether what she would say unprompted goes out (`decisions.md`,
"Whether she speaks unprompted is decided in code"). The turn loop asks it of every reply on a turn nobody asked for
(`ashley.channels.model.Inbound.unprompted`), and never of a reply to a person.

The decision keys on measured facts and structured fields of her reply, never on its words. A turn a wake from the
house starts carries the facts of its moment (`moment.Moment`), gathered before the turn, and is planned from them
before she is asked (`planned`): the plan's outcome reaches her as that call's instruction. Every other unprompted turn
carries none, and goes out on her `Reply.says` alone, except a remark nobody asked for (`remark.Chance`): code allows
one before she is asked (`remark`), and lets it out only when she says it is worth saying and it is no line she
already sent."""

from abc import abstractmethod

from ..inference.reply import Reply
from ..services import Service
from .moment import Moment, Plan
from .remark import RATES, Chance, Rates, Verdict, repeats, rolls, verdict
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

    @abstractmethod
    def rolls(self, seed: str) -> bool:
        """Whether a message with the stable id `seed` rolls a remark, before any fact about it is read. Pure."""

    @abstractmethod
    def remark(self, chance: Chance) -> Verdict:
        """Whether she may make a remark at `chance`, before her turn runs. Pure."""

    @abstractmethod
    def remark_speaks(self, reply: Reply, line: str, chance: Chance) -> bool:
        """Whether `reply`, delivered as `line`, goes out as a remark at `chance`. Pure."""


class NullInitiative(Initiative):
    """What an unwired process sees: she never speaks unprompted."""

    def planned(self, moment: Moment) -> Plan:
        return Plan(0.0, None, "silent")

    def speaks(self, reply: Reply, moment: Moment | None) -> bool:
        return False

    def rolls(self, seed: str) -> bool:
        return False

    def remark(self, chance: Chance) -> Verdict:
        return "rolled_out"

    def remark_speaks(self, reply: Reply, line: str, chance: Chance) -> bool:
        return False


class Scored(Initiative):
    """The moment's score and seeded roll (`score.planned`) under `weights`: a reply goes out when she says it is worth
    saying and, at a moment, the plan is not silent. A remark is allowed by `rates` (`remark.verdict`) and goes out
    when she says it is worth saying and it repeats no line she sent."""

    def __init__(self, weights: Weights, rates: Rates = RATES) -> None:
        self._weights = weights
        self._rates = rates

    def planned(self, moment: Moment) -> Plan:
        return planned(moment, self._weights)

    def speaks(self, reply: Reply, moment: Moment | None) -> bool:
        return reply.says != "none" and (moment is None or self.planned(moment).outcome != "silent")

    def rolls(self, seed: str) -> bool:
        return rolls(seed, self._rates)

    def remark(self, chance: Chance) -> Verdict:
        return verdict(chance, self._rates, self._weights)

    def remark_speaks(self, reply: Reply, line: str, chance: Chance) -> bool:
        return reply.says != "none" and self.remark(chance) == "allowed" and not repeats(line, chance)
