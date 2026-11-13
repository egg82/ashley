"""A wake rule that names a speaker: the rule's field is checked by shape; the runner uses the speaker only when the
household's house lists it as a media player (else the phone, and a house that cannot be read leaves the wake due);
the turn then runs on the speaker's thread, queued in the outbox, and the satellites singleton plays its clip through
Home Assistant, falling back to the phone when it cannot. House, clips and player are fakes; the rest is real."""

import json

import pytest
from ashley import services
from ashley.channels.model import Device, Listed, Satellite
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later, Outbox
from ashley.channels.voice.clips import ClipsUnavailable
from ashley.channels.voice.later import say
from ashley.channels.wake import speaker
from ashley.home_assistant.homes import Homes
from ashley.workshop.wake_rule import WakeRule, rule_of
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import World
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from later_support import FakeClips, clips as clips
from voice_support import FakeConnection, FakeSpeaker, FakeTurnLoop, pipeline
from wb_runner_support import DONE, GREET, stack, sweep
from wb_support import add_device

KITCHEN = "media_player.zq_kitchen"
URL = "https://ashley.test/api/voice/clips/tok-1"
BASE = {"event": "arrived", "brief": GREET, "tools": ["lamp_on"]}


def body(**extra: object) -> str:
    return json.dumps({**BASE, **extra})


@pytest.mark.parametrize("given", [KITCHEN, "media_player.a1"])
def test_a_rule_may_name_a_media_player(given: str) -> None:
    rule = rule_of(body(speaker=given))
    assert isinstance(rule, WakeRule) and rule.speaker == given


@pytest.mark.parametrize("given", ["light.zq_lamp", "media_player.", "media_player.Kitchen", "kitchen", "", None, 3,
                                   ["media_player.zq_kitchen"], "media_player.zq_kitchen "])
def test_a_speaker_that_is_not_a_media_player_entity_id_makes_no_rule(given: object) -> None:
    assert rule_of(body(speaker=given)) is None


def test_a_rule_without_a_speaker_has_none_and_a_speaker_adds_no_specificity() -> None:
    plain, named = rule_of(body()), rule_of(body(speaker=KITCHEN))
    assert plain is not None and named is not None and plain.speaker is None
    assert named.specificity == plain.specificity == 0
    assert named.answers("arrived", "person.alana", None)


def test_the_thread_names_the_person_and_the_entity_and_nothing_else_parses() -> None:
    assert speaker.parsed(speaker.thread(7, KITCHEN)) == (7, KITCHEN)
    for other in ("device:3", "device:speaker:", "device:speaker:x:media_player.a", "device:speaker:7:", "push:7"):
        assert speaker.parsed(other) is None


def house(world: World, *things: str, up: bool = True) -> MemoryHouse:
    made = MemoryHouse(things=[state(t, t, "idle") for t in things], down=not up)
    services.register(Homes, AnyHousehold(made))
    return made


def listing(world: World) -> dict[int, list[Listed]]:
    household = world.who.household_id
    return {household: [Listed(Device(add_device(world.url, household, "zq-ha", "ha", house=True), household, "ha",
                                      "house", "present", "text", "chat"), "house")]}


def threads(world: World) -> list[str]:
    got = scalar(world.url, "SELECT coalesce(json_agg(ct.thread ORDER BY t.id), '[]') FROM turns t "
                            "JOIN conversation_threads ct ON ct.conversation_id = t.conversation_id "
                            "WHERE t.author = 'ashley' AND NOT t.follows")
    return list(got)


def queued_threads(world: World) -> list[str]:
    return list(scalar(world.url, "SELECT coalesce(json_agg(thread ORDER BY id), '[]') FROM outbox"))


def test_a_wake_whose_rule_names_a_listed_speaker_runs_on_it_and_the_clip_plays_there(
        world: World, clips: FakeClips) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    house(world, KITCHEN, "light.zq_lamp")

    async def go() -> None:
        rows = listing(world)
        async with stack(world, rows=rows) as s:
            await s.rule(body=body(speaker=KITCHEN, greets=False))
            wake = await s.hand_in()
            await sweep()
            assert s.outcome(wake) == "turn"
            mine = speaker.thread(world.who.id, KITCHEN)
            assert threads(world) == [mine] and queued_threads(world) == [mine]
            assert "said aloud on a speaker" in str(world.first.inference.prompts[0])
            (waiting,) = await services.get(Outbox).take("device:")
            player = FakeSpeaker()
            await say(waiting, {}, pipeline(FakeTurnLoop(), player))
            assert player.played == [(KITCHEN, URL)] and player.households == [world.who.household_id]
            assert [c[1] for c in clips.added] == ["Welcome home."]
            assert clips.added[0][0] == rows[world.who.household_id][0].device.id
            assert queued_threads(world) == []

    run(go())


