"""`respond`, steps 1-4 and 6 of its docstring, against fakes in the locator: who the speaker is, the conversation and
the person turn (retried once on ConversationClosed), the persona's facts, the messages with speaker prefixes, the
delivered field stored and rendered, and a failed store of her turn not costing the reply."""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from ashley import logs
from ashley.channels.model import Medium, Outbound
from ashley.channels.respond import respond
from ashley.conversations.conversations import ConversationsUnavailable
from ashley.conversations.model import NewTurn
from ashley.inference.model import Message
from ashley.inference.reply import Reply
from conversations_support import events
from inference_support import settle
from turns_support import ALANA, HOUSE, HOUSEHOLD, SAM, SPEC, OTHER_SPEC, World, inbound, world as world

REPLY = Reply(spoken="Done, the lights are on.", text="Done: *lights on*.")


def test_a_named_speaker_is_the_participant_and_the_person_turns_speaker(world: World) -> None:
    out = settle(respond(inbound(text="hello", speaker_id=ALANA.id)))
    (call,) = world.conversations.thread_calls
    assert (call.household_id, call.thread, call.kind, set(call.participants)) == (HOUSE, "device:3", "command",
                                                                                  {ALANA.id})
    assert world.conversations.turns_of(out.conversation_id)[0] == ("person", ALANA.id, "hello")
    assert world.persona.asked[0][1].speaker == ALANA


@pytest.mark.parametrize("home", [frozenset({SAM.id}), frozenset({ALANA.id, SAM.id}), frozenset[int](), None])
def test_a_named_speaker_wins_over_presence(world: World, home: frozenset[int] | None) -> None:
    world.presence.answer = home
    settle(respond(inbound(speaker_id=ALANA.id, shared=True)))
    assert world.persona.asked[0][1].speaker == ALANA
    assert world.persona.asked[0][1].home == home


def test_on_a_shared_channel_the_one_person_home_is_the_speaker(world: World) -> None:
    world.presence.answer = frozenset({SAM.id})
    out = settle(respond(inbound(text="hi", shared=True)))
    assert set(world.conversations.thread_calls[0].participants) == {SAM.id}
    assert world.conversations.turns_of(out.conversation_id)[0] == ("person", SAM.id, "hi")
    assert world.persona.asked[0][1].speaker == SAM


@pytest.mark.parametrize("home", [frozenset({ALANA.id, SAM.id}), frozenset[int](), None])
def test_on_a_shared_channel_anything_but_exactly_one_home_is_unknown(world: World, home: frozenset[int] | None) -> None:
    world.presence.answer = home
    out = settle(respond(inbound(text="hi", shared=True)))
    assert tuple(world.conversations.thread_calls[0].participants) == ()
    assert world.conversations.turns_of(out.conversation_id)[0] == ("person", None, "hi")
    assert world.persona.asked[0][1].speaker is None
    assert world.persona.asked[0][1].home == home


def test_a_personal_channel_never_takes_its_speaker_from_presence(world: World) -> None:
    world.presence.answer = frozenset({SAM.id})
    out = settle(respond(inbound(text="hi", shared=False, place=None, audience="owner")))
    assert world.conversations.turns_of(out.conversation_id)[0] == ("person", None, "hi")
    assert world.persona.asked[0][1].speaker is None


def test_a_conversation_closing_between_the_two_calls_is_asked_for_once_more(world: World) -> None:
    world.conversations.closing = 1
    out = settle(respond(inbound(text="again", speaker_id=ALANA.id)))
    calls = world.conversations.thread_calls
    assert len(calls) == 2 and calls[0] == calls[1]
    first, second = (cid for cid, _ in world.conversations.added[:2])
    assert first != second and out.conversation_id == second
    assert world.conversations.turns_of(second) == [("person", ALANA.id, "again"), ("ashley", None, "The lights are on.")]
    assert world.conversations.turns_of(first) == []


