"""Fakes for the on-demand tool tests: a turn's tools as several named sources, each with its own instructions, in
place of `turn_tools.for_turn`'s, and the prompt a first step is asked."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

import pytest
from ashley.channels import turn_tools
from ashley.channels.model import Inbound
from ashley.inference.model import Prompt, ToolCall, ToolResult, ToolSpec
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue, Tools

GROUPS: Mapping[str, tuple[str, ...]] = {"everyday": ("lights", "weather"), "reminders": ("remind", "reminders"),
                                         "mail": ("mail_search", "mail_send"), "money": ("money_accounts",)}
READS = frozenset({"lights", "weather", "reminders", "mail_search", "money_accounts"})
INSTRUCTIONS = {"everyday": "How the lights work.", "reminders": "How reminders work.", "mail": "How mail works.",
                "money": "How money works."}


@dataclass
class Group(Tools):
    key: str
    called: list[str] = field(default_factory=list[str])

    async def catalogue(self) -> Catalogue:
        return Catalogue(tuple(ToolSpec(n, f"{n} tool", {"type": "object"}, reads=n in READS, outside=False)
                               for n in GROUPS[self.key]), INSTRUCTIONS[self.key])

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call.name)
        return ToolResult(call.id, f"{call.name} done")


def sources(*keys: str) -> dict[str, Tools]:
    return {k: Group(k) for k in (keys or tuple(GROUPS))}


def offer(monkeypatch: pytest.MonkeyPatch, made: Mapping[str, Tools], narrow: bool = True) -> None:
    """`turn_tools.for_turn` answers `made` as one composite, narrowed as the turn's fields say when `narrow`."""

    def for_turn(inbound: Inbound, *_: object, **__: object) -> Tools:
        offered = CompositeTools(dict(made))
        return turn_tools.narrowed(inbound, offered) if narrow else offered

    monkeypatch.setattr(turn_tools, "for_turn", for_turn)


def fingerprint(prompt: Prompt) -> str:
    """The first eight hex digits of the sha256 of a step's whole prompt (system, messages, tools, tool choice), the
    moment's clock line left out."""
    system = {k: replace(v, moment=re.sub(r"It is [^\n]*\n", "", v.moment)) for k, v in prompt.system.items()}
    return hashlib.sha256(repr(replace(prompt, system=system)).encode()).hexdigest()[:8]
