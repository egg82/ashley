"""A turn under a cut with a `core` offers those tool sources from its first step and the rest only after she asks for
them with `use_tools` (`channels.on_demand`), through the real turn loop with a scripted model: the loader offers only
what the turn's own tools hold, a narrowed turn cannot load past its narrowing, and a turn another runner resumes offers
what the first had loaded."""

import asyncio
from collections.abc import Generator, Mapping
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels import cut, tool_loop
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.channels.on_demand import LOADER
from ashley.channels.respond import respond
from ashley.inference.inference import Inference
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from on_demand_support import Group, offer, sources
from respond_support import ALANA, FakeInference, Fakes, inbound, wired as wired

REPLY = Reply(spoken="Done.", text="Done.")
CHAT = replace(inbound("anything in my inbox?", thread="person:1:web", speaker_id=ALANA.id, kind="chat"),
               audience="owner", shared=False, place=None, channel="web", later=True, later_by="turn")
CORE = cut.Cut(core=frozenset({"everyday"}))


@pytest.fixture(autouse=True)
def installed() -> Generator[None]:
    cut.install(CORE)
    yield
    cut.install(cut.NO_CUT)


def load(*groups: str, id_: str = "u") -> ToolCalls:
    return ToolCalls((ToolCall(id_, LOADER, {"groups": list(groups)}),))


def names(specs: tuple[ToolSpec, ...]) -> list[str]:
    return [s.name for s in specs]


def ran(wired: Fakes, monkeypatch: pytest.MonkeyPatch, script: list[ToolCalls | Reply], ask: Inbound = CHAT) -> dict[str, Group]:
    made = sources()
    offer(monkeypatch, made)
    wired.inference.script = list(script)
    asyncio.run(respond(ask))
    return {k: g for k, g in made.items() if isinstance(g, Group)}


def test_the_first_step_offers_the_core_and_the_loader_and_only_the_core_s_instructions(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    ran(wired, monkeypatch, [REPLY])
    first = wired.inference.prompts[0]
    assert names(first.tools) == ["lights", "weather", LOADER]
    assert wired.contexts[0].tool_instructions == "How the lights work."
    loader = first.tools[-1]
    assert loader.reads and not loader.outside
    for key in ("reminders", "mail", "money"):
        assert f"- {key}:" in loader.description
    assert "- everyday:" not in loader.description


def test_a_loaded_group_is_offered_from_the_next_step_with_its_instructions(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    made = ran(wired, monkeypatch, [load("mail"), ToolCalls((ToolCall("m", "mail_search", {}),)), REPLY])
    first, second, third = wired.inference.prompts
    assert names(second.tools) == ["lights", "weather", LOADER, "mail_search", "mail_send"] == names(third.tools)
    assert "How mail works." in second.system["default"].moment and "How mail works." not in first.system["default"].moment
    assert "How reminders works." not in second.system["default"].moment
    assert made["mail"].called == ["mail_search"] and made["money"].called == []


def test_a_second_load_adds_to_the_first_and_each_groups_instructions_appear_once(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    ran(wired, monkeypatch, [load("mail", id_="a"), load("money", id_="b"), REPLY])
    last = wired.inference.prompts[2]
    assert names(last.tools) == ["lights", "weather", LOADER, "mail_search", "mail_send", "money_accounts"]
    moment = last.system["default"].moment
    assert moment.count("How mail works.") == 1 and moment.count("How money works.") == 1


@pytest.mark.parametrize("asked", [("everyday",), ("nothing",), ("mail", "nothing"), ()])
def test_a_group_the_turn_does_not_have_is_an_error_naming_the_groups_it_has_and_offers_nothing(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch, asked: tuple[str, ...]) -> None:
    ran(wired, monkeypatch, [load(*asked), REPLY])
    first, second = wired.inference.prompts
    assert names(second.tools) == names(first.tools)
    result = second.messages[-1]
    assert isinstance(result, ToolResults) and result.results[0].is_error
    assert "reminders, mail, money" in result.results[0].content


def test_a_reads_only_turn_loads_only_the_reads_of_a_group(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    ran(wired, monkeypatch, [load("mail"), REPLY], replace(CHAT, reads_only=True))
    first, second = wired.inference.prompts
    assert names(first.tools) == ["lights", "weather", LOADER]
    assert names(second.tools) == ["lights", "weather", LOADER, "mail_search"]


def test_a_turn_narrowed_to_named_tools_has_no_loader_and_offers_only_those(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    ran(wired, monkeypatch, [REPLY], replace(CHAT, tools_only=("lights", "mail_search")))
    assert names(wired.inference.prompts[0].tools) == ["lights", "mail_search"]


def test_a_turn_with_no_group_outside_the_core_has_no_loader(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    offer(monkeypatch, sources("everyday"))
    wired.inference.script = [REPLY]
    asyncio.run(respond(CHAT))
    assert names(wired.inference.prompts[0].tools) == ["lights", "weather"]


def test_a_turn_resumed_by_another_runner_offers_the_groups_the_first_loaded(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    offer(monkeypatch, sources())
    inference = FakeInference(script=[REPLY])
    services.register(Inference, inference)
    landing = Landing(CHAT, (1, 1), load_limits())
    system: Mapping[str, SystemPrompt] = {"default": SystemPrompt("system for chat")}
    offered = ToolResults((ToolResult("u", "Offered from your next step: money (1 tools)"),))
    progress = tool_loop.Progress((Message("person", CHAT.text), load("money"), offered), 1, 1)
    specs = asyncio.run(tool_loop.offered(landing))
    assert specs is not None and names(specs.specs) == ["lights", "weather", LOADER]

    asyncio.run(tool_loop.resumed(progress, "chat", system, specs.specs, load_limits()["chat"], 1, landing, False, 0.0,
                                  arrive=landing.arrived))
    prompt = inference.prompts[0]
    assert names(prompt.tools) == ["lights", "weather", LOADER, "money_accounts"]
    assert "How money works." in prompt.system["default"].moment
