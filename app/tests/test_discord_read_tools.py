"""Her read of the Discord channel a message came from (`tools.discord_read.DiscordReadTools` over the real
`HttpChannelPosts`, against a fake Discord REST API): offered only on a server-channel turn from a household member,
never on a DM, a stranger's message or another channel; it reads the turn's channel and no argument can name another;
its count is bounded; what it returns is outside words; no log line carries a message's text or the token."""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace

import httpx2
import pytest
from ashley import services
from ashley.channels.discord.route import decide
from ashley.channels.limits import load as load_limits, smallest_result_chars
from ashley.channels.model import DiscordServer, Inbound
from ashley.channels.turn_tools import sources
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.discord_posts import ChannelPosts
from ashley.tools.discord_posts_http import HttpChannelPosts
from ashley.tools.discord_read import DEFAULT_COUNT, MOST, RECENT, DiscordReadTools
from discord_support import ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, GUEST_ID, ME, SECRET, SIDE_CHANNEL, message

TOKEN = "zqx-bot-token-77"
RESULT_CHARS = smallest_result_chars(load_limits())
SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}


def post(n: int, channel: int, text: str = "") -> dict[str, object]:
    return {"id": str(1000 + n), "channel_id": str(channel), "content": text or f"line {n}",
            "timestamp": f"2026-11-01T10:{n % 60:02d}:00+00:00",
            "author": {"id": "7", "username": f"user{n}", "global_name": f"Name {n}" if n % 2 else None,
                       "bot": n == 3}}


class FakeDiscord:
    """Discord's `GET /channels/<id>/messages`: newest first, at most `limit`, for a channel it holds."""

    def __init__(self, channels: dict[int, list[dict[str, object]]], status: int = 200) -> None:
        self.channels, self.status = channels, status
        self.seen: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(request)
        found = re.fullmatch(r"/api/v10/channels/(\d+)/messages", request.url.path)
        if self.status != 200:
            return httpx2.Response(self.status)
        if found is None:
            return httpx2.Response(404)
        channel = int(found.group(1))
        if channel not in self.channels or request.headers.get("authorization") != f"Bot {TOKEN}":
            return httpx2.Response(403 if channel in self.channels else 404)
        limit = int(request.url.params.get("limit", "50"))
        return httpx2.Response(200, json=list(reversed(self.channels[channel]))[:limit])


def wired(discord: Callable[[httpx2.Request], httpx2.Response]) -> None:
    async def token() -> str:
        return TOKEN
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(discord))
    services.register(ChannelPosts, HttpChannelPosts(token, http))


def call(tools: DiscordReadTools, arguments: dict[str, object] | None = None, name: str = RECENT) -> ToolResult:
    return asyncio.run(tools.call(ToolCall("c", name, arguments or {})))


def many(n: int, channel: int = CHANNEL) -> FakeDiscord:
    return FakeDiscord({channel: [post(i, channel) for i in range(1, n + 1)], SIDE_CHANNEL: [post(99, SIDE_CHANNEL)]})


def inbound(**changes: object) -> Inbound | None:
    got = decide(message(**changes), ME, SERVERS, ALANA)
    return got if isinstance(got, Inbound) else None


def test_it_is_offered_on_a_server_channel_turn_of_a_member_and_nowhere_else() -> None:
    here = inbound()
    assert here is not None and here.discord_channel == CHANNEL
    assert "discord_read" in sources(here)
    assert "discord_read" not in sources(replace(here, discord_channel=None))
    dm = inbound(guild_id=None, channel_id=DM_CHANNEL)
    assert dm is not None and dm.discord_channel is None and "discord_read" not in sources(dm)
    stranger = decide(message(author_id=GUEST_ID), ME, SERVERS, None)
    assert isinstance(stranger, Inbound) and stranger.taint == "stranger" and "discord_read" not in sources(stranger)
    web = replace(here, channel="web", discord_channel=None, thread="person:1:web")
    assert "discord_read" not in sources(web)


def test_the_tool_reads_the_channel_it_was_built_for_and_that_alone() -> None:
    fake = many(5)
    wired(fake)
    tools = DiscordReadTools(SIDE_CHANNEL, RESULT_CHARS)
    got = json.loads(call(tools).content)
    assert [m["author"] for m in got["messages"]] == ["Name 99"]
    assert [r.url.path for r in fake.seen] == [f"/api/v10/channels/{SIDE_CHANNEL}/messages"]


@pytest.mark.parametrize("argument", [{"channel": "1001"}, {"channel_id": 1001}, {"count": 2, "guild": 900}])
def test_no_argument_can_point_it_at_another_channel(argument: dict[str, object]) -> None:
    fake = many(5)
    wired(fake)
    got = call(DiscordReadTools(SIDE_CHANNEL, RESULT_CHARS), argument)
    assert got.is_error and got.content.startswith("bad_arguments") and fake.seen == []


