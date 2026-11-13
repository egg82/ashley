"""Every schema the app can send a chat provider, collected through the real tool sources and the real wire modules,
and the keyword rules (`provider_schema_rejects.json`) a provider is known to answer 400 to."""

import ast
import asyncio
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard

from ashley import services, wiring
from ashley.channels import turn_tools
from ashley.channels.model import Inbound
from ashley.connections.connections import Connections
from ashley.home_assistant.homes import Homes
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.model import ToolSpec
from ashley.inference.reply import Reply
from ashley.memory import writer_output
from ashley.memory.eval.judge import Verdict
from ashley.tools.action_judge_model import Answer
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.runs.sandbox import Sandbox
from ashley.senses.deposits import Deposits, NullDeposits
from ashley.senses.proposal_payloads import REMINDERS, Payload, ReminderSchedule, Topic, encode
from ashley.senses.proposals import NullProposals, Proposal, Proposals
from ashley.senses.wakes import Reminder
from ashley.tidy.pointer import Pointed
from ashley.tools.bench_agent import JobResult
from ashley.tools.look_up import LookedUp
from ashley.tools.tools import Tools
from pydantic import BaseModel
from automations_support import FakeHouse
from source_tree import Parsed
from bench_run_support import Box
from homes_support import AnyHousehold
from money_support import HeldConnections
from test_reminder_turn import Home


RULES = Path(__file__).with_name("provider_schema_rejects.json")
APP = Path(__file__).resolve().parents[1] / "ashley"
HOUSEHOLD, ALANA, SAM, CONVERSATION, TURN = 10, 1, 2, 20, 30
RESPONSE_FORMATS: tuple[type[BaseModel], ...] = (Reply, writer_output.Written, Verdict, LookedUp, Pointed, Answer, JobResult)
"""The structured response formats the app sends. `unlisted_formats` fails when a call site names one not here."""


@dataclass(frozen=True)
class Sent:
    """One schema as a provider receives it: where it came from (`label`), and the schema."""

    label: str
    schema: Mapping[str, object]


def wire_tools(provider: str, specs: tuple[ToolSpec, ...]) -> list[Sent]:
    if provider == "anthropic":
        return [Sent(f"tool {t['name']}", dict(t["input_schema"])) for t in anthropic_wire.tools(specs)]
    return [Sent(f"tool {t['function']['name']}", dict(t["function"].get("parameters", {})))
            for t in openai_wire.tools(specs)]


def wire_formats(provider: str) -> list[Sent]:
    build = anthropic_wire.reply_schema if provider == "anthropic" else openai_wire.reply_schema
    return [Sent(f"format {f.__name__}", build(f)) for f in RESPONSE_FORMATS]


WIRES: dict[str, str] = {"anthropic": "anthropic", "openai": "openai-compatible", "gemini": "openai-compatible"}
"""The providers `wiring` builds a chat provider for, by the wire module that adapts their schemas."""


class _Proposed(NullProposals):
    """A reminder proposed in the turn before, so the tool that agrees to it is offered."""

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        if topic.name != REMINDERS.name:
            return await super().pending(made_by, conversation_id, topic)
        now = datetime.now(UTC)
        reminder = Reminder(HOUSEHOLD, made_by, made_by, "x", now + timedelta(days=1), None)
        return Proposal(HOUSEHOLD, made_by, conversation_id, TURN - 1, now, topic.decode(encode(ReminderSchedule(reminder))[1]))


def _inbound(**fields: Any) -> Inbound:
    base = Inbound(household_id=HOUSEHOLD, thread="person:1:web", text="hi", kind="chat", medium="text",
                   audience="owner", speaker_id=ALANA, shared=False, place=None, channel="web", later=True,
                   later_by="turn", opens_benches=True, on_page=True)
    return replace(base, **fields)


TURNS: tuple[Inbound, ...] = (
    _inbound(), _inbound(thread="bench:4", kind="brainstorm", bench_id=4),
    _inbound(audience="household", shared=True))
"""The shapes of turn that offer different sources: a person's chat, their bench's talk, and a shared channel."""


