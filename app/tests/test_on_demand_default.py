"""With no eval cut installed, a text turn begins with the loader alone and a spoken turn with every group
(`on_demand.json`, by `Inbound.medium`); an installed cut's `core` overrides that, `"all"` included; a text turn another
runner resumes offers the groups it loaded."""

import asyncio
import json
from collections.abc import Generator, Mapping
from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels import cut, on_demand, tool_loop
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.channels.on_demand import LOADER
from ashley.channels.respond import respond
from ashley.inference.inference import Inference
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.evals import variant
from on_demand_support import GROUPS, offer, sources
from contract.conversations_support import events
from respond_support import ALANA, FakeInference, Fakes, inbound, wired as wired

REPLY = Reply(spoken="Done.", text="Done.")
TEXT = replace(inbound("anything in my inbox?", thread="person:1:web", speaker_id=ALANA.id, kind="chat"),
               audience="owner", shared=False, place=None, channel="web", later=True, later_by="turn")
SPOKEN = replace(TEXT, medium="spoken")
EVERY_TOOL = [t for tools in GROUPS.values() for t in tools]


@pytest.fixture(autouse=True)
def no_cut() -> Generator[None]:
    cut.install(cut.NO_CUT)
    yield
    cut.install(cut.NO_CUT)


def names(specs: tuple[ToolSpec, ...]) -> list[str]:
    return [s.name for s in specs]


def first_tools(wired: Fakes, monkeypatch: pytest.MonkeyPatch, ask: Inbound) -> list[str]:
    offer(monkeypatch, sources())
    wired.inference.script = [REPLY]
    asyncio.run(respond(ask))
    return names(wired.inference.prompts[0].tools)


def test_a_text_turn_begins_with_the_loader_alone(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    assert first_tools(wired, monkeypatch, TEXT) == [LOADER]


def test_a_spoken_turn_begins_with_every_group_and_no_loader(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    assert first_tools(wired, monkeypatch, SPOKEN) == EVERY_TOOL


def test_the_turn_log_names_the_core_in_force_and_no_group(wired: Fakes, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    first_tools(wired, monkeypatch, TEXT)
    first_tools(wired, monkeypatch, SPOKEN)
    cut.install(cut.Cut(core=frozenset({"everyday"})))
    first_tools(wired, monkeypatch, TEXT)
    seen = [e["core"] for e in events(capsys.readouterr().out, "respond.offered")]
    assert seen == ["empty", "all", "some"]


def test_an_installed_cuts_core_overrides_the_default_for_either_medium(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    cut.install(cut.Cut(core=frozenset({"everyday"})))
    assert first_tools(wired, monkeypatch, TEXT) == ["lights", "weather", LOADER]
    assert first_tools(wired, monkeypatch, SPOKEN) == ["lights", "weather", LOADER]


def test_a_variant_core_all_gives_a_text_turn_every_group(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    variant.install(variant.parse(json.dumps({"name": "everything", "core": "all"})))
    assert first_tools(wired, monkeypatch, TEXT) == EVERY_TOOL


def test_a_variant_core_list_overrides_the_default(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    variant.install(variant.parse(json.dumps({"name": "some", "core": ["money"]})))
    assert first_tools(wired, monkeypatch, TEXT) == ["money_accounts", LOADER]


def test_a_turn_that_does_not_load_on_demand_keeps_every_tool_by_default(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    assert first_tools(wired, monkeypatch, replace(TEXT, tools_only=("lights", "mail_search"))) == ["lights", "mail_search"]


def test_a_text_turn_that_begins_with_her_look_at_a_camera_keeps_every_tool(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    assert first_tools(wired, monkeypatch, replace(TEXT, seen=("cam", None))) == EVERY_TOOL


def test_a_text_turn_resumed_by_another_runner_offers_the_groups_the_first_loaded(monkeypatch: pytest.MonkeyPatch,
                                                                                  wired: Fakes) -> None:
    offer(monkeypatch, sources())
    inference = FakeInference(script=[REPLY])
    services.register(Inference, inference)
    landing = Landing(TEXT, (1, 1), load_limits())
    system: Mapping[str, SystemPrompt] = {"default": SystemPrompt("system for chat")}
    asked = ToolCalls((ToolCall("u", LOADER, {"groups": ["money"]}),))
    offered = ToolResults((ToolResult("u", "Offered from your next step: money (1 tools)"),))
    progress = tool_loop.Progress((Message("person", TEXT.text), asked, offered), 1, 1)
    specs = asyncio.run(tool_loop.offered(landing))
    assert specs is not None and names(specs.specs) == [LOADER]

    asyncio.run(tool_loop.resumed(progress, "chat", system, specs.specs, load_limits()["chat"], 1, landing, False, 0.0,
                                  arrive=landing.arrived))
    assert names(inference.prompts[0].tools) == [LOADER, "money_accounts"]


def test_the_shipped_defaults_are_an_empty_core_for_text_and_every_group_for_speech() -> None:
    assert on_demand.defaults() == {"text": frozenset(), "spoken": None}


@pytest.mark.parametrize("bad", [None, [], {"text": []}, {"text": [], "spoken": None, "kiosk": None},
                                 {"text": "mail", "spoken": None}, {"text": [""], "spoken": None},
                                 {"text": [1], "spoken": None}, {"text": [], "spoken": {}}])
def test_a_defaults_file_that_is_not_one_core_per_medium_fails_loudly(bad: object) -> None:
    with pytest.raises(ValueError, match="on_demand.json"):
        on_demand.parse(bad)


def test_a_defaults_file_may_name_the_groups_a_medium_begins_with() -> None:
    assert on_demand.parse({"text": ["everyday"], "spoken": None}) == {"text": frozenset({"everyday"}), "spoken": None}