@pytest.mark.parametrize("things", [(), ("media_player.zq_other",)])
def test_a_speaker_the_house_does_not_list_as_a_media_player_leaves_the_turn_on_the_phone(
        world: World, things: tuple[str, ...]) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    house(world, *things)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule(body=body(speaker=KITCHEN))
            wake = await s.hand_in()
            await sweep()
            assert s.outcome(wake) == "turn"
            assert threads(world) == [f"push:{world.who.id}"] == queued_threads(world)

    run(go())


def test_a_house_that_cannot_be_read_leaves_the_wake_due_and_a_later_sweep_runs_it_on_the_speaker(
        world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    made = house(world, KITCHEN, up=False)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule(body=body(speaker=KITCHEN))
            wake = await s.hand_in()
            await sweep()
            assert s.outcome(wake) is None and s.turns_of(wake) == 0
            made.down = False
            await sweep()
            assert s.outcome(wake) == "turn" and queued_threads(world) == [speaker.thread(world.who.id, KITCHEN)]

    run(go())


def test_a_rule_without_a_speaker_never_asks_the_house(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    made = house(world, KITCHEN)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.hand_in()
            await sweep()
            assert made.reads == 0 and queued_threads(world) == [f"push:{world.who.id}"]

    run(go())


def test_a_named_speaker_wins_over_the_satellite_of_the_place_the_wake_names(world: World, clips: FakeClips) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)
    house(world, KITCHEN)

    async def go() -> None:
        rows = listing(world)
        household = world.who.household_id
        echo = Device(add_device(world.url, household, "zq-echo", "echo"), household, "echo", "Back Hall", "present",
                      "spoken", "command")
        rows[household].append(Listed(echo, "satellite"))
        async with stack(world, rows=rows) as s:
            await s.rule(body=body(speaker=KITCHEN, greets=True))
            wake = await s.hand_in(what="back_hall")
            await sweep()
            assert s.outcome(wake) == "turn"
            assert threads(world) == [speaker.thread(world.who.id, KITCHEN)]
            assert scalar(world.url, "SELECT route FROM wakes WHERE id = %s", (wake,)) == "phone"

    run(go())


def waiting_for(world: World, thread: str) -> Later:
    conversation = int(scalar(world.url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') "
                                         "RETURNING id", (world.who.household_id,)))
    return Later(1, world.who.household_id, thread, Outbound(conversation, "spoken", "Welcome home."), 2500)


@pytest.mark.parametrize("refuses", ["player", "clips", "no_player", "no_house"])
def test_a_reply_that_cannot_be_played_is_queued_for_the_persons_phone(
        world: World, clips: FakeClips, refuses: str) -> None:
    async def go() -> None:
        async with stack(world, rows={} if refuses == "no_house" else listing(world)):
            if refuses == "clips":
                clips.error = ClipsUnavailable("down")
            player = None if refuses == "no_player" else FakeSpeaker(accepts=refuses != "player")
            await say(waiting_for(world, speaker.thread(world.who.id, KITCHEN)), {}, pipeline(FakeTurnLoop(), player))
            assert queued_threads(world) == [f"push:{world.who.id}"]
            assert scalar(world.url, "SELECT body FROM outbox") == "Welcome home."

    run(go())


def test_a_reply_played_is_not_also_sent_to_the_phone(world: World, clips: FakeClips) -> None:
    async def go() -> None:
        async with stack(world, rows=listing(world)):
            await say(waiting_for(world, speaker.thread(world.who.id, KITCHEN)), {},
                      pipeline(FakeTurnLoop(), FakeSpeaker()))
            assert queued_threads(world) == []

    run(go())


def test_a_satellite_thread_is_still_said_on_its_own_connection(clips: FakeClips) -> None:
    conn = FakeConnection()
    sat = Satellite(Device(3, 1, "echo", "office", "present", "spoken", "command"), "10.0.0.9", None)

    async def go() -> None:
        await say(Later(1, 1, "device:3", Outbound(41, "spoken", "Welcome home."), 2500), {3: (sat, conn)},
                  pipeline(FakeTurnLoop()))

    run(go())
    assert conn.announced == [URL]
