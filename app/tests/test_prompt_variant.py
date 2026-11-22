"""A prompt variant leaves out exactly what it names from her turn's prompt and offered tools, and nothing else: no
variant is today's prompt, a name the code does not have fails naming it, and the report labels name the variant."""

import asyncio
import io
import json
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ashley import services
from ashley.channels import cut, speaker, turn_prompt
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.evals import prompt_sizes_live, variant
from ashley.evals.house_report import render, to_json
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools
from respond_support import ALANA, HOME, FakeConversations, FakePeople, FakePresence

SPECS = (ToolSpec("lights", "the lights", {"type": "object"}, reads=True),
         ToolSpec("lock", "the lock", {"type": "object"}, reads=True),
         ToolSpec("mail_send", "send mail", {"type": "object"}, reads=False),
         ToolSpec("mail_read", "read mail", {"type": "object"}, reads=True))
OWNERS = {"lights": "house", "lock": "house", "mail_send": "mail", "mail_read": "mail"}


@dataclass
class OwnedTools(Tools):
    specs: tuple[ToolSpec, ...] = SPECS
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, "Use the tools.", sources=("house", "mail"), owners=OWNERS)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        return ToolResult(call.id, "ok")


@pytest.fixture(autouse=True)
def seams() -> Generator[None]:
    services.register(People, FakePeople())
    services.register(Presence, FakePresence())
    services.register(Conversations, FakeConversations())
    services.register(InFlight, InFlight.null())
    cut.install(cut.NO_CUT)
    yield
    cut.install(cut.NO_CUT)
    for interface in (People, Presence, Conversations, InFlight):
        services.unregister(interface)


def built(channel: str = "web") -> turn_prompt.Prompted:
    ask = prompt_sizes_live.inbound("chat", channel, HOME.id, ALANA.id, "hello")
    who = asyncio.run(speaker.who(ask))
    return asyncio.run(turn_prompt.build(ask, who, OwnedTools(), turn_prompt.nothing_carried()))


def parts(prompted: turn_prompt.Prompted) -> dict[str, str]:
    return dict(persona.stable_parts("chat", prompted.context)["default"])


def varied(**data: object) -> variant.Variant:
    got = variant.parse(json.dumps({"name": "t", **data}))
    variant.install(got)
    return got


def test_no_variant_is_the_prompt_and_tools_she_has_today() -> None:
    got = built()
    plain = persona.Context(**{k: v for k, v in vars(got.context).items() if k not in ("left_out", "examples_out")})
    assert got.system == persona.system("chat", plain) and got.context == plain
    assert got.catalogue is not None and got.catalogue.specs == SPECS and got.catalogue.owners == OWNERS
    assert cut.active() is cut.NO_CUT and variant.label(None) == "none"
    variant.finish()


def test_a_section_cut_drops_those_parts_and_leaves_the_rest_byte_for_byte() -> None:
    base = parts(built())
    assert {"persona.wit", "persona.examples", "kind", "tools"} <= set(base)
    varied(sections=["persona.wit", "tools"])
    got = built()
    assert parts(got) == {k: v for k, v in base.items() if k not in ("persona.wit", "tools")}
    assert got.system["default"].stable == "\n\n".join(parts(got).values())
    assert got.catalogue is not None and got.catalogue.specs == SPECS


def test_a_locked_section_can_be_cut_too() -> None:
    base = parts(built())
    varied(sections=["persona.contract"])
    assert set(base) - set(parts(built())) == {"persona.contract"}


def test_an_example_cut_drops_that_example_only() -> None:
    base = parts(built())["persona.examples"]
    varied(examples=["presidents", "pla"])
    got = parts(built())["persona.examples"]
    assert "president" not in got and "PLA" not in got
    assert got.count("\n- ") == base.count("\n- ") - 2
    assert all(line in base for line in got.split("\n"))
    assert "pod bay" in got and "wind tunnel" in got


def test_a_tool_cut_drops_that_tool_and_a_source_cut_drops_its_tools() -> None:
    varied(tools=["lights"], sources=["mail"])
    got = built()
    assert got.catalogue is not None
    assert [s.name for s in got.catalogue.specs] == ["lock"]
    assert got.catalogue.owners == {"lock": "house"} and got.catalogue.sources == ("house",)
    assert got.catalogue.instructions == "Use the tools."
    variant.finish()


def test_a_tool_or_source_no_turn_offered_fails_the_run_naming_it() -> None:
    varied(tools=["lights", "ligths"], sources=["mial"])
    built()
    with pytest.raises(ValueError, match="ligths, mial"):
        variant.finish()


@pytest.mark.parametrize("data,needle", [
    ({"sections": ["persona.nope"]}, "persona.nope"),
    ({"sections": ["persona.wit", "wit"]}, "names wit,"),
    ({"examples": ["presidnts"]}, "presidnts"),
    ({"sectons": ["kind"]}, "sectons"),
    ({"tools": "lights"}, "'tools' is a list"),
    ({"name": ""}, "`name`"),
])
def test_a_name_the_code_does_not_have_is_an_error_that_names_it(data: dict[str, object], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        variant.parse(json.dumps({"name": "t", **data}))


def test_text_that_is_not_one_json_object_is_refused() -> None:
    for text in ("", "[]", "{"):
        with pytest.raises(ValueError):
            variant.parse(text)
    with pytest.raises(ValueError, match="cannot be read"):
        variant.read("/nonexistent/variant.json")


def test_the_label_names_the_variant_and_a_hash_of_its_json_whatever_its_layout() -> None:
    a = variant.parse('{"name": "t", "sections": ["kind"], "tools": ["lights"]}')
    b = variant.parse('{\n  "tools": ["lights"],\n  "sections": ["kind"],\n  "name": "t"\n}')
    c = variant.parse('{"name": "t", "sections": ["kind", "profile"]}')
    assert a.label == b.label and a.label.startswith("t@") and a.label != c.label


def test_the_reports_carry_the_variant_label() -> None:
    label = varied(sections=["kind"]).label
    assert json.loads(to_json({}, label))["variant"] == label
    assert render({}, label).startswith(f"variant: {label}")
    assert json.loads(to_json({}))["variant"] == "none"


@pytest.mark.parametrize("eval_name", ["house", "prompt-sizes"])
def test_the_entry_point_refuses_a_variant_with_an_unknown_name_before_touching_anything(
        eval_name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley.evals.__main__ import main
    path = tmp_path / "v.json"
    path.write_text('{"name": "typo", "examples": ["presidnts"]}')
    assert main([eval_name, "--variant", str(path)]) == 2
    assert "presidnts" in capsys.readouterr().err and cut.active() is cut.NO_CUT


def test_a_variant_from_stdin_is_read_with_a_dash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"name": "piped", "sections": ["kind"]}'))
    assert variant.read("-").name == "piped"