@pytest.mark.parametrize("count", [0, -1, MOST + 1, 500, "3", 2.5, True, None])
def test_a_count_outside_one_to_the_most_is_refused_before_discord_is_asked(count: object) -> None:
    fake = many(5)
    wired(fake)
    got = call(DiscordReadTools(CHANNEL, RESULT_CHARS), {"count": count})
    assert got.is_error and got.content.startswith("bad_arguments") and fake.seen == []


def test_it_asks_for_the_default_count_or_the_one_named_and_never_shows_more_than_asked() -> None:
    fake = many(MOST + 10)
    wired(fake)
    tools = DiscordReadTools(CHANNEL, 10**6)
    assert len(json.loads(call(tools).content)["messages"]) == DEFAULT_COUNT
    assert fake.seen[-1].url.params["limit"] == str(DEFAULT_COUNT)
    assert len(json.loads(call(tools, {"count": MOST}).content)["messages"]) == MOST
    assert len(json.loads(call(tools, {"count": 3}).content)["messages"]) == 3 and fake.seen[-1].url.params["limit"] == "3"


def test_a_server_that_returns_more_than_asked_is_still_cut_to_the_count_keeping_the_newest() -> None:
    def greedy(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[post(i, CHANNEL) for i in range(9, 0, -1)])
    wired(greedy)
    got = json.loads(call(DiscordReadTools(CHANNEL, 10**6), {"count": 2}).content)
    assert [m["text"] for m in got["messages"]] == ["line 8", "line 9"]


def test_messages_come_oldest_first_with_author_name_bot_flag_and_time() -> None:
    wired(many(4))
    got = json.loads(call(DiscordReadTools(CHANNEL, 10**6), {"count": 4}).content)
    assert [m["text"] for m in got["messages"]] == ["line 1", "line 2", "line 3", "line 4"]
    first, third = got["messages"][0], got["messages"][2]
    assert first["author"] == "Name 1" and first["bot"] is False and first["id"] == "1001"
    assert third["bot"] is True and got["messages"][1]["author"] == "user2"
    assert got["shown"] == 4 and got["fetched"] == 4


def test_a_result_too_long_for_the_loop_drops_the_oldest_and_says_how_many_it_shows() -> None:
    wired(FakeDiscord({CHANNEL: [post(i, CHANNEL, "x" * 400) for i in range(1, 31)]}))
    got = call(DiscordReadTools(CHANNEL, 2000), {"count": 30})
    body = json.loads(got.content)
    assert len(got.content) <= 2000 and 0 < body["shown"] < 30 and body["fetched"] == 30
    assert body["messages"][-1]["id"] == "1030"


def test_what_it_returns_is_outside_words_by_its_spec() -> None:
    tools = DiscordReadTools(CHANNEL, RESULT_CHARS)
    spec = asyncio.run(tools.catalogue()).specs[0]
    wired(many(2))
    got = call(tools)
    assert spec.name == RECENT and spec.reads and spec.outside is True
    assert got.taints(spec.outside) is True


@pytest.mark.parametrize(("status", "reason"), [(403, "refused"), (401, "refused"), (404, "not_found"),
                                                (429, "unreachable"), (500, "unreachable"), (418, "unexpected")])
def test_each_way_discord_refuses_comes_back_as_an_error_saying_what_to_do(status: int, reason: str) -> None:
    wired(FakeDiscord({}, status=status))
    got = call(DiscordReadTools(CHANNEL, RESULT_CHARS))
    assert got.is_error and got.content.startswith(reason + ":")


def test_an_unreachable_discord_and_a_missing_token_are_errors_not_crashes() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")
    wired(down)
    assert call(DiscordReadTools(CHANNEL, RESULT_CHARS)).content.startswith("unreachable:")

    async def none() -> str:
        return ""
    services.register(ChannelPosts, HttpChannelPosts(none, httpx2.AsyncClient(transport=httpx2.MockTransport(down))))
    assert call(DiscordReadTools(CHANNEL, RESULT_CHARS)).content.startswith("no_token:")


def test_another_tool_name_is_an_unknown_tool() -> None:
    wired(many(1))
    assert call(DiscordReadTools(CHANNEL, RESULT_CHARS), name="discord_send").content.startswith("unknown_tool")


def test_no_log_line_carries_a_message_s_text_or_the_token(caplog: pytest.LogCaptureFixture) -> None:
    wired(FakeDiscord({CHANNEL: [post(1, CHANNEL, SECRET)]}))
    with caplog.at_level(logging.DEBUG):
        got = call(DiscordReadTools(CHANNEL, RESULT_CHARS))
    assert SECRET in got.content
    lines = " ".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert "tools.call" in lines and SECRET not in lines and TOKEN not in lines
