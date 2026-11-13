"""Her tools for her home channel (`tools.discord_home_tools.HomeTools` over the real `HttpHomeChannel`, against a fake
Discord REST API): offered on her turn of tending it and never on a reply to anyone, on any channel, `#ashley` included;
each acts on the channel it was built with and no argument names another; she pins and unpins only her own messages;
nothing they return is outside words; no log line carries the token, a topic or a message's text."""

import asyncio
import json
import logging
import re
from dataclasses import replace

import httpx2
import pytest
from ashley import services
from ashley.channels.discord.home import inbound as tending
from ashley.channels.discord.route import decide
from ashley.channels.model import DiscordServer, Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.discord_home import HomeChannel
from ashley.tools.discord_home_http import HttpHomeChannel
from ashley.tools.discord_home_tools import MINE, NAMES, PIN, TOPIC, HomeTools
from ashley.tools.tools import Catalogue, Tools
from discord_support import ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, ME, SECRET, SIDE_CHANNEL, message

TOKEN = "zqx-home-token-31"
SERVER = DiscordServer(FAMILY, GUILD, CHANNEL)
SERVERS = {GUILD: SERVER}
OTHER_USER = 9191


def msg(n: int, author: int, text: str = "", channel: int = CHANNEL) -> dict[str, object]:
    """A message as Discord's REST API returns it, with the sibling keys a real one carries."""
    return {"id": str(5000 + n), "channel_id": str(channel), "content": text or f"line {n}", "type": 0,
            "timestamp": f"2026-11-01T10:{n % 60:02d}:00+00:00", "pinned": False, "mentions": [], "tts": False,
            "author": {"id": str(author), "username": f"user{author}", "global_name": None, "bot": author == ME}}


class FakeRest:
    """Discord's REST API for the endpoints the port uses, over channels it holds; `seen` is every request."""

    def __init__(self, channels: dict[int, list[dict[str, object]]], pins: dict[int, list[int]] | None = None,
                 status: int | None = None) -> None:
        self.channels, self.pins, self.status = channels, pins or {}, status
        self.topics: dict[int, str] = {}
        self.seen: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(request)
        if request.headers.get("authorization") != f"Bot {TOKEN}":
            return httpx2.Response(401)
        path, method = request.url.path.removeprefix("/api/v10"), request.method
        if path == "/users/@me":
            return httpx2.Response(200, json={"id": str(ME), "username": "her", "bot": True})
        if self.status is not None:
            return httpx2.Response(self.status, json={"message": "no", "code": 50013})
        found = re.fullmatch(r"/channels/(\d+)(/messages|/pins)?(?:/(\d+))?", path)
        if found is None or int(found.group(1)) not in self.channels:
            return httpx2.Response(404, json={"message": "Unknown Channel", "code": 10003})
        channel, part, one = int(found.group(1)), found.group(2), found.group(3)
        held = self.channels[channel]
        if part is None and method == "PATCH":
            self.topics[channel] = json.loads(request.content)["topic"]
            return httpx2.Response(200, json={"id": str(channel), "topic": self.topics[channel]})
        if part == "/messages" and one is None:
            return httpx2.Response(200, json=list(reversed(held))[:int(request.url.params["limit"])])
        if part == "/messages":
            hit = [m for m in held if m["id"] == one]
            return httpx2.Response(200, json=hit[0]) if hit else httpx2.Response(404, json={"code": 10008})
        if part == "/pins" and one is None:
            return httpx2.Response(200, json=[m for m in held if int(str(m["id"])) in self.pins.get(channel, [])])
        if part == "/pins" and method in ("PUT", "DELETE"):
            pinned = self.pins.setdefault(channel, [])
            if method == "PUT":
                pinned.append(int(one))
            elif int(one) in pinned:
                pinned.remove(int(one))
            return httpx2.Response(204)
        return httpx2.Response(405)

    def changes(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.seen if r.method in ("PATCH", "PUT", "DELETE")]


def home_channel() -> list[dict[str, object]]:
    return [msg(1, ME, "her old pinned line"), *[msg(n, OTHER_USER if n % 2 else ME) for n in range(2, 80)],
            msg(80, OTHER_USER, SECRET)]


def wired(rest: FakeRest) -> None:
    async def token() -> str:
        return TOKEN
    services.register(HomeChannel, HttpHomeChannel(token, httpx2.AsyncClient(transport=httpx2.MockTransport(rest))))


def call(name: str, arguments: dict[str, object] | None = None, channel: int = CHANNEL) -> ToolResult:
    return asyncio.run(HomeTools(channel).call(ToolCall("c", name, arguments or {})))


