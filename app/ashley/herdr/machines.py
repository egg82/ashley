"""A person's machines: each herdr connection they hold is one machine, named by its connection label. Every caller
that reaches the bridge goes through `held` and `choose`, so which machine a call runs on is decided in one place.

The default machine, for a caller that names none and the person holds more than one, is the first made (lowest
connection id): it stays the same when a machine is added, so what predates the second machine keeps its meaning."""

from dataclasses import dataclass, field
from typing import Literal

from .. import services
from ..connections import ports
from ..connections.connections import Connections
from .model import Access

MachineRefusal = Literal["unknown_machine", "machine_needed"]


class MachineRefused(Exception):
    """`unknown_machine`: the label is not one of the person's machines. `machine_needed`: the person holds several
    and the call must say which."""

    def __init__(self, reason: MachineRefusal) -> None:
        super().__init__(reason)
        self.reason: MachineRefusal = reason


@dataclass(frozen=True)
class Machine:
    """One machine's connection, with what its person wrote about it (`description`, empty when nothing). `access` raises BridgeFailed (`unexpected`) when its stored address is not a bridge's,
    when used, so one bad address spoils that machine alone."""

    label: str
    base_url: str
    token: str = field(repr=False)
    person_id: int
    connection_id: int
    description: str = ""

    @property
    def access(self) -> Access:
        return Access.of(self.base_url, self.token, self.person_id)


async def held(household_id: int, person_id: int) -> tuple[Machine, ...]:
    """The person's machines, first made first. Raises ConnectionsUnavailable."""
    opened = await ports.opened_all(services.get(Connections), "herdr", household_id, person_id)
    made = sorted(opened, key=lambda o: o.connection.id)
    return tuple(Machine(o.connection.label, o.connection.base_url, o.secret, person_id, o.connection.id,
                         o.connection.description)
                 for o in made)


def choose(machines: tuple[Machine, ...], label: str | None, *, must_name: bool = False) -> Machine | None:
    """The machine called `label`; with none named, the person's only machine, else the default (the first made) unless
    `must_name`. None when `machines` is empty. Raises MachineRefused."""
    if not machines:
        return None
    first = machines[0]
    if label is None or label == "":
        if must_name and len(machines) > 1:
            raise MachineRefused("machine_needed")
        return first
    found = next((m for m in machines if m.label == label), None)
    if found is None:
        raise MachineRefused("unknown_machine")
    return found