def offered() -> list[ToolSpec]:
    """Every tool the app offers across `TURNS`, from `turn_tools.for_turn` over the wired shared tools, a household
    with Sure, GitLab and GitHub connected, a sandbox, a house, and a money-rule proposal waiting."""
    shared, *_ = wiring.tools([], "https://search.test")
    connections = HeldConnections()
    for kind in ("sure", "gitlab", "github", "herdr"):
        connections.connect(HOUSEHOLD, kind=kind, person_id=ALANA if kind != "sure" else None)
    people = Household(HOUSEHOLD, "home", "America/Denver", "",
                       (Person(ALANA, HOUSEHOLD, "Alana"), Person(SAM, HOUSEHOLD, "Sam")))
    wired: dict[type[Any], Any] = {Tools: shared, Connections: connections, People: Home(people), Sandbox: Box(),
                                   Deposits: NullDeposits(), Proposals: _Proposed(), Homes: AnyHousehold(FakeHouse().house())}
    for interface, provider in wired.items():
        services.register(interface, provider)
    try:
        found: dict[tuple[str, str], ToolSpec] = {}
        for turn in TURNS:
            for spec in asyncio.run(turn_tools.for_turn(turn, (CONVERSATION, TURN)).catalogue()).specs:
                found[(spec.name, json.dumps(spec.parameters, sort_keys=True))] = spec
        return list(found.values())
    finally:
        for interface in wired:
            services.unregister(interface)


def collect(provider: str, specs: list[ToolSpec] | None = None) -> list[Sent]:
    """What `provider` is sent: its wire form of each tool, and of each response format."""
    return [*wire_tools(provider, tuple(offered() if specs is None else specs)), *wire_formats(provider)]


def rules() -> dict[str, list[dict[str, str]]]:
    return json.loads(RULES.read_text())


def _is_schema(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _schemas(value: object) -> list[Mapping[str, object]]:
    """`value` as schemas: itself when it is one, its members when a list."""
    if _is_schema(value):
        return [value]
    return [m for m in _members(value) if _is_schema(m)]


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _members(value: object) -> list[object]:
    return list(value) if _is_list(value) else []


def _children(node: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    for key in ("items", "additionalProperties", "not", "anyOf", "oneOf", "allOf", "prefixItems"):
        yield from _schemas(node.get(key))
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        named = node.get(key)
        if _is_schema(named):
            yield from _schemas(list(named.values()))


def _nodes(node: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    yield node
    for child in _children(node):
        yield from _nodes(child)


def _array_of_arrays(node: Mapping[str, object], keyword: str) -> bool:
    inner = node.get("items")
    return (node.get("type") == "array" and keyword in node and _is_schema(inner)
            and inner.get("type") == "array" and keyword in inner)


SHAPES: dict[str, Callable[[Mapping[str, object], str], bool]] = {
    "anywhere": lambda node, keyword: keyword in node,
    "array_and_its_array_items": _array_of_arrays,
}


def violations(provider: str, sent: list[Sent]) -> list[str]:
    """`label: keyword (shape)` for every place a schema in `sent` carries something `provider` rejects."""
    found: list[str] = []
    for rule in rules()[provider]:
        for one in sent:
            if any(SHAPES[rule["shape"]](node, rule["keyword"]) for node in _nodes(one.schema)):
                found.append(f"{one.label}: {rule['keyword']} ({rule['shape']})")
    return found


def used_formats(package_tree: Mapping[Path, Parsed]) -> set[str]:
    """Names of response formats passed to `Inference.step`/`generate` somewhere in the app (a capitalised name or the
    attribute of a module)."""
    used: set[str] = set()
    for path, parsed in package_tree.items():
        if APP not in path.parents or (".step(" not in parsed.source and ".generate(" not in parsed.source):
            continue
        for call in ast.walk(parsed.tree):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("step", "generate") and len(call.args) >= 3):
                arg = call.args[2]
                name = arg.id if isinstance(arg, ast.Name) else arg.attr if isinstance(arg, ast.Attribute) else ""
                if name[:1].isupper():
                    used.add(name)
    return used


def unlisted_formats(package_tree: Mapping[Path, Parsed]) -> set[str]:
    """Names `used_formats` finds that `RESPONSE_FORMATS` lacks."""
    return used_formats(package_tree) - {f.__name__ for f in RESPONSE_FORMATS}