class Everyday(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("look_up", "look up", {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "done")


def offered(inbound: Inbound) -> set[str]:
    services.register(Tools, Everyday())
    return {s.name for s in asyncio.run(for_turn(inbound).catalogue()).specs}


def replies() -> list[Inbound]:
    """Every turn the Discord adapter hands in for someone's message: a mention and a reply in her home channel, by a
    member and by a stranger, a mention in another channel, and a DM."""
    found = [decide(message(), ME, SERVERS, ALANA),
             decide(message(mentions_me=False, replies_to_me=True), ME, SERVERS, ALANA),
             decide(message(author_id=31337), ME, SERVERS, None),
             decide(message(channel_id=SIDE_CHANNEL), ME, SERVERS, ALANA),
             decide(message(channel_id=DM_CHANNEL, guild_id=None), ME, {}, ALANA)]
    turns = [t for t in found if isinstance(t, Inbound)]
    assert len(turns) == len(found), "every message here is one she answers"
    return turns


def test_her_tending_turn_offers_the_home_tools_and_only_them() -> None:
    turn = tending(SERVER, f"{FAMILY.id}:1")
    assert turn.home_channel == CHANNEL and turn.thread == f"discord:{CHANNEL}"
    assert offered(turn) == set(NAMES)


def test_no_reply_to_anyone_is_offered_them_on_any_channel() -> None:
    turns = replies()
    assert {t.thread for t in turns} >= {f"discord:{CHANNEL}", f"discord:{SIDE_CHANNEL}"}
    for turn in turns:
        assert turn.home_channel is None
        assert not set(NAMES) & offered(turn)


def test_even_a_reply_carrying_the_home_channel_is_never_offered_them() -> None:
    for turn in replies():
        assert not set(NAMES) & offered(replace(turn, home_channel=CHANNEL))
        remark_shaped = replace(turn, home_channel=CHANNEL, unprompted=True)
        assert not set(NAMES) & offered(remark_shaped), "a remark on someone's message is not her own initiative"
    tend = tending(SERVER, "7:1")
    assert not set(NAMES) & offered(replace(tend, unprompted=False)), "a turn someone waits on is a reply"
    assert not set(NAMES) & offered(replace(tend, author="person")), "a person's message is never her own initiative"


def test_home_mine_lists_her_own_messages_with_her_pins_and_nobody_elses() -> None:
    rest = FakeRest({CHANNEL: home_channel()}, {CHANNEL: [5001, 5003]})
    wired(rest)
    got = call(MINE)
    body = json.loads(got.content)["messages"]
    assert not got.is_error and got.outside is None
    assert body[0] == {"id": "5001", "at": "2026-11-01T10:01:00+00:00", "text": "her old pinned line", "pinned": True}
    assert [m["id"] for m in body] == ["5001"] + [str(5000 + n) for n in range(32, 80, 2)], "hers among the latest 50"
    assert [m["pinned"] for m in body[:1]] == [True] and not any(m["pinned"] for m in body[1:])
    assert SECRET not in got.content and '"5003"' not in got.content, "someone else's message, pinned or not, is not hers"


def test_home_topic_sets_the_topic_of_the_channel_it_was_built_with_and_no_other() -> None:
    rest = FakeRest({CHANNEL: home_channel(), SIDE_CHANNEL: []})
    wired(rest)
    assert not call(TOPIC, {"topic": "plants and puns"}).is_error
    assert rest.topics == {CHANNEL: "plants and puns"}
    named = call(TOPIC, {"topic": "x", "channel": str(SIDE_CHANNEL)})
    assert named.is_error and named.content.startswith("bad_arguments")
    assert call(TOPIC, {"topic": "y" * 1025}).is_error
    assert rest.changes() == [("PATCH", f"/api/v10/channels/{CHANNEL}")]


def test_home_pin_pins_and_unpins_only_her_own_message_in_her_channel() -> None:
    rest = FakeRest({CHANNEL: home_channel()})
    wired(rest)
    assert not call(PIN, {"message": "5002", "pinned": True}).is_error
    assert rest.pins == {CHANNEL: [5002]}
    assert not call(PIN, {"message": "5002", "pinned": False}).is_error
    theirs = call(PIN, {"message": "5003", "pinned": True})
    assert theirs.is_error and theirs.content.startswith("not_hers")
    assert call(PIN, {"message": "5004", "pinned": True, "channel": str(SIDE_CHANNEL)}).is_error
    assert call(PIN, {"message": "-1", "pinned": True}).is_error and call(PIN, {"message": "5004"}).is_error
    assert rest.changes() == [("PUT", f"/api/v10/channels/{CHANNEL}/pins/5002"),
                              ("DELETE", f"/api/v10/channels/{CHANNEL}/pins/5002")]


@pytest.mark.parametrize(("status", "reason"), [(403, "refused"), (404, "not_found"), (429, "unreachable"),
                                                (400, "unexpected")])
def test_discord_refusing_is_an_error_naming_why(status: int, reason: str) -> None:
    wired(FakeRest({CHANNEL: home_channel()}, status=status))
    tried: list[tuple[str, dict[str, object]]] = [(MINE, {}), (TOPIC, {"topic": "t"}),
                                                  (PIN, {"message": "5002", "pinned": True})]
    for name, arguments in tried:
        got = call(name, arguments)
        assert got.is_error and got.content.startswith(f"{reason}:"), name


def test_with_no_token_nothing_is_asked_of_discord() -> None:
    rest = FakeRest({CHANNEL: home_channel()})

    async def none() -> str:
        return ""
    services.register(HomeChannel, HttpHomeChannel(none, httpx2.AsyncClient(transport=httpx2.MockTransport(rest))))
    assert call(MINE).content.startswith("no_token") and rest.seen == []


def test_no_log_line_carries_the_token_a_topic_or_a_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    wired(FakeRest({CHANNEL: home_channel()}))
    call(MINE)
    call(TOPIC, {"topic": SECRET + "-topic"})
    call(PIN, {"message": "5002", "pinned": True})
    assert caplog.records, "the calls were logged"
    assert not [r for r in caplog.records if TOKEN in r.getMessage() or SECRET in r.getMessage()]


def test_every_tool_says_it_carries_no_outside_words() -> None:
    specs = asyncio.run(HomeTools(CHANNEL).catalogue()).specs
    assert {s.name for s in specs} == set(NAMES) and not any(s.outside for s in specs)
    assert [s.name for s in specs if s.reads] == [MINE]
