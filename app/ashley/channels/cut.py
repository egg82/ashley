"""A cut of a turn's prompt, applied by the turn and set by nothing outside `ashley.evals`: parts of the stable prompt,
persona examples, tools and tool sources the turn leaves out, so an eval can measure a prompt with something removed
on the code the app runs (`ashley.evals.variant` names and checks the parts). `NO_CUT` is the default and changes
nothing; `install` is the setter, called by the eval entry point only (`tests/test_cut_seam.py` fails on any other
caller)."""

from dataclasses import dataclass, replace

from ..tools.tools import Catalogue


@dataclass(frozen=True)
class Cut:
    """`sections` are `persona.stable_parts` names, `examples` persona example ids (`persona.sections`), `tools` tool
    names and `sources` the keys of tool sources (`Catalogue.owners`)."""

    sections: frozenset[str] = frozenset()
    examples: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()


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


def thinned(catalogue: Catalogue) -> Catalogue:
    """`catalogue` less the cut's tools and the tools of its sources. The catalogue itself when nothing is cut."""
    cut = _active
    if not cut.tools and not cut.sources:
        return catalogue
    owners = catalogue.owners
    gone = {s.name for s in catalogue.specs if s.name in cut.tools or owners.get(s.name) in cut.sources}
    _met.update(n for n in cut.tools if any(s.name == n for s in catalogue.specs))
    _met.update(k for k in cut.sources if k in {*owners.values(), *catalogue.sources})
    return replace(catalogue, specs=tuple(s for s in catalogue.specs if s.name not in gone),
                   sources=tuple(k for k in catalogue.sources if k not in cut.sources),
                   owners={n: k for n, k in owners.items() if n not in gone})


def unmet() -> tuple[str, ...]:
    """The cut's tool and source names no catalogue a turn read has held, sorted: a typo, or a part this run never offered."""
    return tuple(sorted((_active.tools | _active.sources) - _met))
