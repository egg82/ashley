"""A cut of a turn's prompt, applied by the turn and set by nothing outside `ashley.evals`: parts of the stable prompt,
persona examples, tools and tool sources the turn leaves out, so an eval can measure a prompt with something removed
on the code the app runs (`ashley.evals.variant` names and checks the parts). `NO_CUT` is the default and changes
nothing; `install` is the setter, called by the eval entry point only (`tests/test_cut_seam.py` fails on any other
caller)."""

from dataclasses import dataclass, replace

from ..tools.tools import Catalogue
from . import on_demand


@dataclass(frozen=True)
class Cut:
    """`sections` are `persona.stable_parts` names, `examples` persona example ids (`persona.sections`), `tools` tool
    names and `sources` the keys of tool sources (`Catalogue.owners`). `core`, when set, is the keys of the tool sources
    a turn offers from its first step; the others load on demand (`channels.on_demand`), and None offers every source."""

    sections: frozenset[str] = frozenset()
    examples: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()
    core: frozenset[str] | None = None


NO_CUT = Cut()

_active = NO_CUT
_met: set[str] = set()


def active() -> Cut:
    """The cut in force: `NO_CUT` unless an eval installed one."""
    return _active


def install(cut: Cut) -> None:
    """Make `cut` the one in force for every turn of this process, and forget which of its tools and sources were met."""
    global _active
    _active = cut
    _met.clear()


def thinned(catalogue: Catalogue, loaded: frozenset[str] = frozenset()) -> Catalogue:
    """`catalogue` less the cut's tools and the tools of its sources. A catalogue that holds the loader tool is also
    less the sources outside the cut's `core` that are not `loaded`, with their instructions, the loader and the loaded
    sources' tools last. The catalogue itself when nothing is cut."""
    cut = _active
    if cut.core is not None:
        catalogue = _cored(catalogue, cut.core, loaded)
    if not cut.tools and not cut.sources:
        return catalogue
    owners = catalogue.owners
    gone = {s.name for s in catalogue.specs if s.name in cut.tools or owners.get(s.name) in cut.sources}
    _met.update(n for n in cut.tools if any(s.name == n for s in catalogue.specs))
    _met.update(k for k in cut.sources if k in {*owners.values(), *catalogue.sources})
    return replace(catalogue, specs=tuple(s for s in catalogue.specs if s.name not in gone),
                   sources=tuple(k for k in catalogue.sources if k not in cut.sources),
                   owners={n: k for n, k in owners.items() if n not in gone})


def _cored(catalogue: Catalogue, core: frozenset[str], loaded: frozenset[str]) -> Catalogue:
    if not any(s.name == on_demand.LOADER for s in catalogue.specs):
        return catalogue
    owners = catalogue.owners
    _met.update(k for k in core if k in owners.values())
    hidden = set(on_demand.held_back(catalogue, core)) - loaded
    now = tuple(s for s in catalogue.specs if s.name != on_demand.LOADER and owners.get(s.name) not in loaded | hidden)
    after = tuple(s for s in catalogue.specs if owners.get(s.name) in loaded)
    loader = tuple(s for s in catalogue.specs if s.name == on_demand.LOADER)
    guidance = {k: v for k, v in catalogue.guidance.items() if k not in hidden}
    return replace(catalogue, specs=(*now, *loader, *after), sources=tuple(k for k in catalogue.sources if k not in hidden),
                   owners={n: k for n, k in owners.items() if k not in hidden}, guidance=guidance,
                   instructions=("\n\n".join(guidance.values()) or None) if catalogue.guidance else catalogue.instructions)


def unmet() -> tuple[str, ...]:
    """The cut's tool, source and core names no catalogue a turn read has held, sorted: a typo, or a part this run never
    offered."""
    return tuple(sorted((_active.tools | _active.sources | (_active.core or frozenset())) - _met))
