"""A turn begun with `Inbound.seen` starts with her look at a camera's recording, as the tool makes it (the picture
prepared and kept as a look on no bench), as a tool call and its result before her first step; a turn without it is
untouched; a look that fails is the tool's error result, not a missing step; and `seen` survives the checkpoint."""

import asyncio
from dataclasses import replace

import pytest
from files_support import sync
from ashley import services
from ashley.channels import seen
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.inference.model import Entry, Image, Message, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.looks.looks import Looks
from ashley.tools.camera_specs import LOOK
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from inflight_blind.ifb_checkpoint_support import checkpoint
from respond_support import Fakes, inbound, wired as wired
from test_camera_port import HALL, PORCH, world
from test_camera_recordings import RED, GREEN, BLUE, gif, keep

START: tuple[Entry, ...] = (Message("person", "ring"),)
OFFERED = (ToolSpec(LOOK, "look", {"type": "object"}, reads=True),)


def seeing(camera: str, recording: str) -> Inbound:
    return replace(inbound(), seen=(camera, recording))


def pair(got: tuple[Entry, ...]) -> tuple[ToolCall, ToolResult]:
    assert got[0] == START[0] and len(got) == 3
    calls, results = got[1], got[2]
    assert isinstance(calls, ToolCalls) and isinstance(results, ToolResults)
    (call,), (result,) = calls.calls, results.results
    return call, result


@sync
async def test_the_look_is_her_tool_call_and_its_result_with_the_picture_kept_as_a_look_on_no_bench(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((RED, GREEN, BLUE)))
        got = await seen.carried(replace(inbound(), household_id=home, seen=(PORCH, event.id)), conversation, turn, START, OFFERED)
        call, result = pair(got)
        assert (call.name, dict(call.arguments)) == (LOOK, {"camera": PORCH, "recording": event.id})
        assert not result.is_error and len(result.images) == 1 and result.call_id == call.id
        (kept,) = await services.get(Looks).in_conversation(home, conversation)
        assert (kept.call_id, kept.bench_id) == (call.id, None)


@sync
async def test_without_seen_the_entries_are_returned_untouched_and_nothing_is_looked_at(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        keep(house, PORCH, 1, gif((RED,)))
        assert await seen.carried(replace(inbound(), household_id=home), conversation, turn, START, OFFERED) == START
        assert await services.get(Looks).in_conversation(home, conversation) == []


@sync
async def test_a_look_that_fails_is_an_error_result_telling_her_so_and_keeps_nothing(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((RED, GREEN)))
        other = replace(inbound(), household_id=home, seen=(HALL, event.id))
        _, result = pair(await seen.carried(other, conversation, turn, START, OFFERED))
        assert result.is_error and result.images == ()
        assert await services.get(Looks).in_conversation(home, conversation) == []


def test_seen_survives_the_checkpoint_as_a_pair_of_strings() -> None:
    base = checkpoint()
    got = loads(dumps(replace(base, inbound=replace(base.inbound, seen=("cam", "rec")))))
    assert got.inbound.seen == ("cam", "rec")
    assert loads(dumps(base)).inbound.seen is None


class _Picture:
    """What the tool gives: a result carrying a picture."""

    def __init__(self, household: int, conversation: int, turn: int) -> None:
        pass

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, '{"picture": "follows in this result"}', images=(Image("image/png", b"png"),))


def test_the_first_step_is_asked_with_her_look_after_the_message_and_the_checkpoint_keeps_it(
        wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seen, "CameraTools", _Picture)
    wired.tools.specs = OFFERED
    wired.inference.script = [Reply(spoken="Someone is there.", text="Someone is there.")]
    asyncio.run(respond(seeing("cam", "rec")))
    entries = wired.inference.prompts[0].messages
    assert [type(e) for e in entries] == [Message, ToolCalls, ToolResults]
    results = entries[2]
    assert isinstance(results, ToolResults) and results.results[0].images == (Image("image/png", b"png"),)


@sync
async def test_a_turn_that_does_not_offer_the_tool_begins_without_the_look(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((RED,)))
        asked = replace(inbound(), household_id=home, seen=(PORCH, event.id))
        assert await seen.carried(asked, conversation, turn, START, ()) == START
        assert await services.get(Looks).in_conversation(home, conversation) == []
