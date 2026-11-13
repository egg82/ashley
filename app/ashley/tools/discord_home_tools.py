"""Her tools for her home channel on the household's Discord server, offered only on a turn of her own initiative there
(`ashley.channels.turn_tools.for_turn`, from `Inbound.home_channel`), never on a reply to anyone. Each acts on the
channel it was built with and no argument names another: `home_mine` reads her own messages there, `home_topic` sets
its topic, `home_pin` pins or unpins one of her messages. What she posts there is her reply on that turn, through the
outbox, so no tool posts. Nothing a tool returns was written by anyone but her (`outside` false). Topic text and
messages are never logged; `tools.call` carries the outcome and counts."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from . import bench_results
from .bench_args import BadArguments, check_names
from .discord_home import HomeChannel, HomeFailed, Reason
from .tools import Catalogue, Tools

MINE = "home_mine"
TOPIC = "home_topic"
PIN = "home_pin"
NAMES = (MINE, TOPIC, PIN)
LATEST = 50
TOPIC_MOST = 1024
INSTRUCTIONS = (
    "Your channel on the household's Discord server is yours to keep as you like: its topic, what you pin and what "
    f"you post there. {MINE} lists your own recent messages there and which are pinned; {TOPIC} sets the channel's "
    f"topic; {PIN} pins or unpins one of your own messages by its id. What you write as your reply is posted there "
    "only if you set `says` to reply.")
_HINTS: dict[Reason, str] = {
    "no_token": "her Discord connection has no token",
    "refused": "Discord would not let her; the server's owner can allow Manage Channels and Manage Messages for her "
               "on her channel",
    "not_found": "Discord has no such channel or message",
    "not_hers": "she pins and unpins only her own messages",
    "unreachable": "Discord did not answer, or asked her to slow down; try again later",
    "unexpected": "Discord refused it or answered with something unexpected (a channel holds at most 50 pins)"}


def specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(MINE, "List your own latest messages in your channel, oldest first, with their ids and whether each "
                 "is pinned.", {"type": "object", "properties": {}}, True, outside=False),
        ToolSpec(TOPIC, "Set your channel's topic; an empty one clears it.", {
            "type": "object", "properties": {"topic": {
                "type": "string", "description": f"The topic, at most {TOPIC_MOST} characters"}},
            "required": ["topic"]}, outside=False, tier="judged", label="Set her channel's topic"),
        ToolSpec(PIN, "Pin or unpin one of your own messages in your channel.", {
            "type": "object", "properties": {
                "message": {"type": "string", "description": f"The message's id, from {MINE}"},
                "pinned": {"type": "boolean", "description": "true to pin it, false to unpin it"}},
            "required": ["message", "pinned"]}, outside=False, tier="runs", label="Pinned or unpinned her message"))


class HomeTools(Tools):
    def __init__(self, channel_id: int) -> None:
        self._channel = channel_id
        self._specs = {s.name: s for s in specs()}

    async def catalogue(self) -> Catalogue:
        return Catalogue(tuple(self._specs.values()), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments or Discord failing are each an error result."""
        started = time.monotonic()
        spec = self._specs.get(call.name)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        home = services.get(HomeChannel)
        try:
            check_names(call.arguments, spec)
            if call.name == MINE:
                mine = await home.mine(self._channel, LATEST)
                return bench_results.ok(call, started, {"messages": [
                    {"id": str(m.id), "at": m.at, "text": m.text, "pinned": m.pinned} for m in mine]}, rows=len(mine))
            if call.name == TOPIC:
                await home.set_topic(self._channel, _topic(call.arguments.get("topic")))
                return bench_results.ok(call, started, {"topic": "set"})
            pinned = _pinned(call.arguments.get("pinned"))
            await home.pin(self._channel, _message(call.arguments.get("message")), pinned)
            return bench_results.ok(call, started, {"pinned": pinned})
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except HomeFailed as e:
            return bench_results.failed(call, started, e.reason, _HINTS[e.reason])


def _topic(value: object) -> str:
    if not isinstance(value, str) or len(value) > TOPIC_MOST:
        raise BadArguments(f"topic is text of at most {TOPIC_MOST} characters")
    return value


def _message(value: object) -> int:
    if not isinstance(value, str) or not (value.isascii() and value.isdigit()) or not 0 < int(value) < 2**63:
        raise BadArguments(f"message is a message id from {MINE}")
    return int(value)


def _pinned(value: object) -> bool:
    if type(value) is not bool:
        raise BadArguments("pinned is true or false")
    return value
