"""Whether a turn has read outside words. A turn is tainted by its origin (`Inbound.taint`) from its first step, and
by the first tool result that can carry text written outside the household, from then on; a taint never clears.
`Checkpoint.tainted` keeps which: the origin or the tool's name. Recording it changes nothing a turn does."""

from collections.abc import Mapping

from ..inference.model import ToolResult, ToolSpec


def specs_outside(tools: tuple[ToolSpec, ...]) -> dict[str, bool]:
    """Each offered tool's `outside`, by name."""
    return {t.name: t.outside for t in tools}


def taints(name: str, result: ToolResult, outside: Mapping[str, bool]) -> bool:
    """Whether the result of the call to `name` taints a turn: its own `outside` when it says, else its spec's in
    `outside`; a name not there taints."""
    return outside.get(name, True) if result.outside is None else result.outside
