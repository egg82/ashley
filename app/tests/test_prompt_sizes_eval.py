"""The prompt-sizes eval over a fake count: the stable sections are the whole stable prompt, a count is made per part
with the route's model, the report holds names and numbers and never a part's text, and the prompt and tools it
counts are the ones her real turn sends."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from anthropic import Omit
from anthropic.types import MessageParam, MessageTokensCount, OutputConfigParam, TextBlockParam, ToolParam
from ashley import services
from ashley.channels.respond import respond
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind
from ashley.evals import prompt_sizes, prompt_sizes_live
from ashley.evals.prompt_sizes import Request, Sizes, measure
from ashley.evals.prompt_sizes_report import Meta, render, to_json
from ashley.inference import anthropic_wire
from ashley.inference.inference import Inference
from ashley.inference.model import Route, SystemPrompt, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.routes import Routes
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.tools.tools import Tools
from respond_support import ALANA, HOME, FakeConversations, FakeInference, FakePeople, FakePresence, FakeTools

from ashley.conversations.conversations import Conversations

SENTINEL = "SENTINEL-do-not-print-7f3a"
MODEL = "claude-test-model"
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = persona.Context(NOW, HOME, ALANA, frozenset({1}), "kitchen", "Tool guidance.", True)
LIGHTS, LOCK = ToolSpec("lights", f"the lights {SENTINEL}", {"type": "object"}), ToolSpec("lock", "the lock", {"type": "object"})


class Seen:
    """A fake count: tokens grow with the request's size, and every request is kept."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, Request]] = []

    async def __call__(self, model: str, request: Request) -> int:
        self.asked.append((model, request))
        return 5 + len(json.dumps(asdict(request))) // 4


def sizes(count: Seen, owners: dict[str, str] | None = None, tools: tuple[ToolSpec, ...] = (LIGHTS, LOCK)) -> Sizes:
    parts = [("persona.who", "Who she is."), ("kind", f"The rules. {SENTINEL}"), ("profile", "A household.")]
    system = SystemPrompt("\n\n".join(t for _, t in parts), f"It is late. {SENTINEL}")
    return asyncio.run(measure(count, MODEL, parts, system, tools, owners or {"lights": "house", "lock": "house"},
                               {"type": "object", "properties": {}}))


def test_the_sections_are_the_whole_stable_prompt_for_every_kind_and_variant() -> None:
    for kind in ("command", "chat", "brainstorm"):
        kinded: Kind = kind
        built, parts = persona.system(kinded, CONTEXT), persona.stable_parts(kinded, CONTEXT)
        assert set(parts) == set(built) and built
        for variant, found in parts.items():
            assert len(found) >= 4 and len({name for name, _ in found}) == len(found)
            assert sum(len(text) for _, text in found) + 2 * (len(found) - 1) == len(built[variant].stable)
            assert "\n\n".join(text for _, text in found) == built[variant].stable


def test_a_part_list_that_does_not_make_the_stable_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match="stable"):
        asyncio.run(measure(Seen(), MODEL, [("a", "one")], SystemPrompt("two"), (), {}, {}))


def test_a_count_is_made_per_section_and_per_tool_on_the_routes_model() -> None:
    seen = Seen()
    got = sizes(seen)
    assert {model for model, _ in seen.asked} == {MODEL} and len(seen.asked) == got.calls
    alone = [r.system[0]["text"] for _, r in seen.asked if r.system and not r.tools and len(r.messages) == 1 and r.messages[0]["content"] == "."]
    for _, text in [("persona.who", "Who she is."), ("kind", f"The rules. {SENTINEL}"), ("profile", "A household.")]:
        assert text in alone
    named = [r.tools[0]["name"] for _, r in seen.asked if r.tools and len(r.tools) == 1]
    assert {"lights", "lock"} <= set(named)
    assert [p.name for p in got.stable] == ["persona.who", "kind", "profile"] and [p.name for p in got.tools] == ["lights", "lock"]
    assert all(p.tokens > 0 for p in (*got.stable, *got.tools, got.moment, got.reply_schema))
    assert got.stable[1].chars == len(f"The rules. {SENTINEL}") and got.joins == 4


def test_tools_group_by_their_source_and_a_tool_nobody_offered_is_its_own_group() -> None:
    got = sizes(Seen(), {"lights": "house", "lock": "house"}, (LIGHTS, LOCK, ToolSpec("carry_out", "go", {"type": "object"})))
    assert [(g.name, g.members) for g in got.groups] == [("house", 2), (prompt_sizes.UNOWNED, 1)]
    assert sizes(Seen(), {"lights": "a", "lock": "b"}).groups[1].name == "b"


def test_a_turn_with_no_tools_counts_none_and_still_measures_the_rest() -> None:
    got = sizes(Seen(), {}, ())
    assert got.tools == () and got.groups == () and got.tools_whole.tokens == 0 and got.stable_whole.tokens > 0


