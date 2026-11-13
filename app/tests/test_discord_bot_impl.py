"""The Discord singleton end to end over fakes at its seams (the session, the claims, People, Devices, the turn loop):
a mapped DM is answered, a household channel only when she is addressed and as a reply, a repeated message once, a
failed turn with its fallback line, and nothing a message says reaches a log line."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs, services
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.client import Discord
from ashley.channels.discord.config import Config
from ashley.channels.discord.message import Message, snowflake_at
from ashley.channels.discord.seen import Seen
from ashley.channels.model import Device, DiscordServer, Inbound, Listed, Outbound, Satellite
from ashley.channels.respond import RespondUnavailable
from ashley.people.model import Account, Household, Person
from ashley.people.people import People

ME, ALANA, STRANGER, CHANNEL, DM, GUILD, OTHER = 900, 501, 502, 77, 88, 5, 79
NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SECRET = "PLANTED-CONTENT-zq"
CONFIG = Config(max_messages=2, catch_up_s=600, seen_retention_days=7, typing_refresh_s=0.01,
                token_poll_s=30, unavailable_text="later", refused_text="no", held_footer="Say yes.")
GENERAL = DiscordServer(Device(3, 1, "general", "discord", "household", "text", "chat"), GUILD, CHANNEL)


def message(n: int, channel: int, guild: int | None, author: int = ALANA, mentions: bool = False) -> Message:
    return Message(snowflake_at(NOW) + n, channel, guild, author, False, f"<@{ME}> {SECRET} {n}", mentions, False)


class FakeDiscord(Discord):
    def __init__(self, live: list[Message]) -> None:
        self.me = ME
        self.live = live
        self.sent: list[tuple[int, str, int | None]] = []
        self.histories: list[int] = []

    async def messages(self) -> AsyncIterator[Message]:
        for m in self.live:
            yield m

    async def send(self, channel_id: int, text: str, reply_to: int | None) -> None:
        self.sent.append((channel_id, text, reply_to))

    async def typing(self, channel_id: int) -> None:
        pass

    async def history(self, channel_id: int, after: int, limit: int = 50) -> list[Message]:
        self.histories.append(channel_id)
        return []


class MemorySeen(Seen):
    def __init__(self) -> None:
        self.claimed: dict[int, int] = {}

    async def claim(self, message_id: int, channel_id: int) -> bool:
        if message_id in self.claimed:
            return False
        self.claimed[message_id] = channel_id
        return True

    async def last(self, since: datetime) -> dict[int, int]:
        return {}

    async def prune(self, before: datetime) -> int:
        return 0

    async def settle(self, message_id: int) -> None:
        return None

    async def unsettled(self, since: datetime) -> dict[int, int]:
        return {}


class OnePerson(People):
    async def household(self, household_id: int) -> Household | None:
        return None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return Person(11, 1, "Alana") if (system, external_id) == ("discord", str(ALANA)) else None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class OneServer(Devices):
    """Answers each read with the next of `answers`, the last one repeating."""

    def __init__(self, answers: list[list[DiscordServer] | Exception] | None = None) -> None:
        self.answers = answers or [[GENERAL]]

    async def by_token(self, token: str) -> Device | None:
        return None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


def run(live: list[Message], down: bool = False,
        devices: OneServer | None = None) -> tuple[FakeDiscord, list[Inbound]]:
    services.register(People, OnePerson())
    services.register(Devices, devices or OneServer())
    discord = FakeDiscord(live)
    asked: list[Inbound] = []

    async def respond(inbound: Inbound) -> Outbound:
        asked.append(inbound)
        await asyncio.sleep(0.02)   # still thinking when the message stream ends
        if down:
            raise RespondUnavailable("down")
        return Outbound(40, "text", "hello")

    @asynccontextmanager
    async def connect() -> AsyncGenerator[Discord]:
        yield discord

    asyncio.run(Bot(connect, MemorySeen(), CONFIG, respond, lambda: NOW + timedelta(seconds=1)).run())
    return discord, asked


def test_a_mapped_dm_and_an_addressed_channel_message_are_answered_once(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    dm, mention = message(1, DM, None), message(2, CHANNEL, 5, mentions=True)
    discord, asked = run([dm, message(3, CHANNEL, 5), message(4, DM, None, STRANGER), mention, dm])
    assert sorted(discord.sent) == sorted([(DM, "hello", None), (CHANNEL, "hello", mention.id)])
    assert {(i.thread, i.audience, i.speaker_id, i.text) for i in asked} == {
        (f"discord:{DM}", "owner", 11, f"{SECRET} 1"), (f"discord:{CHANNEL}", "household", 11, f"{SECRET} 2")}
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "event=discord.unmapped" in out and "reason=not_addressed" in out and "event=discord.claimed_elsewhere" in out


def test_a_turn_that_cannot_be_made_posts_the_fallback_line() -> None:
    discord, _ = run([message(1, DM, None)], down=True)
    assert discord.sent == [(DM, "later", None)]


def test_when_the_session_ends_the_replies_in_flight_are_still_sent(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    discord, _ = run([message(1, DM, None)])
    assert discord.sent == [(DM, "hello", None)], "the message stream ended while she was thinking"
    out = capsys.readouterr().out
    assert out.index("event=discord.replied") < out.index("event=discord.disconnected reason=ended")


def test_a_channel_registered_after_the_start_is_answered() -> None:
    mention = message(1, CHANNEL, 5, mentions=True)
    discord, _ = run([mention], devices=OneServer([[], [GENERAL]]))
    assert discord.sent == [(CHANNEL, "hello", mention.id)]


def test_a_guild_message_is_dropped_unclaimed_when_devices_cannot_be_read(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    mention = message(1, CHANNEL, 5, mentions=True)
    discord, asked = run([mention, mention], devices=OneServer([[GENERAL], DevicesUnavailable("down"), [GENERAL]]))
    assert (discord.sent, len(asked)) == ([(CHANNEL, "hello", mention.id)], 1), "the second sight still answers it"
    assert "reason=devices_unavailable" in capsys.readouterr().out


def test_she_answers_in_any_channel_of_a_household_server_and_no_other(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    elsewhere, stranger_server = message(1, OTHER, GUILD, mentions=True), message(2, OTHER + 1, GUILD + 1, mentions=True)
    discord, asked = run([elsewhere, stranger_server])
    assert discord.sent == [(OTHER, "hello", elsewhere.id)]
    assert [i.thread for i in asked] == [f"discord:{OTHER}"], "each channel is its own thread"
    assert discord.histories == [CHANNEL], "catch-up covers the home channel"
    assert "reason=unknown_server" in capsys.readouterr().out