def test_the_persona_is_asked_with_the_facts_of_this_moment(world: World) -> None:
    world.presence.answer = frozenset({ALANA.id, SAM.id})
    settle(respond(inbound(kind="chat", speaker_id=SAM.id, place="hallway")))
    ((kind, context),) = world.persona.asked
    assert kind == "chat"
    assert context.household == HOUSEHOLD
    assert context.home == frozenset({ALANA.id, SAM.id})
    assert context.place == "hallway"
    assert context.tool_instructions is not None
    assert context.tool_instructions.startswith("use the lights tool for lights\n\n")
    assert "remind" in context.tool_instructions and "cancel_reminder" not in context.tool_instructions
    assert context.tools_reachable is True
    local = datetime.now(ZoneInfo(HOUSEHOLD.timezone))
    assert context.now.tzinfo is not None
    assert context.now.utcoffset() == local.utcoffset()
    assert abs(context.now.astimezone(UTC) - datetime.now(UTC)) < timedelta(minutes=1)


def test_the_household_timezone_is_the_one_used(world: World) -> None:
    world.people.households[HOUSE] = replace(HOUSEHOLD, timezone="Asia/Kathmandu")   # +05:45, never a default
    settle(respond(inbound()))
    assert world.persona.asked[0][1].now.utcoffset() == timedelta(hours=5, minutes=45)


def test_tools_unavailable_means_no_tools_and_says_so(world: World) -> None:
    world.tools.on_offer = None
    out = settle(respond(inbound()))
    context = world.persona.asked[0][1]
    assert context.tools_reachable is False
    assert context.tool_instructions is None
    (asked,) = world.inference.asked
    assert asked.prompt.tools == ()
    assert out.body == "The lights are on."


def test_the_step_is_asked_with_the_persona_the_catalogue_and_reply(world: World) -> None:
    settle(respond(inbound(kind="brainstorm")))
    (asked,) = world.inference.asked
    assert asked.task == "brainstorm"
    assert asked.output is Reply
    assert asked.prompt.tool_choice == "auto"
    assert asked.prompt.tools == (SPEC, OTHER_SPEC)
    assert dict(asked.prompt.system) == dict(world.persona.prompts)


def test_messages_are_the_conversation_oldest_first_with_known_speakers_named(world: World) -> None:
    world.conversations.seed("device:3", "chat", [
        NewTurn("person", "is it raining", ALANA.id), NewTurn("ashley", "no"), NewTurn("person", "thanks", None),
        NewTurn("person", "and tomorrow", SAM.id)])
    settle(respond(inbound(text="what about friday", kind="chat", speaker_id=ALANA.id)))
    sent = world.inference.asked[0].prompt.messages
    earlier, last = [m for m in sent[:-1] if isinstance(m, Message)], sent[-1]
    assert len(earlier) == len(sent) - 1
    stripped = [(m.author, re.sub(r"^\(\w{3} \d{1,2} \w{3} \d{4} \d\d:\d\d\) ", "", m.text)) for m in earlier]
    assert stripped == [("person", "Alana: is it raining"), ("ashley", "no"), ("person", "thanks"),
                        ("person", "Sam: and tomorrow")]
    assert all(re.match(r"^\(\w{3} \d{1,2} \w{3} \d{4} \d\d:\d\d\) ", m.text) for m in earlier)
    assert last == Message("person", "Alana: what about friday")


def test_an_unknown_speakers_turn_has_no_prefix(world: World) -> None:
    settle(respond(inbound(text="who am i", shared=True)))
    assert world.inference.asked[0].prompt.messages == (Message("person", "who am i"),)


@pytest.mark.parametrize(("medium", "field"), [("spoken", "spoken"), ("text", "text")])
def test_her_turn_stores_the_delivered_field_and_the_body_renders_it(world: World, medium: Medium, field: str) -> None:
    world.inference.then = REPLY
    out = settle(respond(inbound(medium=medium)))
    delivered = REPLY.spoken if field == "spoken" else REPLY.text
    assert out == Outbound(out.conversation_id, medium, delivered)
    assert world.conversations.turns_of(out.conversation_id)[-1] == ("ashley", None, delivered)
    assert len(world.conversations.turns_of(out.conversation_id)) == 2


def test_a_failure_to_store_her_turn_is_logged_and_the_reply_still_delivered(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.conversations.ashley_error = ConversationsUnavailable("failover")
    world.inference.then = REPLY
    logs.setup()
    capsys.readouterr()
    out = settle(respond(inbound(medium="text", speaker_id=ALANA.id)))
    assert out.body == REPLY.text
    assert world.conversations.turns_of(out.conversation_id) == [("person", ALANA.id, "turn on the lights")]
    assert len(events(capsys.readouterr().out, "respond.turn_unrecorded")) == 1