def test_the_report_holds_names_and_numbers_and_never_a_parts_text(tmp_path: Path) -> None:
    seen = Seen()
    got = sizes(seen)
    assert any(SENTINEL in json.dumps(asdict(r)) for _, r in seen.asked)
    meta = Meta("chat", "web", "anthropic", MODEL, "gemini/g", 6)
    out, written = render(got, meta), to_json(got, meta)
    for text in (out, written):
        assert SENTINEL not in text and "Who she is" not in text and "A household" not in text
        assert "persona.who" in text and "lights" in text and MODEL in text
    parsed = json.loads(written)
    assert [s["name"] for s in parsed["stable"]["sections"]] == ["persona.who", "kind", "profile"]
    assert parsed["whole_request_tokens"] == got.whole and parsed["calls"] == got.calls


class FakeMessages:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, object]] = []

    async def count_tokens(self, *, model: str, messages: list[MessageParam], system: list[TextBlockParam] | Omit,
                           tools: list[ToolParam] | Omit, output_config: OutputConfigParam | Omit) -> MessageTokensCount:
        self.kwargs.append({"model": model, "system": system, "tools": tools, "output_config": output_config})
        return MessageTokensCount(input_tokens=11)


async def _counted(count: prompt_sizes.Count, request: Request) -> int:
    return await count(MODEL, request)


def test_the_sdk_count_sends_the_model_and_only_the_parts_a_request_has() -> None:
    fake = FakeMessages()
    count = prompt_sizes_live.counting(fake)
    plain = Request([MessageParam(role="user", content=".")])
    full = Request(plain.messages, anthropic_wire.system(SystemPrompt("s")), anthropic_wire.tools((LIGHTS,)), {"type": "object"})
    assert asyncio.run(_counted(count, plain)) == 11 and asyncio.run(_counted(count, full)) == 11
    assert all(k["model"] == MODEL for k in fake.kwargs)
    assert [isinstance(k["system"], Omit) for k in fake.kwargs] == [True, False]
    assert [isinstance(k["output_config"], Omit) for k in fake.kwargs] == [True, False]
    assert fake.kwargs[1]["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}}


def test_the_counted_route_is_the_first_anthropic_one_and_names_a_first_that_is_not() -> None:
    routes = Routes({"chat": (Route("gemini", "g", 30.0), Route("anthropic", MODEL, 30.0)),
                     "command": (Route("anthropic", "c", 30.0),), "brainstorm": (Route("gemini", "g", 30.0),)}, 60.0)
    assert prompt_sizes_live.counted_route(routes, "chat") == (Route("anthropic", MODEL, 30.0), "gemini/g")
    assert prompt_sizes_live.counted_route(routes, "command")[1] == ""
    with pytest.raises(ValueError, match="no Anthropic route"):
        prompt_sizes_live.counted_route(routes, "brainstorm")


@pytest.fixture
def turn() -> Generator[FakeInference]:
    inference = FakeInference()
    services.register(People, FakePeople())
    services.register(Presence, FakePresence())
    services.register(Conversations, FakeConversations())
    services.register(InFlight, InFlight.null())
    services.register(Tools, FakeTools((LIGHTS, LOCK)))
    services.register(Inference, inference)
    yield inference
    for interface in (People, Presence, Conversations, InFlight, Tools, Inference):
        services.unregister(interface)


@pytest.mark.parametrize("channel", prompt_sizes_live.CHANNELS)
def test_what_it_counts_is_the_prompt_and_tools_her_turn_sends(turn: FakeInference, channel: str, tmp_path: Path) -> None:
    turn.script = [Reply(spoken="Hi.", text="Hi.")]
    ask = prompt_sizes_live.inbound("chat", channel, HOME.id, ALANA.id, "hello")
    asyncio.run(respond(ask))
    sent = turn.prompts[0]
    seen = Seen()
    routes = Routes({"chat": (Route("anthropic", MODEL, 30.0),)}, 60.0)
    options = prompt_sizes_live.Options("chat", channel, HOME.id, None, "hello")
    out = asyncio.run(prompt_sizes_live.run(seen, routes, options, tmp_path / "sizes.json"))
    whole = [r for _, r in seen.asked if r.system and r.tools and r.reply_schema]
    assert len(whole) == 1 and {m for m, _ in seen.asked} == {MODEL}
    assert whole[0].system == anthropic_wire.system(sent.system_for("default"))
    assert whole[0].tools == anthropic_wire.tools(sent.tools) and len(sent.tools) >= 2
    assert whole[0].reply_schema == anthropic_wire.reply_schema(Reply)
    assert "persona." in out and "lights" in out and "hello" not in out.replace("Hello", "")
    assert json.loads((tmp_path / "sizes.json").read_text())["meta"]["channel"] == channel
