"""The system prompt for one reply. The prose lives in Markdown beside this module: `ashley.md` (who she is, for every
kind), one file per conversation kind in `kinds/` (`command.md`, `chat.md`, `brainstorm.md`: length and shape, the
rules for the `spoken` and `text` fields), and optional per-variant overrides in `variants/<variant>/` with the same
names, for a provider that needs different wording (`Route.variant`). Nothing about any one household is in those
files: that is `Household.profile`."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from ..conversations.model import Kind
from ..inference.model import SystemPrompt
from ..memory.model import Recalled
from ..people.model import Household, Person
from . import facts, prose, sections

NO_OVERRIDES: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class Context:
    """The facts of this moment. `now` is timezone-aware, in the household's timezone. `speaker` is who is talking,
    None when unknown. `home` is who is home, None when unknown (`Presence.home`). `place` is where a shared device is.
    `tool_instructions` is the tool source's own guidance (`Catalogue.instructions`); `tools_reachable` is False when
    the catalogue could not be read, so she says she cannot reach the house rather than pretend; `tools_unreachable` names
the tool sources that did not answer when others did (`Catalogue.unreachable`), each said in one line. `remembered` is what
    memory recalled for this message, best first, or None when memory could not be reached, which she is told, and
    `standing` is then empty. `standing` is the facts that hold every time (`Memory.profile`). `phone` is whether this
    reply's `text` may go to the speaker's phone (`Reply.to_phone`), which only a known speaker can have; `page_open`, on a turn she was woken for, whether the speaker has a page open
    (None: not a fact this turn is given). `aloud` is whether this message was said aloud on a page that can play her voice, which offers `Reply.aloud` (`channels.aloud.offered`). `overhears` is whether what she heard may not have been said to her (`Inbound.overhears`), which offers `Reply.says` `offer` and `none`. `said_before` is
    older turns that may bear on this message, one line each, already filtered to what this reply may hear. `while_away` is
    what she did since for asks she could not carry out, one line each, to tell. `tools_now` is the tool sources' state
    at this moment (`Catalogue.now`), in the `moment` layer. `overrides` is the household's text for the persona's
    overridable sections by section id (`ashley.skills.persona.bodies`), applied by `sections.render`, which ignores
    any id that is not an `allowed` section; empty, the persona is the shipped text. Every reply carries
    both a `spoken` and a `text` field whichever medium delivers it, so the medium is not a fact here."""

    now: datetime
    household: Household
    speaker: Person | None
    home: frozenset[int] | None
    place: str | None
    tool_instructions: str | None
    tools_reachable: bool
    remembered: tuple[Recalled, ...] | None = ()
    standing: tuple[Recalled, ...] = ()
    tools_unreachable: tuple[str, ...] = ()
    phone: bool = False
    page_open: bool | None = None
    aloud: bool = False
    overhears: bool = False
    said_before: tuple[str, ...] = ()
    while_away: tuple[str, ...] = ()
    tools_now: str | None = None
    overrides: Mapping[str, str] = NO_OVERRIDES


def system(kind: Kind, context: Context) -> Mapping[str, SystemPrompt]:
    """One system prompt per variant found under `variants/`, plus `default`: each is the persona (its `ashley.md`
    rendered with `context.overrides`), then the kind's
    rules, then the tool instructions or, when tools are unreachable, one line saying the house cannot be reached right
    now, then the household's units, its language when that is not English, and its profile when non-empty, then her standing facts (`facts.standing`; nothing when there are
    none), then what she remembers (`facts.remembered`; nothing when memory recalled nothing), then what was said before
    (`facts.said_before`; nothing when there is none), then what was done while they were away (`facts.while_away`; nothing
    when there is none), then the tools' state (`facts.tools_now`; nothing when there is none), then the facts of the
    moment last (the local date and time with weekday; the speaker's name or that the speaker is unknown; with `phone`,
    that `text` may go to their phone; who is home by name, or that it is unknown; the place, when known). Each is a
    `SystemPrompt`: the text up to the tool instructions, profile and standing facts is `stable`, and what she remembers,
    what was said before and the facts of the moment are `moment`, so a cached `stable` survives the clock moving.
    Raises ValueError for a naive `now`, a `speaker` or anyone in `home` not in `context.household`, `phone` with no
    `speaker`, or a kind with no file. Deterministic: the same arguments give the same text, so a cached prompt prefix stays cached."""
    facts.check(context.household, context.speaker, context.home, context.now)
    if context.phone and context.speaker is None:
        raise ValueError("only a known speaker has a phone")
    stable = [
        facts.tools(context.tool_instructions, context.tools_reachable, context.tools_unreachable),
        facts.profile(context.household),
        facts.standing(context.standing, context.now),
    ]
    moment = [
        facts.remembered(context.remembered, context.now),
        facts.said_before(context.said_before),
        facts.while_away(context.while_away),
        facts.tools_now(context.tools_now),
        facts.facts(context.now, context.household, context.speaker, context.home, context.place, context.phone,
                      context.page_open, context.aloud, context.overhears),
    ]
    return {variant: SystemPrompt(_assemble(variant, kind, context.overrides, context.household, stable), _join(moment))
            for variant in prose.variants()}


def _join(parts: list[str | None]) -> str:
    return "\n\n".join(part for part in parts if part)


def _assemble(variant: str, kind: Kind, overrides: Mapping[str, str], household: Household,
              after: list[str | None]) -> str:
    who, rules = prose.read(variant, sections.FILE), prose.read(variant, f"kinds/{kind}.md")
    if who is None or rules is None:
        raise ValueError(f"no persona text for kind {kind!r} in variant {variant!r}")
    return _join([facts.in_units(sections.render(who, overrides), household), rules, *after])
