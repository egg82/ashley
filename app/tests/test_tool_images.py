"""A tool result's pictures reach each provider in its own shape and survive a checkpoint."""

import base64
import json

from ashley.channels import checkpoint
from ashley.channels.checkpoint import Checkpoint
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import Progress
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.model import (Image, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults)

PNG = Image("image/png", b"\x89PNG-one")
JPEG = Image("image/jpeg", b"\xff\xd8-two")
ASKED = ToolCalls((ToolCall("c1", "bench_look", {}), ToolCall("c2", "bench_read", {})))


def entries(first: ToolResult, second: ToolResult) -> tuple[Message | ToolCalls | ToolResults, ...]:
    return (Message("person", "look"), ASKED, ToolResults((first, second)))


def b64(image: Image) -> str:
    return base64.b64encode(image.data).decode()


def test_anthropic_puts_the_pictures_in_the_tool_result_after_its_text() -> None:
    turns = anthropic_wire.messages(entries(ToolResult("c1", "seen", images=(PNG, JPEG)), ToolResult("c2", "plain")))
    assert json.loads(json.dumps(turns[2])) == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "is_error": False, "content": [
            {"type": "text", "text": "seen"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64(PNG)}},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(JPEG)}}]},
        {"type": "tool_result", "tool_use_id": "c2", "is_error": False, "content": "plain"}]}


def test_openai_sends_the_pictures_in_a_user_message_right_after_the_tool_messages() -> None:
    system = SystemPrompt("stable", "now")
    out = json.loads(json.dumps(openai_wire.messages(
        system, entries(ToolResult("c1", "seen", images=(PNG,)), ToolResult("c2", "plain")))))
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool", "user", "user"]
    assert out[5] == {"role": "user", "content": [
        {"type": "text", "text": f"{openai_wire.PICTURE_LABEL} c1:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(PNG)}}]}
    assert "now" in out[6]["content"]


def test_openai_adds_no_message_when_no_result_has_a_picture() -> None:
    out = openai_wire.messages(SystemPrompt("stable"), entries(ToolResult("c1", "a"), ToolResult("c2", "b")))
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool"]


def saved(progress: Progress) -> Progress:
    inbound = Inbound(household_id=1, thread="person:1:web", text="look", kind="chat", medium="text", audience="owner",
                      speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn")
    system = {"default": SystemPrompt("s", "m")}
    return checkpoint.loads(checkpoint.dumps(Checkpoint(inbound, 1, 2, 1, system, progress))).progress


def test_pictures_survive_a_checkpoint_in_its_entries_and_its_round_in_flight() -> None:
    result = ToolResult("c1", "seen", images=(PNG, JPEG))
    again = saved(Progress(entries(result, ToolResult("c2", "x")), 1, 2, ASKED, {"c1": result}))
    assert again.done["c1"].images == (PNG, JPEG)
    last = again.entries[2]
    assert isinstance(last, ToolResults) and last.results[0].images == (PNG, JPEG) and last.results[1].images == ()


def test_a_result_written_before_pictures_existed_reads_back_without_any() -> None:
    result = ToolResult("c1", "x")
    text = checkpoint.dumps(Checkpoint(Inbound(household_id=1, thread="t", text="a", kind="chat", medium="text",
                                               audience="owner", speaker_id=1, shared=False, place=None, channel="web",
                                               later=True, later_by="turn"), 1, 2, 1, {"default": SystemPrompt("s")},
                                       Progress((), 1, 1, ASKED, {"c1": result})))
    old = text.replace(', "images": []', "")
    assert old != text
    assert checkpoint.loads(old).progress.done["c1"] == result
