"""When she tends her home channel (`initiative.tend`, `channels.discord.home`): once per server and slot of time, a
seeded roll first and then a score from the slot's facts, measured from the messages sent before the slot began; never
when a fact is unknown, at night, or soon after her own last message there. An allowed slot is one turn of hers, the
household's, on the home channel's thread, with the slot as its source; the Discord singleton's session runs it."""

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import virtual_time
from ashley import logs, services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.discord import home
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.config import load as load_config
from ashley.channels.model import Device, DiscordServer, Inbound, Outbound
from ashley.channels.respond import RespondUnavailable
from ashley.initiative.initiative import Initiative, Scored
from ashley.initiative.tend import FILE, RATES, Rates, Tending, load, rolls, score, verdict
from ashley.initiative.weights import parse
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.tools.discord_home_tools import NAMES
from ashley.tools.discord_posts import ChannelPosts, Post, PostsFailed
from discord_support import CHANNEL, FAMILY, GUILD, ME, NOW, OTHER_CHANNEL, OTHER_GUILD, SECRET, FakeConnect
from discord_support import FakeDevices, FakeDiscord, FakeSeen, snowflake
from initiative_support import weights as weights_json

SERVER = DiscordServer(FAMILY, GUILD, CHANNEL)
SECOND = DiscordServer(Device(8, 2, "their room", "den", "household", "text", "chat"), OTHER_GUILD, OTHER_CHANNEL)
WEIGHTS = parse(weights_json(night={"weight": 0.0, "from_hour": 22, "to_hour": 7}))
SLOT = int(NOW.timestamp() // RATES.slot_s)
BEGUN = datetime.fromtimestamp(SLOT * RATES.slot_s, UTC)
H = 3600.0


def rates(**changed: Any) -> Rates:
    return replace(RATES, **{"chance": 1.0, **changed})


def facts(**changed: Any) -> Tending:
    return replace(Tending("7:1", 12, True, 30 * H, 10), **changed)


def written(tmp_path: Path, **changed: Any) -> Path:
    raw = {**json.loads(FILE.read_text()), **changed}
    path = tmp_path / "tend.json"
    path.write_text(json.dumps(raw))
    return path


def test_the_shipped_rates_load(tmp_path: Path) -> None:
    assert load() == RATES and load(written(tmp_path)) == RATES and 0 < RATES.chance < 1


@pytest.mark.parametrize("changed", [{"chance": 1.5}, {"chance": True}, {"read_count": 101}, {"read_count": 0},
                                     {"slot_s": 0}, {"quiet": {"weight": 0.6}}, {"activity": {"weight": 1, "full_at": 2.5}},
                                     {"extra": 1}])
def test_rates_out_of_shape_are_refused(tmp_path: Path, changed: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        load(written(tmp_path, **changed))


def test_a_missing_key_is_refused(tmp_path: Path) -> None:
    raw = json.loads(FILE.read_text())
    del raw["min_gap_h"]
    (tmp_path / "t.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load(tmp_path / "t.json")


def test_the_roll_is_fixed_by_its_seed_and_falls_in_at_about_the_chance() -> None:
    seeds = [f"7:{n}" for n in range(4000)]
    hits = [rolls(s, RATES) for s in seeds]
    assert hits == [rolls(s, RATES) for s in seeds]
    assert abs(sum(hits) / len(hits) - RATES.chance) < 0.03
    assert not any(rolls(s, rates(chance=0.0)) for s in seeds[:200])


@pytest.mark.parametrize(("changed", "expected"), [
    ({}, "allowed"),
    ({"hour": None}, "unknown"),
    ({"known": False}, "unknown"),
    ({"hour": 23}, "night"),
    ({"since_mine_s": RATES.min_gap_h * H - 1}, "recent"),
    ({"since_mine_s": RATES.min_gap_h * H, "people_since": 0}, "low"),
    ({"since_mine_s": None, "people_since": 0}, "allowed"),
])
def test_a_slot_that_rolled_in_is_decided_by_its_facts(changed: dict[str, Any], expected: str) -> None:
    night = parse(weights_json())
    assert verdict(facts(**changed), rates(), night) == expected


def test_a_slot_the_roll_misses_is_rolled_out_whatever_its_facts() -> None:
    assert verdict(facts(), rates(chance=0.0), WEIGHTS) == "rolled_out"


def test_the_score_rises_with_quiet_and_with_people_talking_each_up_to_its_share() -> None:
    r = rates()
    assert score(facts(since_mine_s=None, people_since=0), r) == pytest.approx(r.quiet_weight)
    assert score(facts(since_mine_s=r.quiet_full_at_h * H * 5, people_since=999), r) == pytest.approx(
        r.quiet_weight + r.activity_weight)
    half = facts(since_mine_s=r.quiet_full_at_h * H / 2, people_since=r.activity_full_at // 2)
    assert score(half, r) == pytest.approx(r.quiet_weight / 2 + r.activity_weight * (r.activity_full_at // 2)
                                           / r.activity_full_at)


class Posts(ChannelPosts):
    def __init__(self, posts: list[Post] | Exception) -> None:
        self.posts = posts
        self.asked: list[tuple[int, int]] = []

    async def recent(self, channel_id: int, count: int) -> list[Post]:
        self.asked.append((channel_id, count))
        if isinstance(self.posts, Exception):
            raise self.posts
        return self.posts


class Zoned(People):
    async def household(self, household_id: int) -> Household | None:
        return Household(household_id, "home", "UTC", "", ())

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


def post(at: datetime, author: int, bot: bool = False, n: int = 0) -> Post:
    return Post(snowflake(at, n), author, "someone", bot, at.isoformat(), SECRET)


def test_the_facts_are_measured_from_what_was_sent_before_the_slot_began() -> None:
    services.register(People, Zoned())
    services.register(ChannelPosts, Posts([
        post(BEGUN - timedelta(hours=30), ME), post(BEGUN - timedelta(hours=26), ME, True),
        post(BEGUN - timedelta(hours=25), 11), post(BEGUN - timedelta(hours=3), 3, bot=True),
        post(BEGUN - timedelta(hours=2), 12), post(BEGUN - timedelta(hours=1), 13),
        post(BEGUN + timedelta(minutes=5), ME), post(BEGUN + timedelta(minutes=6), 14)]))
    got = asyncio.run(home.gathered(SERVER, "7:1", ME, BEGUN))
    assert got == Tending("7:1", BEGUN.hour, True, 26 * H, 3), "people after her last, bots not counted"


def test_with_none_of_hers_read_every_persons_message_counts_and_an_unreadable_channel_is_unknown() -> None:
    services.register(People, Zoned())
    services.register(ChannelPosts, Posts([post(BEGUN - timedelta(hours=h), 11) for h in (3, 2)]))
    assert asyncio.run(home.gathered(SERVER, "7:1", ME, BEGUN)) == Tending("7:1", BEGUN.hour, True, None, 2)
    services.register(ChannelPosts, Posts(PostsFailed("refused")))
    assert asyncio.run(home.gathered(SERVER, "7:1", ME, BEGUN)).known is False
    services.unregister(People)
    assert asyncio.run(home.gathered(SERVER, "7:1", ME, BEGUN)).hour is None


class Started:
    def __init__(self) -> None:
        self.turns: list[Coroutine[Any, Any, None]] = []

    def __call__(self, turn: Coroutine[Any, Any, None]) -> None:
        self.turns.append(turn)

    def run(self) -> None:
        for turn in self.turns:
            asyncio.run(turn)
        self.turns = []

    def close(self) -> None:
        for turn in self.turns:
            turn.close()


def allowing(**changed: Any) -> None:
    services.register(Initiative, Scored(WEIGHTS, tending=rates(**changed)))
    services.register(People, Zoned())
    services.register(ChannelPosts, Posts([post(BEGUN - timedelta(days=5), ME)]))


def test_each_servers_slot_is_decided_once_and_an_allowed_one_is_her_turn_on_its_home_channel() -> None:
    allowing()
    services.register(Devices, FakeDevices([SERVER, SECOND]))
    asked: list[Inbound] = []

    async def respond(inbound: Inbound) -> Outbound:
        asked.append(inbound)
        return Outbound(9, "text", "hello", says="none")
    started, done = Started(), set[str]()
    asyncio.run(home.check(ME, started, respond, NOW, done, rates()))
    asyncio.run(home.check(ME, started, respond, NOW + timedelta(seconds=RATES.slot_s - 1), done, rates()))
    assert len(started.turns) == 2, "one per server, and the same slot again starts nothing"
    started.run()
    assert [(i.thread, i.home_channel, i.source) for i in asked] == [
        (f"discord:{CHANNEL}", CHANNEL, f"discord-home:{FAMILY.id}:{SLOT}"),
        (f"discord:{OTHER_CHANNEL}", OTHER_CHANNEL, f"discord-home:8:{SLOT}")]
    turn = asked[0]
    assert (turn.unprompted, turn.author, turn.speaker_id, turn.tools_only, turn.later_by, turn.taint) == (
        True, "household", None, NAMES, "outbox", None)
    asyncio.run(home.check(ME, started, respond, NOW + timedelta(seconds=RATES.slot_s), done, rates()))
    assert len(started.turns) == 2, "the next slot is decided afresh"
    started.close()
    assert done == {f"{FAMILY.id}:{SLOT + 1}", f"8:{SLOT + 1}"}, "only the current slot is kept"


def test_a_slot_not_allowed_starts_nothing_and_a_roll_that_misses_reads_nothing() -> None:
    allowing(min_gap_h=24 * 6)
    services.register(Devices, FakeDevices([SERVER]))
    started = Started()
    asyncio.run(home.check(ME, started, _never, NOW, set(), rates(min_gap_h=24 * 6)))
    assert started.turns == []
    posts = Posts([])
    services.register(ChannelPosts, posts)
    services.register(Initiative, Scored(WEIGHTS, tending=rates(chance=0.0)))
    asyncio.run(home.check(ME, started, _never, NOW, set(), rates(chance=0.0)))
    assert started.turns == [] and posts.asked == []


def test_servers_that_cannot_be_read_decide_nothing_until_they_can() -> None:
    allowing()
    devices = FakeDevices([SERVER])
    devices.error = DevicesUnavailable("down")
    services.register(Devices, devices)
    started, done = Started(), set[str]()
    asyncio.run(home.check(ME, started, _never, NOW, done, rates()))
    assert (started.turns, done) == ([], set())
    devices.error = None
    asyncio.run(home.check(ME, started, _never, NOW, done, rates()))
    assert len(started.turns) == 1
    started.close()


async def _never(inbound: Inbound) -> Outbound:
    raise AssertionError("no turn runs")


def test_a_turn_that_cannot_be_made_is_logged_and_never_raises(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    allowing()
    services.register(Devices, FakeDevices([SERVER]))

    async def down(inbound: Inbound) -> Outbound:
        raise RespondUnavailable("down")
    started = Started()
    asyncio.run(home.check(ME, started, down, NOW, set(), rates()))
    assert len(started.turns) == 1
    started.run()
    assert "reason=tend_turn" in capsys.readouterr().out


def test_the_discord_session_tends_while_it_is_open(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    services.register(Initiative, Scored(WEIGHTS, tending=rates()))
    services.register(People, Zoned())
    services.register(Devices, FakeDevices([SERVER]))
    services.register(ChannelPosts, Posts([post(NOW - timedelta(days=5), ME)]))
    discord, asked = FakeDiscord(), list[Inbound]()

    async def respond(inbound: Inbound) -> Outbound:
        asked.append(inbound)
        return Outbound(9, "text", "hello", says="none")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()

        def clock() -> datetime:
            return NOW + timedelta(seconds=loop.time())
        session = asyncio.create_task(Bot(FakeConnect(discord), FakeSeen(lambda: NOW), load_config(), respond,
                                          clock).run())
        await asyncio.sleep(RATES.check_every_s + 1)
        discord.incoming.put_nowait(None)
        await session
    virtual_time.run(scenario(), limit=RATES.check_every_s * 3)
    assert [i.home_channel for i in asked] == [CHANNEL]
    out = capsys.readouterr().out
    assert "discord.tend " in out and "verdict=allowed" in out and SECRET not in out
