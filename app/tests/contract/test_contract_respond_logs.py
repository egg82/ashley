"""`respond`'s log lines: `respond.done` with the conversation id, kind, medium, tool rounds, tool calls, speaker
`known` or `unknown` and duration_ms; `respond.failed` with a reason; never the message, the reply, a tool's arguments
or result, or anyone's name."""

import pytest
from ashley import logs
from ashley.channels.respond import RespondRefused, RespondUnavailable, respond
from ashley.conversations.conversations import ConversationsUnavailable
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import SystemPrompt, ToolCall, ToolCalls, ToolResult
from ashley.inference.reply import Reply
from ashley.people.model import Household, Person
from ashley.tools.tools import Catalogue
from conversations_support import events
from inference_support import settle
from turns_support import HOUSE, SPEC, OTHER_SPEC, World, asks, inbound, world as world

MARK = "zqLEAK8812"
STANDARD = {"ts", "level", "logger", "event"}


def test_done_carries_id_kind_medium_rounds_calls_speaker_and_duration(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.script = [asks("lights", "weather", round_=1), asks("lights", round_=2)]
    logs.setup()
    capsys.readouterr()
    out = settle(respond(inbound(kind="chat", medium="text", speaker_id=11)))
    (line,) = events(capsys.readouterr().out, "respond.done")
    assert out.conversation_id == 41
    assert {"41", "chat", "text", "2", "3", "known"} <= set(line.values())
    assert "duration_ms" in line


def test_done_says_unknown_for_an_unknown_speaker_and_zero_tools(world: World,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound(kind="brainstorm", medium="spoken")))
    (line,) = events(capsys.readouterr().out, "respond.done")
    assert {"41", "brainstorm", "spoken", "0", "unknown"} <= set(line.values())
    assert "known" not in line.values()


@pytest.mark.parametrize("failure", ["inference", "refused", "conversations"])
def test_failed_carries_a_reason_and_there_is_no_done(world: World, capsys: pytest.CaptureFixture[str],
                                                      failure: str) -> None:
    if failure == "inference":
        world.inference.then = InferenceUnavailable("none")
    elif failure == "refused":
        world.inference.then = InferenceRefused("no")
    else:
        world.conversations.error = ConversationsUnavailable("failover")
    logs.setup()
    capsys.readouterr()
    with pytest.raises((RespondUnavailable, RespondRefused)):
        settle(respond(inbound()))
    out = capsys.readouterr().out
    (line,) = events(out, "respond.failed")
    assert set(line) - STANDARD, "the line carries a reason"
    assert events(out, "respond.done") == []


def marked(world: World) -> None:
    """Plant MARK in every piece of content respond handles: names, profile, catalogue, tool arguments and results,
    the reply, and the persona's prompts."""
    alana, sam = Person(11, HOUSE, f"Alana {MARK}"), Person(12, HOUSE, f"Sam {MARK}")
    world.people.households[HOUSE] = Household(HOUSE, f"home {MARK}", "UTC", f"profile {MARK}", (alana, sam))
    assert world.tools.on_offer is not None
    world.tools.on_offer = Catalogue((SPEC, OTHER_SPEC), f"instructions {MARK}")
    world.tools.results["lights"] = ToolResult("x", f'{{"secret": "{MARK}"}}')
    world.tools.results["weather"] = ToolResult("x", f"failed {MARK}", is_error=True)
    world.inference.script = [ToolCalls((ToolCall("c1", "lights", {"name": MARK}),
                                         ToolCall("c2", "weather", {"where": f"{MARK} street"})))]
    world.inference.then = Reply(spoken=f"spoken {MARK}", text=f"text {MARK}")
    world.persona.prompts = {"default": SystemPrompt(f"persona {MARK}")}


def test_no_content_reaches_any_log_line(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    marked(world)
    world.presence.answer = frozenset({12})
    logs.setup()
    capsys.readouterr()
    out_ = settle(respond(inbound(text=f"my secret is {MARK}", medium="text")))
    world.conversations.ashley_error = ConversationsUnavailable("failover")
    marked(world)
    settle(respond(inbound(text=f"again {MARK}", thread="device:4", speaker_id=11)))
    marked(world)
    world.inference.then = InferenceRefused(f"refused {MARK}")
    with pytest.raises(RespondRefused):
        settle(respond(inbound(text=f"refuse {MARK}", thread="device:5")))
    out = capsys.readouterr().out
    assert MARK in out_.body, "control: the content went through"
    assert len(events(out, "respond.done")) == 2, "control: the replies were logged"
    assert len(events(out, "respond.turn_unrecorded")) == 1
    assert len(events(out, "respond.failed")) == 1
    assert MARK not in out
    for word in ("secret", "Alana", "Sam", "street", "profile", "instructions"):
        assert word not in out
