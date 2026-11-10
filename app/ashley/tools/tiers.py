"""Which tier a call is, read from `tiers.json` (`tiers_config`): a Specification over the call's tool, arguments and, for
a house action, the things it resolves to. Reads no wording. `by_arguments` is what `Tools.tier` answers unless a
source knows more; `of_house_do` is the house source's answer."""

from collections.abc import Sequence
from dataclasses import dataclass

from ..inference.model import Tier, ToolCall
from .tiers_config import HouseRule, TiersConfig, load

CONFIG = load()


@dataclass(frozen=True)
class Target:
    """One thing a house call names: its `id`, `domain` and `device_class` (None when the house gives none)."""

    id: str
    domain: str
    device_class: str | None


def by_arguments(call: ToolCall, config: TiersConfig = CONFIG) -> Tier | None:
    """The tier an argument rule gives `call`, the first that matches; None when none does (the spec's own stands)."""
    for rule in config.arguments:
        given = call.arguments.get(rule.argument)
        if call.name == rule.tool and _present(given) and (not rule.values or _named(given, rule.values)):
            return rule.tier
    return None


def of_house_do(action: str, targets: Sequence[Target], config: TiersConfig = CONFIG,
                consequential: Sequence[str] = ()) -> Tier:
    """`runs` when every target the call names is `runs` under the first rule matching it and none is in
    `consequential` (the household's `consequential_entities`); else `judged`. A call that names no target is judged as
    the action alone."""
    if any(t.id in consequential for t in targets):
        return "judged"
    tiers = [_target_tier(config.house_do, action, t, config.default) for t in targets or (None,)]
    return "judged" if "judged" in tiers else "runs"


def _target_tier(rules: Sequence[HouseRule], action: str, target: Target | None, default: Tier) -> Tier:
    domain = action.partition(".")[0]
    if target is not None and target.domain != domain:
        return "judged"
    for rule in rules:
        if _matches(rule, action, domain, target):
            return rule.tier
    return default


def _matches(rule: HouseRule, action: str, domain: str, target: Target | None) -> bool:
    if (rule.domain is not None and rule.domain != domain) or (rule.action is not None and rule.action != action):
        return False
    return not rule.device_class or (target is not None and target.device_class in rule.device_class)


def _present(value: object) -> bool:
    return value is not None and value != "" and value != [] and value is not False


def _named(value: object, values: tuple[str, ...]) -> bool:
    return isinstance(value, str) and value.strip().lower() in values
