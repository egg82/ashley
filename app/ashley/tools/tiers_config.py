"""What a tainted turn does with a change, as data in `tiers.json` beside this module (`decisions.md`, "A turn that has read
outside words asks before it does anything consequential the person did not ask for"). A tool's own tier is on its
`ToolSpec`; this file holds what refines it per call:

- `arguments`: a call to `tool` whose `argument` is given (and, when `values` is listed, is one of them) has `tier`;
- `house_do`: ordered rules over the action and each target the call resolves to, the first that matches deciding;
- `default`: the tier of anything no rule matches."""

import json
from dataclasses import dataclass
from pathlib import Path

from ..home_assistant.ha_json import listed, names, obj, text
from ..inference.model import Tier

FILE = Path(__file__).with_name("tiers.json")
_TIERS: tuple[Tier, ...] = ("runs", "judged")


@dataclass(frozen=True)
class ArgumentRule:
    """`tool`'s call is `tier` when its `argument` is given; when `values` is not empty, only when it names one of them
    (a string compared in lower case)."""

    tool: str
    argument: str
    values: tuple[str, ...]
    tier: Tier


@dataclass(frozen=True)
class HouseRule:
    """A rule that matches an action of `domain` (when given) or exactly `action` (when given), on a target whose
    `device_class` is one of those listed (any, when none are)."""

    tier: Tier
    domain: str | None
    action: str | None
    device_class: tuple[str, ...]


@dataclass(frozen=True)
class TiersConfig:
    default: Tier
    arguments: tuple[ArgumentRule, ...]
    house_do: tuple[HouseRule, ...]


def load() -> TiersConfig:
    """The tiers shipped in `tiers.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> TiersConfig:
    """TiersConfig from JSON already parsed. Raises ValueError unless the keys are exactly `default`, `arguments` and
    `house_do`, each tier is `runs` or `judged`, and each rule is well formed. The things a household always has
    judged are its own settings (`home_assistant.house_values`), not shipped data."""
    top = obj(raw)
    if set(top) != {"default", "arguments", "house_do"}:
        raise ValueError("tiers.json has exactly default, arguments and house_do")
    return TiersConfig(_tier(top["default"]), tuple(_argument(r) for r in listed(top["arguments"])),
                       tuple(_house(r) for r in listed(top["house_do"])))


def _tier(value: object) -> Tier:
    for t in _TIERS:
        if value == t:
            return t
    raise ValueError("a tier is runs or judged")


def _argument(raw: object) -> ArgumentRule:
    rule = obj(raw)
    if set(rule) - {"tool", "argument", "values", "tier"} or not {"tool", "argument", "tier"} <= set(rule):
        raise ValueError("an argument rule has tool, argument, tier and optionally values")
    tool, argument = text(rule["tool"]), text(rule["argument"])
    if not tool or not argument:
        raise ValueError("an argument rule names a tool and an argument")
    values = names(rule.get("values", []))
    if len(values) != len(listed(rule.get("values", []))):
        raise ValueError("an argument rule's values are non-empty strings")
    return ArgumentRule(tool, argument, tuple(v.lower() for v in values), _tier(rule["tier"]))


def _house(raw: object) -> HouseRule:
    rule = obj(raw)
    if set(rule) - {"tier", "domain", "action", "device_class"} or "tier" not in rule:
        raise ValueError("a house_do rule has tier and optionally domain, action and device_class")
    domain, action = text(rule.get("domain")) or None, text(rule.get("action")) or None
    if (domain is None) == (action is None):
        raise ValueError("a house_do rule names a domain or an action, not both and not neither")
    return HouseRule(_tier(rule["tier"]), domain, action, names(rule.get("device_class", [])))

