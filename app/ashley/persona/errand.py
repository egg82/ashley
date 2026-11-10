"""The system prompt for an errand run (`ashley.errands`): who she is, `errand.md` saying what she is doing and for
whom, the sources' tool guidance, the household's units and profile, and the time."""

from collections.abc import Mapping
from datetime import datetime

from ..inference.model import SystemPrompt
from ..people.model import Household, Person
from . import facts, prose


def system(household: Household, asker: Person, source: str, instructions: str | None, unreachable: tuple[str, ...],
           now: datetime) -> Mapping[str, SystemPrompt]:
    """One system prompt per variant: the persona, the errand section naming `asker` and the `source` that was out of
    reach, `# Tools` from `instructions` and `unreachable` (`facts.tools`), the household's units and profile, and
    `# Now`. Raises ValueError for a naive `now`, an `asker` not in `household`, or a variant with no errand text."""
    facts.check(household, asker, None, now)
    now_line = f"# Now\n\nIt is {facts.when(now)}."
    prompts: dict[str, SystemPrompt] = {}
    for variant in prose.variants():
        who, errand = prose.read(variant, "ashley.md"), prose.read(variant, "errand.md")
        if who is None or errand is None:
            raise ValueError(f"no persona text for an errand in variant {variant!r}")
        parts = [who, errand.format(name=asker.name, source=source), facts.tools(instructions, True, unreachable),
                 facts.profile(household)]
        prompts[variant] = SystemPrompt("\n\n".join(p for p in parts if p), now_line)
    return prompts
